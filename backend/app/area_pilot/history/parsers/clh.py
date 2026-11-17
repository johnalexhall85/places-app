"""AHRQ Community-Level Health (CLH) v2.0 county and tract history parser (file years 2018-2022)."""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Iterator

import openpyxl

from app.area_pilot.clh import load_registry, parse_value
from app.area_pilot.history.rows import HistoryRow, make_row, row_problems

SCHEMA_VERSION = '1'
TERRITORY_PREFIXES = ('60', '66', '69', '78')
ROLE_RE = re.compile(r'^clh(20[0-9]{2})_(county|tract)$')


def _header_sha(header: list[str]) -> str:
    return hashlib.sha256('|'.join(header).encode('utf-8')).hexdigest()


def _validate_config(
    config: dict,
    files: dict[str, Path],
) -> tuple[
    list[tuple[str, str, str]],
    dict[tuple[str, str], list[tuple[dict, dict, dict, str]]],
]:
    if '_index' not in config:
        config['_index'] = {
            (m['measure_id'], p['period']): (m, p)
            for m in config.get('measures', [])
            for p in m.get('periods', [])
        }

    levels = list(config.get('levels') or [])
    if not levels or not set(levels) <= {'county', 'tract'}:
        raise ValueError(f'CLH history levels must be within county/tract, got {levels!r}')

    selection = config.get('selection') or {}
    if selection.get('sheets') != ['Layout', 'Data']:
        raise ValueError(f'CLH history selection.sheets must be [\'Layout\', \'Data\'], got {selection.get("sheets")!r}')

    current_registry = load_registry()
    current_measures = {m['measure_id']: m for m in current_registry['measures']}

    measures_by_part: dict[tuple[str, str], list[tuple[dict, dict, dict, str]]] = {}
    seen_part_measures: dict[tuple[str, str], set[str]] = {}

    for measure in config.get('measures', []):
        mid = measure.get('measure_id')
        if mid not in current_measures:
            raise ValueError(f'CLH history measure {mid!r} is not in the current CLH registry')
        current_measure = current_measures[mid]
        unit = current_measure['unit']

        m_levels = list(measure.get('levels', levels))
        if not m_levels or not set(m_levels) <= set(current_measure['geographies']) or not set(m_levels) <= set(levels):
            raise ValueError(
                f'CLH history measure {mid} levels {m_levels!r} outside allowed geographies {current_measure["geographies"]!r}'
            )

        for spec in measure.get('periods', []):
            if not spec.get('available', True):
                continue
            period = str(spec.get('period', ''))
            locator = spec.get('locator') or {}
            file_year = str(locator.get('file_year', ''))
            column = locator.get('column')
            label = locator.get('label')
            if (
                not re.fullmatch(r'20[0-9]{2}', file_year)
                or not column
                or column != mid
                or not label
                or label != current_measure['official_label']
                or not period.endswith(file_year)
            ):
                raise ValueError(f'CLH measure {mid} period {period!r} has invalid locator {locator!r}')

            for level in m_levels:
                key = (file_year, level)
                measures_by_part.setdefault(key, []).append((measure, spec, locator, unit))
                seen = seen_part_measures.setdefault(key, set())
                if mid in seen:
                    raise ValueError(f'Duplicate CLH measure {mid} in part {key}')
                seen.add(mid)

    if not measures_by_part:
        raise ValueError('CLH history registry declares no available periods')

    sources_by_role = {s['role']: s for s in config.get('sources', [])}
    declared_roles: dict[str, tuple[str, str]] = {}
    for file_year, level in sorted(measures_by_part):
        role = f'clh{file_year}_{level}'
        declared_roles[role] = (file_year, level)

    if not files:
        raise ValueError('No CLH source files provided')

    unknown_roles = sorted(set(files) - set(declared_roles) | (set(files) - set(sources_by_role)))
    if unknown_roles:
        raise ValueError(f'Unknown or undeclared CLH source file roles: {unknown_roles}')

    required_source_roles = set(sources_by_role) & set(declared_roles)
    if len(required_source_roles) < len(declared_roles):
        missing = sorted(required_source_roles - set(files))
        if missing:
            raise ValueError(f'Missing required CLH source file roles: {missing}')

    active_parts: list[tuple[str, str, str]] = []
    for file_year in sorted({fy for fy, _ in measures_by_part}):
        for level in ('county', 'tract'):
            role = f'clh{file_year}_{level}'
            if role in files:
                active_parts.append((role, file_year, level))

    return active_parts, measures_by_part


