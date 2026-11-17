"""CDC BRFSS state prevalence history parser (years 2017-2022)."""
from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

from app.area_pilot.brfss import load_registry, location_kind, parse_observation
from app.area_pilot.history.rows import HistoryRow, make_row, row_problems, to_decimal

SCHEMA_VERSION = '1'
EXPECTED_HEADER = [
    'year',
    'locationabbr',
    'locationdesc',
    'class',
    'topic',
    'question',
    'response',
    'break_out',
    'break_out_category',
    'sample_size',
    'data_value',
    'confidence_limit_low',
    'confidence_limit_high',
    'display_order',
    'data_value_unit',
    'data_value_type',
    'data_value_footnote_symbol',
    'data_value_footnote',
    'datasource',
    'classid',
    'topicid',
    'locationid',
    'breakoutid',
    'breakoutcategoryid',
    'questionid',
    'responseid',
    'geolocation',
]


def _header_sha(header: list[str]) -> str:
    return hashlib.sha256('|'.join(header).encode('utf-8')).hexdigest()


def _build_selection_map(config: dict) -> tuple[dict, dict[tuple[str, str, str], tuple[dict, dict, dict]], set[str]]:
    if '_index' not in config:
        config['_index'] = {
            (m['measure_id'], p['period']): (m, p)
            for m in config.get('measures', [])
            for p in m.get('periods', [])
        }
    selection = config.get('selection') or {}
    expected_locations = selection.get('expected_locations')
    if not isinstance(expected_locations, dict) or not expected_locations:
        raise ValueError('BRFSS history registry is missing selection.expected_locations')

    current_registry = load_registry()
    if selection.get('source_filters') != current_registry['source_filters']:
        raise ValueError('BRFSS history selection.source_filters differs from current registry')
    if selection.get('median_locations') != current_registry['median_locations']:
        raise ValueError('BRFSS history selection.median_locations differs from current registry')
    if selection.get('source_only_locations') != current_registry['source_only_locations']:
        raise ValueError('BRFSS history selection.source_only_locations differs from current registry')

    obs_config = dict(current_registry, expected_locations=expected_locations)
    current_measures = {m['measure_id']: m for m in current_registry['measures']}

    by_selection: dict[tuple[str, str, str], tuple[dict, dict, dict]] = {}
    declared_years: set[str] = set()
    for measure in config.get('measures', []):
        mid = measure.get('measure_id')
        if mid not in current_measures:
            raise ValueError(f'BRFSS history measure {mid!r} is not in the current BRFSS registry')
        current_measure = current_measures[mid]
        allowed_levels = measure.get('levels', config.get('levels', []))
        if allowed_levels != ['state']:
            raise ValueError(f'BRFSS history measure {mid} must declare state level only, got {allowed_levels!r}')

        for spec in measure.get('periods', []):
            if not spec.get('available', True):
                continue
            period = str(spec.get('period', ''))
            if not re.fullmatch(r'[0-9]{4}', period) or period not in expected_locations:
                raise ValueError(f'BRFSS measure {mid} period {period!r} has no expected_locations entry')
            locator = spec.get('locator') or {}
            question_id = locator.get('question_id')
            response_id = locator.get('response_id')
            if not question_id or not response_id:
                raise ValueError(f'BRFSS measure {mid} period {period} locator is incomplete: {locator!r}')

            sel_key = (period, question_id, response_id)
            if sel_key in by_selection:
                raise ValueError(f'BRFSS history registry repeats selection {sel_key}')

            merged_measure = dict(
                current_measure,
                observation_period=period,
                question_id=question_id,
                response_id=response_id,
            )
            by_selection[sel_key] = (measure, spec, merged_measure)
            declared_years.add(period)

    if not by_selection:
        raise ValueError('BRFSS history registry declares no available periods')
    return obs_config, by_selection, declared_years


