"""CMS Original Medicare Geographic Variation (OM GV) history parser (years 2019-2023)."""
from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

from app.area_pilot.cms_gv import _exclusion_for, header_sha, load_registry, parse_value, range_problems
from app.area_pilot.history.rows import LEVEL_LENGTH, HistoryRow, make_row, row_problems, to_decimal

SCHEMA_VERSION = '1'
EXPECTED_DIMENSIONS = ['YEAR', 'BENE_GEO_LVL', 'BENE_GEO_DESC', 'BENE_GEO_CD', 'BENE_AGE_LVL']


def _validate_config(config: dict) -> tuple[dict[str, dict], dict[str, list[tuple[dict, dict, dict]]]]:
    if ' _index' not in config and '_index' not in config:
        config['_index'] = {
            (m['measure_id'], p['period']): (m, p)
            for m in config.get('measures', [])
            for p in m.get('periods', [])
        }
    selection = config.get('selection') or {}
    if selection.get('dimensions') != EXPECTED_DIMENSIONS:
        raise ValueError(f'CMS GV selection dimensions differ from expected: {selection.get("dimensions")!r}')
    if selection.get('age_level') != 'All':
        raise ValueError(f'CMS GV selection age_level must be All, got {selection.get("age_level")!r}')
    if selection.get('geo_levels') != {'State': 'state', 'County': 'county'}:
        raise ValueError(f'CMS GV selection geo_levels differ from expected: {selection.get("geo_levels")!r}')

    current_registry = load_registry()
    current_measures = {m['measure_id']: m for m in current_registry['measures']}

    declared_by_year: dict[str, list[tuple[dict, dict, dict]]] = defaultdict(list)
    for measure in config.get('measures', []):
        mid = measure.get('measure_id')
        if mid not in current_measures:
            raise ValueError(f'CMS GV history measure {mid!r} is not in the current CMS GV registry')
        current_measure = current_measures[mid]
        if measure.get('source_field') != current_measure['source_field']:
            raise ValueError(
                f'CMS GV measure {mid} source_field {measure.get("source_field")!r} '
                f'differs from current registry {current_measure["source_field"]!r}'
            )
        for spec in measure.get('periods', []):
            if not spec.get('available', True):
                continue
            period = str(spec.get('period', ''))
            locator_year = str((spec.get('locator') or {}).get('YEAR', ''))
            if not re.fullmatch(r'[0-9]{4}', period) or locator_year != period:
                raise ValueError(f'CMS GV measure {mid} period {period!r} has mismatched locator {spec.get("locator")!r}')
            declared_by_year[period].append((measure, spec, current_measure))

    if not declared_by_year:
        raise ValueError('CMS GV history registry declares no available periods')
    return current_measures, dict(declared_by_year)


