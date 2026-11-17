"""Census ACS 5-year subject-table community characteristics history parser (vintages 2019-2023)."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

from app.area_pilot.acs_profile import fields, load_registry, parse_observation, parse_response
from app.area_pilot.history.rows import HistoryRow, make_row, row_problems, to_decimal

SCHEMA_VERSION = '1'


def _validate_config(
    config: dict,
) -> tuple[
    dict,
    set[str],
    list[str],
    dict[str, list[tuple[dict, dict, dict]]],
    dict[tuple[str, str], list[tuple[str, str | None]]],
]:
    if '_index' not in config:
        config['_index'] = {
            (m['measure_id'], p['period']): (m, p)
            for m in config.get('measures', [])
            for p in m.get('periods', [])
        }

    if config.get('levels') != ['state', 'county', 'tract']:
        raise ValueError(f'ACS profile history levels must be state, county, tract; got {config.get("levels")!r}')

    current_registry = load_registry()
    supported_states = set(current_registry['supported_state_fips'])
    state_fips = list(config.get('state_fips') or [])
    if not state_fips or len(state_fips) != len(set(state_fips)):
        raise ValueError('ACS profile history registry state_fips must be non-empty and unique')
    outside_supported = sorted(set(state_fips) - supported_states)
    if outside_supported:
        raise ValueError(f'ACS profile history registry state_fips contains unsupported states: {outside_supported}')

    selection = config.get('selection') or {}
    expected_fields = list(selection.get('fields') or [])
    if tuple(expected_fields) != fields(current_registry):
        raise ValueError('ACS profile history selection.fields differs from current registry fields')

    current_measures = {m['measure_id']: m for m in current_registry['measures']}
    measures = config.get('measures') or []
    if len(measures) != len(current_measures):
        raise ValueError(f'ACS profile history registry must declare {len(current_measures)} measures')

    by_vintage: dict[str, list[tuple[dict, dict, dict]]] = defaultdict(list)
    for measure in measures:
        mid = measure.get('measure_id')
        if mid not in current_measures:
            raise ValueError(f'ACS profile history measure {mid!r} is not in the current registry')
        current_measure = current_measures[mid]
        if measure.get('variable') != current_measure['variable']:
            raise ValueError(
                f'ACS profile measure {mid} variable {measure.get("variable")!r} '
                f'differs from current measure variable {current_measure["variable"]!r}'
            )
        seen_vintages: set[str] = set()
        for spec in measure.get('periods', []):
            if not spec.get('available', True):
                continue
            period = str(spec.get('period', ''))
            locator = spec.get('locator') or {}
            vintage = str(locator.get('vintage', ''))
            loc_var = locator.get('variable')
            if loc_var != current_measure['variable']:
                raise ValueError(
                    f'ACS profile measure {mid} period {period!r} locator variable {loc_var!r} '
                    f'differs from current measure variable {current_measure["variable"]!r}'
                )
            if not re.fullmatch(r'20[0-9]{2}', vintage) or not period.endswith(vintage):
                raise ValueError(f'ACS profile measure {mid} period {period!r} has invalid vintage locator {locator!r}')
            if vintage in seen_vintages:
                raise ValueError(f'ACS profile measure {mid} repeats vintage {vintage}')
            seen_vintages.add(vintage)
            by_vintage[vintage].append((measure, spec, current_measure))

    if not by_vintage:
        raise ValueError('ACS profile history registry declares no available periods')

    sources_by_role = {s['role']: s for s in config.get('sources', [])}
    roles_by_part: dict[tuple[str, str], list[tuple[str, str | None]]] = {}
    for vintage in sorted(by_vintage):
        for level in config['levels']:
            base_role = f'acsp{vintage}_{level}'
            if level == 'state':
                if base_role not in sources_by_role:
                    raise ValueError(f'ACS profile history registry is missing source role {base_role!r}')
                roles_by_part[(vintage, level)] = [(base_role, None)]
            else:
                part_roles: list[tuple[str, str | None]] = []
                for st in state_fips:
                    expanded_role = f'{base_role}_{st}'
                    if base_role not in sources_by_role and expanded_role not in sources_by_role:
                        raise ValueError(f'ACS profile history registry is missing source role {base_role!r}')
                    part_roles.append((expanded_role, st))
                roles_by_part[(vintage, level)] = part_roles

    return current_registry, supported_states, state_fips, dict(by_vintage), roles_by_part


def _format_source_value(raw_estimate: str | None, raw_annotation: str | None) -> str:
    est = '' if raw_estimate is None else str(raw_estimate).strip()
    ann = '' if raw_annotation is None else str(raw_annotation).strip()
    return f'{est}|{ann}' if ann else est


def parse(config: dict, files: dict[str, Path], evidence: dict) -> Iterator[tuple[str, list[HistoryRow]]]:
    """Parse archived Census ACS subject-table JSON responses into per-(vintage, level) HistoryRow parts."""
    current_registry, supported_states, state_fips, by_vintage, roles_by_part = _validate_config(config)
    configured_states = set(state_fips)

    expected_roles = {
        role
        for part_roles in roles_by_part.values()
        for role, _ in part_roles
    }
    missing_roles = sorted(expected_roles - set(files))
    if missing_roles:
        raise ValueError(f'Missing required ACS profile source file roles: {missing_roles}')
    extra_roles = sorted(set(files) - expected_roles)
    if extra_roles:
        raise ValueError(f'Unexpected ACS profile source file roles outside configured state_fips/vintages: {extra_roles}')

    geography_counts: dict[str, dict[str, int]] = {v: {} for v in sorted(by_vintage)}
    row_counts: dict[str, dict[str, int]] = {v: {} for v in sorted(by_vintage)}
    status_counts: dict[str, dict[str, dict[str, int]]] = {v: {} for v in sorted(by_vintage)}
    emitted_rows: dict[str, int] = {}
    parts_to_yield: list[tuple[str, list[HistoryRow]]] = []

    for vintage in sorted(by_vintage):
        declared_measures = by_vintage[vintage]
        for level in config['levels']:
            part_name = f'v{vintage}_{level}'
            part_rows: list[HistoryRow] = []
            level_statuses: Counter[str] = Counter()
            seen_geoids: set[str] = set()

            for role, expected_state in roles_by_part[(vintage, level)]:
                if expected_state is not None and expected_state not in configured_states:
                    raise ValueError(f'Role {role} is for state {expected_state!r} outside state_fips')
                path = Path(files[role])
                try:
                    payload = json.loads(path.read_text(encoding='utf-8'))
                except Exception as exc:
                    raise ValueError(f'Invalid JSON in {path.name}: {exc}') from exc

                records, excluded = parse_response(payload, level, current_registry, expected_state)
                if excluded:
                    raise ValueError(f'Unexpected excluded rows in {role}: {sorted(excluded)}')
                if not records:
                    raise ValueError(f'Empty Census response in {path.name}')

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
                        raise ValueError(f'Duplicate ACS profile geography key {level}:{geoid} in vintage {vintage}')
                    seen_geoids.add(geoid)

                    for measure, spec, current_measure in declared_measures:
                        allowed_levels = measure.get('levels', config['levels'])
                        if level not in allowed_levels:
                            continue
                        mid = measure['measure_id']
                        period = str(spec['period'])
                        variable = current_measure['variable']

                        obs = parse_observation(raw_row, current_measure)
                        val = to_decimal(str(obs['value'])) if obs['value'] is not None else None
                        moe = to_decimal(str(obs['moe'])) if obs['moe'] is not None else None
                        status = obs['status']
                        source_value = _format_source_value(
                            raw_row.get(variable + 'E'),
                            raw_row.get(variable + 'EA'),
                        )

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
                            raise ValueError(f'ACS profile row {history_row.key} failed row contract: {problems}')

                        part_rows.append(history_row)
                        level_statuses[status] += 1

            ordered = sorted(part_rows, key=lambda r: r.key)
            geography_counts[vintage][level] = len(seen_geoids)
            row_counts[vintage][level] = len(ordered)
            status_counts[vintage][level] = dict(sorted(level_statuses.items()))
            emitted_rows[part_name] = len(ordered)
            parts_to_yield.append((part_name, ordered))

    evidence.clear()
    evidence.update({
        'vintages': sorted(by_vintage),
        'state_fips': state_fips,
        'geography_counts': geography_counts,
        'row_counts': row_counts,
        'status_counts': status_counts,
        'emitted_rows': emitted_rows,
        'emitted_total': sum(emitted_rows.values()),
    })

    for part_name, ordered_rows in parts_to_yield:
        yield part_name, ordered_rows