def _parse_workbook(
    config: dict,
    path: Path,
    role: str,
    file_year: str,
    level: str,
    expected_measures: list[tuple[dict, dict, dict, str]],
) -> tuple[list[HistoryRow], dict]:
    expected_year = int(file_year)
    id_field = 'COUNTYFIPS' if level == 'county' else 'TRACTFIPS'
    geoid_re = re.compile(r'^\d{5}$' if level == 'county' else r'^\d{11}$')

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        if workbook.sheetnames != ['Layout', 'Data']:
            raise ValueError(f'CLH {role} workbook worksheets changed: {workbook.sheetnames!r}')

        layout_iter = workbook['Layout'].iter_rows(min_row=1, values_only=True)
        layout_header = next(layout_iter, None)
        if not layout_header or tuple(layout_header[:3]) != ('name', 'label', 'type'):
            raise ValueError(f'CLH {role} Layout header changed: {layout_header!r}')

        layout: dict[str, tuple] = {}
        for row in layout_iter:
            if row and row[0]:
                var_name = row[0]
                if not isinstance(var_name, str) or var_name in layout:
                    raise ValueError(f'Invalid or duplicate CLH {role} Layout variable: {var_name!r}')
                layout[var_name] = row

        verified_layout: dict[str, dict[str, str]] = {}
        for measure, _spec, locator, _unit in expected_measures:
            col = locator['column']
            label = locator['label']
            lrow = layout.get(col)
            if not lrow or len(lrow) < 3 or lrow[1] != label or lrow[2] != 'num':
                raise ValueError(f'CLH {role} layout changed: {col}')
            verified_layout[col] = {'label': str(lrow[1]), 'type': str(lrow[2])}

        data_sheet = workbook['Data']
        data_iter = data_sheet.iter_rows(min_row=1)
        header_cells = next(data_iter, None)
        if header_cells is None:
            raise ValueError(f'CLH {role} Data sheet is empty')
        if any(cell.data_type == 'f' for cell in header_cells):
            raise ValueError(f'Formula in CLH {role} Data header')

        headers = [cell.value for cell in header_cells]
        if (
            not headers
            or any(h is None or not isinstance(h, str) or h == '' for h in headers)
            or len(headers) != len(set(headers))
            or 'YEAR' not in headers
            or id_field not in headers
            or (level == 'tract' and 'COUNTYFIPS' not in headers)
        ):
            raise ValueError(f'CLH {role} Data headers invalid')

        needed_cols = [
            'YEAR',
            id_field,
            *(['COUNTYFIPS'] if level == 'tract' else []),
            *(loc['column'] for _, _, loc, _ in expected_measures),
        ]
        missing_cols = [c for c in needed_cols if c not in headers]
        if missing_cols:
            raise ValueError(f'CLH {role} Data headers invalid (missing {missing_cols})')

        positions = {name: headers.index(name) for name in needed_cols}
        max_pos = max(positions.values())

        seen_geoids: set[str] = set()
        dropped_territories_by_prefix: Counter[str] = Counter()
        part_statuses: Counter[str] = Counter()
        part_rows: list[HistoryRow] = []
        source_rows = 0

        for row_num, row in enumerate(data_iter, start=2):
            if len(row) <= max_pos:
                raise ValueError(f'CLH {role} Data row {row_num} has fewer columns than expected')
            source_rows += 1

            year_cell = row[positions['YEAR']]
            geoid_cell = row[positions[id_field]]
            geoid = geoid_cell.value

            if (
                year_cell.data_type == 'f'
                or isinstance(year_cell.value, bool)
                or year_cell.value != expected_year
                or geoid_cell.data_type == 'f'
                or geoid_cell.data_type != 's'
                or not isinstance(geoid, str)
                or not geoid_re.fullmatch(geoid)
            ):
                raise ValueError(
                    f'Invalid CLH {role} year or GEOID at row {row_num}: year={year_cell.value!r}, geoid={geoid!r}'
                )

            if geoid in seen_geoids:
                raise ValueError(f'Duplicate CLH {role} {level} GEOID: {geoid}')
            seen_geoids.add(geoid)

            if level == 'tract':
                cfips_cell = row[positions['COUNTYFIPS']]
                if cfips_cell.data_type == 'f' or cfips_cell.data_type != 's' or cfips_cell.value != geoid[:5]:
                    raise ValueError(f'CLH {role} tract parent county mismatch: {geoid}')

            parsed_cells: list[tuple[dict, dict, Decimal | None, str, str]] = []
            for measure, spec, locator, unit in expected_measures:
                cell = row[positions[locator['column']]]
                if cell.data_type == 'f':
                    raise ValueError(f'Formula in CLH {role} selected cell {locator["column"]}: {geoid}')
                raw = cell.value
                _, status, _ = parse_value(raw, unit)
                if raw is None or raw == '':
                    val = None
                    source_value = ''
                else:
                    val = Decimal(str(raw))
                    source_value = str(raw)
                parsed_cells.append((measure, spec, val, status, source_value))

            if geoid[:2] in TERRITORY_PREFIXES:
                dropped_territories_by_prefix[geoid[:2]] += 1
                continue

            for measure, spec, val, status, source_value in parsed_cells:
                history_row = make_row(
                    config,
                    measure['measure_id'],
                    str(spec['period']),
                    level,
                    geoid,
                    value=val,
                    status=status,
                    source_value=source_value,
                )
                problems = row_problems(history_row, config)
                if problems:
                    raise ValueError(f'CLH row {history_row.key} failed row contract: {problems}')
                part_rows.append(history_row)
                part_statuses[status] += 1

        kept_geoids = source_rows - sum(dropped_territories_by_prefix.values())
        if kept_geoids <= 0:
            raise ValueError(f'CLH {role} Data sheet contained no kept {level} rows')

        ordered = sorted(part_rows, key=lambda r: r.key)
        part_info = {
            'header_sha256': _header_sha(headers),
            'header_column_count': len(headers),
            'positions': positions,
            'verified_layout': verified_layout,
            'source_rows': source_rows,
            'dropped_territory_rows': sum(dropped_territories_by_prefix.values()),
            'dropped_territories_by_prefix': dict(sorted(dropped_territories_by_prefix.items())),
            'kept_geographies': kept_geoids,
            'status_counts': dict(sorted(part_statuses.items())),
            'emitted_rows': len(ordered),
        }
        return ordered, part_info
    finally:
        workbook.close()


