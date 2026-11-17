"""Census ACS 5-year median household income (B19013) history parser (vintages 2019-2023)."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterator

from app.area_pilot.acs import FIELDS, load_registry, parse_observation, parse_response
from app.area_pilot.history.rows import HistoryRow, make_row, row_problems, to_decimal

SCHEMA_VERSION = '1'


def _validate_config(config: dict) -> tuple[set[str], list[str], dict[str, tuple[dict, dict]], dict[tuple[str, str], list[tuple[str, str | None]]]]:
    if '_index' not in config:
        config['_index'] = {
            (m['measure_id'], p['period']): (m, p)
            for m in config.get('measures', [])
            for p in m.get('periods', [])
        }

    current_registry = load_registry()
    supported_states = set(current_registry['supported_state_fips'])
    state_fips = list(config.get('state_fips') or [])
    if not state_fips or len(state_fips) != len(set(state_fips)):
        raise ValueError('ACS history registry state_fips must be non-empty and unique')
    outside_supported = sorted(set(state_fips) - supported_states)
    if outside_supported:
        raise ValueError(f'ACS history registry state_fips contains unsupported states: {outside_supported}')

    selection = config.get('selection') or {}
    expected_fields = list(selection.get('fields') or [])
    if set(expected_fields) != set(FIELDS) - {'NAME'}:
        raise ValueError(f'ACS history selection.fields {expected_fields!r} does not match expected B19013 fields')

    measures = config.get('measures') or []
    current_measure_id = current_registry['measures'][0]['measure_id']
    if len(measures) != 1 or measures[0].get('measure_id') != current_measure_id:
        raise ValueError(f'ACS history registry must declare single measure {current_measure_id}')
    measure = measures[0]

    by_vintage: dict[str, tuple[dict, dict]] = {}
    for spec in measure.get('periods', []):
        if not spec.get('available', True):
            continue
        period = str(spec.get('period', ''))
        locator = spec.get('locator') or {}
        vintage = str(locator.get('vintage', ''))
        if not re.fullmatch(r'20[0-9]{2}', vintage) or not period.endswith(vintage):
            raise ValueError(f'ACS period {period!r} has invalid vintage locator {locator!r}')
        if vintage in by_vintage:
            raise ValueError(f'ACS history registry repeats vintage {vintage}')
        by_vintage[vintage] = (measure, spec)

    if not by_vintage:
        raise ValueError('ACS history registry declares no available periods')

    sources_by_role = {s['role']: s for s in config.get('sources', [])}
    roles_by_part: dict[tuple[str, str], list[tuple[str, str | None]]] = {}
    for vintage in sorted(by_vintage):
        for level in config['levels']:
            base_role = f'acs{vintage}_{level}'
            if level == 'state':
                if base_role not in sources_by_role:
                    raise ValueError(f'ACS history registry is missing source role {base_role!r}')
                roles_by_part[(vintage, level)] = [(base_role, None)]
            else:
                part_roles: list[tuple[str, str | None]] = []
                for st in state_fips:
                    expanded_role = f'{base_role}_{st}'
                    if base_role not in sources_by_role and expanded_role not in sources_by_role:
                        raise ValueError(f'ACS history registry is missing source role {base_role!r}')
                    part_roles.append((expanded_role, st))
                roles_by_part[(vintage, level)] = part_roles

    return supported_states, state_fips, by_vintage, roles_by_part


def _load_and_parse_response(path: Path, level: str, state: str | None, expected_fields: list[str]) -> dict[str, dict]:
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception as exc:
        raise ValueError(f'Invalid JSON in {path.name}: {exc}') from exc

    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[0], list):
        raise ValueError('Invalid or empty Census response')

    raw_header = payload[0]
    if len(raw_header) != len(set(raw_header)):
        raise ValueError('Census response header contains duplicate columns')
    if not set(expected_fields) <= set(raw_header):
        raise ValueError('Census response header changed')

    if 'NAME' not in raw_header:
        adapted_payload = [
            ['NAME', *raw_header],
            *[
                ['', *row] if isinstance(row, list) and len(row) == len(raw_header) else row
                for row in payload[1:]
            ],
        ]
    else:
        adapted_payload = payload

    records = parse_response(adapted_payload, level, state)
    if not records:
        raise ValueError(f'Empty Census response in {path.name}')
    return records


def _format_source_value(raw_estimate: str | None, raw_annotation: str | None) -> str:
    est = '' if raw_estimate is None else str(raw_estimate).strip()
    ann = '' if raw_annotation is None else str(raw_annotation).strip()
    return f'{est}|{ann}' if ann else est


def parse(config: dict, files: dict[str, Path], evidence: dict) -> Iterator[tuple[str, list[HistoryRow]]]:
    """Parse archived Census ACS 5-year B19013 JSON responses into per-(vintage, level) HistoryRow parts."""
    supported_states, state_fips, by_vintage, roles_by_part = _validate_config(config)
    configured_states = set(state_fips)
    expected_fields = list(config['selection']['fields'])

    expected_roles = {
        role
        for part_roles in roles_by_part.values()
        for role, _ in part_roles
    }
    missing_roles = sorted(expected_roles - set(files))
    if missing_roles:
        raise ValueError(f'Missing required ACS source file roles: {missing_roles}')
    extra_roles = sorted(set(files) - expected_roles)
    if extra_roles:
        raise ValueError(f'Unexpected ACS source file roles outside configured state_fips/vintages: {extra_roles}')

    row_counts: dict[str, dict[str, int]] = {v: {} for v in sorted(by_vintage)}
    status_counts: dict[str, dict[str, dict[str, int]]] = {v: {} for v in sorted(by_vintage)}
    open_ended_rows: dict[str, dict[str, int]] = {v: {} for v in sorted(by_vintage)}
    emitted_rows: dict[str, int] = {}
    parts_to_yield: list[tuple[str, list[HistoryRow]]] = []

    for vintage in sorted(by_vintage):
        measure, spec = by_vintage[vintage]
        mid = measure['measure_id']
        period = str(spec['period'])

        for level in config['levels']:
            part_name = f'v{vintage}_{level}'
            part_rows: list[HistoryRow] = []
            level_statuses: Counter[str] = Counter()
            seen_geoids: set[str] = set()

            for role, expected_state in roles_by_part[(vintage, level)]:
                if expected_state is not None and expected_state not in configured_states:
                    raise ValueError(f'Role {role} is for state {expected_state!r} outside state_fips')
                records = _load_and_parse_response(Path(files[role]), level, expected_state, expected_fields)

                if level == 'state':
                    record_states = set(records)
                    outside_supported = sorted(record_states - supported_states)
                    if outside_supported:
                        raise ValueError(f'{role} contains states outside supported state_fips: {outside_supported}')
                    if record_states != supported_states and not (record_states <= configured_states):
                        outside_cfg = sorted(record_states - configured_states)
                        raise ValueError(f'{role} contains states outside configured state_fips: {outside_cfg}')
                    if not (configured_states <= record_states):
                        missing_st = sorted(configured_states - record_states)
                        raise ValueError(f'{role} is missing configured states: {missing_st}')

                for geoid, raw_row in sorted(records.items()):
                    if geoid in seen_geoids:
                        raise ValueError(f'Duplicate ACS geography key {level}:{geoid} in vintage {vintage}')
                    seen_geoids.add(geoid)

                    obs = parse_observation(raw_row)
                    val = to_decimal(raw_row['B19013_001E']) if obs['value'] is not None else None
                    moe = to_decimal(raw_row['B19013_001M']) if obs['moe'] is not None else None
                    status = obs['status']
                    source_value = _format_source_value(raw_row.get('B19013_001E'), raw_row.get('B19013_001EA'))

                    history_row = make_row(
                        config,
                        mid,
                        period,
                        level,
                        geoid,
                        value=val,
                        status=status,
                        source_value=source_value,
                        moe=moe,
                    )
                    problems = row_problems(history_row, config)
                    if problems:
                        raise ValueError(f'ACS row {history_row.key} failed row contract: {problems}')

                    part_rows.append(history_row)
                    level_statuses[status] += 1

            ordered = sorted(part_rows, key=lambda r: r.key)
            row_counts[vintage][level] = len(ordered)
            status_counts[vintage][level] = dict(sorted(level_statuses.items()))
            open_ended_rows[vintage][level] = level_statuses.get('open_ended', 0)
            emitted_rows[part_name] = len(ordered)
            parts_to_yield.append((part_name, ordered))

    evidence.clear()
    evidence.update({
        'vintages': sorted(by_vintage),
        'state_fips': state_fips,
        'row_counts': row_counts,
        'status_counts': status_counts,
        'open_ended_rows': open_ended_rows,
        'emitted_rows': emitted_rows,
        'emitted_total': sum(emitted_rows.values()),
    })

    for part_name, ordered_rows in parts_to_yield:
        yield part_name, ordered_rows