def parse(config: dict, files: dict[str, Path], evidence: dict) -> Iterator[tuple[str, list[HistoryRow]]]:
    """Parse archived CMS OM GV CSV into per-year HistoryRow parts."""
    if 'gv_csv' not in files:
        raise ValueError("Missing required source file role 'gv_csv'")
    csv_path = Path(files['gv_csv'])

    _, declared_by_year = _validate_config(config)
    selection = config['selection']
    dimensions = selection['dimensions']
    target_age = selection['age_level']
    suppression_token = selection.get('suppression_token', '*')
    geo_levels = selection['geo_levels']
    exclusion_cfg = {'expected_source_exclusions': selection.get('exclusions', [])}

    year_counts: Counter[str] = Counter()
    ignored_years: Counter[str] = Counter()
    age_counts: Counter[str] = Counter()
    ignored_age_by_year: dict[str, Counter[str]] = defaultdict(Counter)
    national_rows: Counter[str] = Counter()
    excluded_rows: dict[str, Counter[str]] = defaultdict(Counter)
    kept_geography_rows: dict[str, Counter[str]] = defaultdict(Counter)
    seen_source_keys: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    seen_geoids: dict[str, set[tuple[str, str]]] = defaultdict(set)
    rows_by_year: dict[str, list[HistoryRow]] = {year: [] for year in declared_by_year}

    total_rows = 0
    with csv_path.open(newline='', encoding='utf-8-sig') as source:
        reader = csv.reader(source)
        header = next(reader, None)
        if not header:
            raise ValueError('CMS GV CSV header is missing')
        if len(set(header)) != len(header):
            raise ValueError('CMS GV CSV header contains duplicate column names')
        if header[:len(dimensions)] != dimensions:
            raise ValueError(
                f'CMS GV CSV dimension columns {header[:len(dimensions)]!r} do not match registry {dimensions!r}'
            )
        missing_fields = [m['source_field'] for m in config['measures'] if m['source_field'] not in header]
        if missing_fields:
            raise ValueError(f'CMS GV CSV missing measure fields: {missing_fields}')

        col_idx = {name: idx for idx, name in enumerate(header)}
        idx_year = col_idx['YEAR']
        idx_geo_lvl = col_idx['BENE_GEO_LVL']
        idx_geo_desc = col_idx['BENE_GEO_DESC']
        idx_geo_cd = col_idx['BENE_GEO_CD']
        idx_age_lvl = col_idx['BENE_AGE_LVL']

        for values in reader:
            total_rows += 1
            if len(values) != len(header):
                raise ValueError(f'CMS GV CSV row {total_rows} has {len(values)} columns; expected {len(header)}')

            row_year = values[idx_year].strip()
            if not re.fullmatch(r'[0-9]{4}', row_year):
                raise ValueError(f'CMS GV CSV row {total_rows} has malformed YEAR: {row_year!r}')
            year_counts[row_year] += 1

            source_level = values[idx_geo_lvl].strip()
            desc = values[idx_geo_desc].strip()
            code = values[idx_geo_cd].strip()
            age = values[idx_age_lvl].strip()
            age_counts[age] += 1

            if row_year not in declared_by_year:
                ignored_years[row_year] += 1
                continue

            if age != target_age:
                ignored_age_by_year[row_year][age] += 1
                continue

            source_key = (source_level, code, desc)
            if source_key in seen_source_keys[row_year]:
                raise ValueError(f'Duplicate CMS GV geography key in {row_year}: {source_key}')
            seen_source_keys[row_year].add(source_key)

            if source_level == 'National':
                if code != '':
                    raise ValueError(f'CMS GV National row in {row_year} has unexpected code {code!r}')
                national_rows[row_year] += 1
                continue

            level = geo_levels.get(source_level)
            if level is None:
                raise ValueError(f'Unexpected CMS GV BENE_GEO_LVL {source_level!r} in {row_year}')

            reason = _exclusion_for(source_level, code, desc, exclusion_cfg)
            if reason is not None:
                excluded_rows[row_year][reason] += 1
                continue

            width = LEVEL_LENGTH.get(level, -1)
            if len(code) != width or not code.isdigit() or code == '0' * width or (level == 'county' and code.endswith('000')):
                raise ValueError(f'Unexpected non-FIPS code {code!r} ({desc!r}) for {source_level} in {row_year}')

            if (level, code) in seen_geoids[row_year]:
                raise ValueError(f'Duplicate CMS GV geoid {level}:{code} in {row_year}')
            seen_geoids[row_year].add((level, code))
            kept_geography_rows[row_year][level] += 1

            for measure, _spec, current_measure in declared_by_year[row_year]:
                allowed_levels = measure.get('levels', config['levels'])
                if level not in allowed_levels:
                    continue
                raw = values[col_idx[measure['source_field']]]
                parsed_val, status = parse_value(raw, current_measure, suppression_token)
                val = to_decimal(raw) if parsed_val is not None else None
                if val is not None:
                    probs = range_problems(val, current_measure)
                    if probs:
                        raise ValueError(
                            f'CMS GV value {raw!r} for {measure["measure_id"]} '
                            f'({level}:{code} {row_year}) failed range check: {probs}'
                        )
                row = make_row(
                    config,
                    measure['measure_id'],
                    row_year,
                    level,
                    code,
                    value=val,
                    status=status,
                    source_value=raw,
                )
                problems = row_problems(row, config)
                if problems:
                    raise ValueError(f'CMS GV row {row.key} failed row contract: {problems}')
                rows_by_year[row_year].append(row)

    missing_years = sorted(y for y, rows in rows_by_year.items() if not rows)
    if missing_years:
        raise ValueError(f'CMS GV CSV has no kept rows for declared years: {missing_years}')

    evidence.clear()
    evidence.update({
        'header_sha256': header_sha(header),
        'column_count': len(header),
        'total_rows': total_rows,
        'year_counts': dict(sorted(year_counts.items())),
        'ignored_years': dict(sorted(ignored_years.items())),
        'age_counts': dict(sorted(age_counts.items())),
        'ignored_age_by_year': {
            y: dict(sorted(counts.items())) for y, counts in sorted(ignored_age_by_year.items())
        },
        'national_rows': dict(sorted(national_rows.items())),
        'excluded_rows': {
            y: dict(sorted(counts.items())) for y, counts in sorted(excluded_rows.items())
        },
        'kept_geography_rows': {
            y: dict(sorted(counts.items())) for y, counts in sorted(kept_geography_rows.items())
        },
        'emitted_rows': {y: len(rows_by_year[y]) for y in sorted(rows_by_year)},
    })

    for year in sorted(rows_by_year):
        yield f'year_{year}', sorted(rows_by_year[year], key=lambda r: r.key)