def parse(config: dict, files: dict[str, Path], evidence: dict) -> Iterator[tuple[str, list[HistoryRow]]]:
    """Parse archived CDC BRFSS Socrata CSV into per-year HistoryRow parts."""
    if 'brfss_csv' not in files:
        raise ValueError("Missing required source file role 'brfss_csv'")
    csv_path = Path(files['brfss_csv'])

    obs_config, by_selection, declared_years = _build_selection_map(config)
    median_footnote = obs_config['footnotes']['median']

    year_counts: Counter[str] = Counter()
    dropped_locations: dict[str, Counter[str]] = defaultdict(Counter)
    kept_state_rows: Counter[str] = Counter()
    status_counts: dict[str, Counter[str]] = defaultdict(Counter)
    blank_median_footnotes_by_year: Counter[str] = Counter()
    seen_keys: set[tuple[str, str, str]] = set()
    seen_measure_periods: set[tuple[str, str]] = set()
    rows_by_year: dict[str, list[HistoryRow]] = {y: [] for y in declared_years}

    total_rows = 0
    with csv_path.open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        header = list(reader.fieldnames or [])
        if header != EXPECTED_HEADER:
            raise ValueError(
                f'BRFSS CSV header {header!r} does not match expected {EXPECTED_HEADER!r}'
            )

        for raw_row in reader:
            total_rows += 1
            if None in raw_row or any(v is None for v in raw_row.values()):
                raise ValueError(f'BRFSS CSV row {total_rows} has an unexpected column count')

            raw_data_value = raw_row['data_value']
            raw_ci_low = raw_row['confidence_limit_low']
            raw_ci_high = raw_row['confidence_limit_high']
            row = {k: (None if v == '' else v) for k, v in raw_row.items()}

            sel_key = (row.get('year'), row.get('questionid'), row.get('responseid'))
            target = by_selection.get(sel_key)
            if target is None:
                raise ValueError(
                    f'BRFSS CSV row {total_rows} does not match any declared (year, question_id, response_id): {sel_key!r}'
                )
            measure, spec, merged_measure = target
            year = str(spec['period'])
            year_counts[year] += 1

            geoid = row.get('locationid') or ''
            if location_kind(obs_config, geoid) == 'median' and row.get('data_value_footnote_symbol') is None:
                row['data_value_footnote_symbol'] = median_footnote
                blank_median_footnotes_by_year[year] += 1

            obs = parse_observation(row, merged_measure, obs_config)

            dup_key = (measure['measure_id'], year, geoid)
            if dup_key in seen_keys:
                raise ValueError(f'Duplicate BRFSS (measure, year, location) key: {dup_key}')
            seen_keys.add(dup_key)

            kind = obs['location_kind']
            if kind in ('median', 'source_only'):
                dropped_locations[year][kind] += 1
                continue
            if kind != 'state':
                raise ValueError(f'Unexpected BRFSS location_kind {kind!r} for {geoid!r} in {year}')

            val = to_decimal(raw_data_value) if obs['value'] is not None else None
            low = to_decimal(raw_ci_low) if obs['ci_low'] is not None else None
            high = to_decimal(raw_ci_high) if obs['ci_high'] is not None else None
            status = obs['status']

            history_row = make_row(
                config,
                measure['measure_id'],
                year,
                'state',
                geoid,
                value=val,
                status=status,
                source_value=raw_data_value,
                low=low,
                high=high,
            )
            problems = row_problems(history_row, config)
            if problems:
                raise ValueError(f'BRFSS row {history_row.key} failed row contract: {problems}')

            rows_by_year[year].append(history_row)
            kept_state_rows[year] += 1
            status_counts[year][status] += 1
            seen_measure_periods.add((measure['measure_id'], year))

    expected_measure_periods = {(m['measure_id'], spec['period']) for m, spec, _ in by_selection.values()}
    missing_measure_periods = sorted(expected_measure_periods - seen_measure_periods)
    if missing_measure_periods:
        raise ValueError(f'BRFSS CSV has no state rows for declared measure-periods: {missing_measure_periods}')

    evidence.clear()
    evidence.update({
        'header_sha256': _header_sha(header),
        'column_count': len(header),
        'total_rows': total_rows,
        'year_counts': dict(sorted(year_counts.items())),
        'dropped_locations': {
            y: dict(sorted(counts.items())) for y, counts in sorted(dropped_locations.items())
        },
        'dropped_totals': {
            'median': sum(c.get('median', 0) for c in dropped_locations.values()),
            'source_only': sum(c.get('source_only', 0) for c in dropped_locations.values()),
        },
        'blank_median_footnotes_by_year': dict(sorted(blank_median_footnotes_by_year.items())),
        'status_counts': {
            y: dict(sorted(counts.items())) for y, counts in sorted(status_counts.items())
        },
        'emitted_rows': {y: len(rows_by_year[y]) for y in sorted(rows_by_year)},
        'emitted_total': sum(len(rows) for rows in rows_by_year.values()),
    })

    for year in sorted(rows_by_year):
        yield f'year_{year}', sorted(rows_by_year[year], key=lambda r: r.key)