def parse(config: dict, files: dict[str, Path], evidence: dict) -> Iterator[tuple[str, list[HistoryRow]]]:
    """Stream archived AHRQ CLH v2.0 XLSX workbooks into per-(file_year, level) HistoryRow parts."""
    active_parts, measures_by_part = _validate_config(config, files)

    parts_evidence: dict[str, dict] = {}
    source_row_counts: dict[str, int] = {}
    dropped_territory_rows: dict[str, int] = {}
    dropped_territories_by_prefix: dict[str, dict[str, int]] = {}
    status_counts: dict[str, dict[str, int]] = {}
    emitted_rows: dict[str, int] = {}

    evidence.clear()
    evidence.update({
        'parts': parts_evidence,
        'source_row_counts': source_row_counts,
        'dropped_territory_rows': dropped_territory_rows,
        'dropped_territories_by_prefix': dropped_territories_by_prefix,
        'status_counts': status_counts,
        'emitted_rows': emitted_rows,
        'emitted_total': 0,
    })

    for role, file_year, level in active_parts:
        part_name = f'y{file_year}_{level}'
        expected_measures = measures_by_part[(file_year, level)]
        ordered_rows, part_info = _parse_workbook(
            config,
            Path(files[role]),
            role,
            file_year,
            level,
            expected_measures,
        )

        parts_evidence[part_name] = part_info
        source_row_counts[role] = part_info['source_rows']
        dropped_territory_rows[role] = part_info['dropped_territory_rows']
        if part_info['dropped_territories_by_prefix']:
            dropped_territories_by_prefix[role] = part_info['dropped_territories_by_prefix']
        status_counts[part_name] = part_info['status_counts']
        emitted_rows[part_name] = len(ordered_rows)
        evidence['emitted_total'] = sum(emitted_rows.values())

        yield part_name, ordered_rows
