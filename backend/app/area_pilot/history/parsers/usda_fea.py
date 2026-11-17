"""USDA ERS Food Environment Atlas history parser (earlier-year county variables)."""
from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from app.area_pilot.history.rows import HistoryRow, MAX_SCALE, make_row, row_problems, to_decimal
from app.area_pilot.usda_fea import classify_value, load_registry, parse_variable_list

SCHEMA_VERSION = '1'
_SCALE_QUANTUM = Decimal(10) ** -MAX_SCALE


def _header_sha(header: list[str]) -> str:
    return hashlib.sha256('|'.join(header).encode('utf-8')).hexdigest()


def _validate_config_and_variables(
    config: dict, variables_path: Path
) -> tuple[dict[str, tuple[dict, dict, dict]], set[str]]:
    if '_index' not in config:
        config['_index'] = {
            (m['measure_id'], p['period']): (m, p)
            for m in config.get('measures', [])
            for p in m.get('periods', [])
        }
    selection = config.get('selection') or {}
    expected_header = selection.get('expected_values_header')
    if not expected_header:
        raise ValueError('USDA FEA history registry is missing selection.expected_values_header')
    sentinels = selection.get('sentinels')
    if not isinstance(sentinels, dict) or not sentinels:
        raise ValueError('USDA FEA history registry is missing selection.sentinels')

    current_registry = load_registry()
    current_measures = {m['measure_id']: m for m in current_registry['measures']}
    variable_lookup = parse_variable_list(variables_path, current_registry)

    declared_by_code: dict[str, tuple[dict, dict, dict]] = {}
    declared_periods: set[str] = set()
    for measure in config.get('measures', []):
        mid = measure.get('measure_id')
        if mid not in current_measures:
            raise ValueError(f'USDA FEA history measure {mid!r} is not in the current USDA FEA registry')
        current_measure = current_measures[mid]
        allowed_levels = measure.get('levels', config.get('levels', []))
        if allowed_levels != ['county']:
            raise ValueError(f'USDA FEA history measure {mid} must declare county level only, got {allowed_levels!r}')

        for spec in measure.get('periods', []):
            if not spec.get('available', True):
                continue
            period = str(spec.get('period', ''))
            if not re.fullmatch(r'[0-9]{4}', period):
                raise ValueError(f'USDA FEA measure {mid} has malformed period {period!r}')
            locator = spec.get('locator') or {}
            var_code = locator.get('variable_code')
            var_name = locator.get('variable_name')
            if not var_code or not var_name:
                raise ValueError(f'USDA FEA measure {mid} period {period} locator is incomplete: {locator!r}')
            if var_code in declared_by_code:
                raise ValueError(f'USDA FEA history registry repeats locator variable_code {var_code!r}')

            var_row = variable_lookup.get(var_code)
            if var_row is None:
                raise ValueError(f'USDA FEA VariableList.csv is missing locator variable_code {var_code!r}')
            actual_name = var_row.get('Variable_Name', '').strip()
            if actual_name != var_name:
                raise ValueError(
                    f'USDA FEA VariableList.csv name for {var_code!r} is {actual_name!r}; expected {var_name!r}'
                )
            if '*' in actual_name:
                raise ValueError(f'USDA FEA marks {var_code!r} as a state-level (*) measure')

            classify_measure = {
                'measure_id': mid,
                'variable_code': var_code,
                'variable_name': var_name,
                'kind': current_measure['kind'],
                'plausible_range': current_measure['plausible_range'],
            }
            declared_by_code[var_code] = (measure, spec, classify_measure)
            declared_periods.add(period)

    if not declared_by_code:
        raise ValueError('USDA FEA history registry declares no available periods')
    return declared_by_code, declared_periods


def parse(config: dict, files: dict[str, Path], evidence: dict) -> Iterator[tuple[str, list[HistoryRow]]]:
    """Parse archived USDA Food Environment Atlas CSV files into per-period HistoryRow parts."""
    for role in ('values_csv', 'variables_csv'):
        if role not in files:
            raise ValueError(f'Missing required source file role {role!r}')
    values_path = Path(files['values_csv'])
    variables_path = Path(files['variables_csv'])

    declared_by_code, declared_periods = _validate_config_and_variables(config, variables_path)
    selection = config['selection']
    expected_header = selection['expected_values_header']
    classify_cfg = {'sentinels': selection['sentinels']}

    variable_counts: Counter[str] = Counter()
    ignored_variables: Counter[str] = Counter()
    padded_fips_by_period: Counter[str] = Counter()
    excluded_rows: dict[str, Counter[str]] = defaultdict(Counter)
    kept_rows_by_variable: Counter[str] = Counter()
    seen_fips_var: set[tuple[str, str]] = set()
    rows_by_period: dict[str, list[HistoryRow]] = {p: [] for p in declared_periods}

    total_rows = 0
    with values_path.open(newline='', encoding='utf-8-sig') as source:
        reader = csv.reader(source)
        header = next(reader, None)
        if header != expected_header:
            raise ValueError(
                f'USDA FEA StateAndCountyData.csv header {header!r} does not match expected {expected_header!r}'
            )

        for raw_row in reader:
            total_rows += 1
            if len(raw_row) != len(expected_header):
                raise ValueError(
                    f'USDA FEA values row {total_rows} has {len(raw_row)} columns; expected {len(expected_header)}'
                )
            raw_fips, _state, _county, code, raw_val = (cell.strip() for cell in raw_row)
            variable_counts[code] += 1

            target = declared_by_code.get(code)
            if target is None:
                ignored_variables[code] += 1
                continue

            measure, spec, classify_measure = target
            period = str(spec['period'])

            if len(raw_fips) == 4 and raw_fips.isdigit():
                fips = raw_fips.zfill(5)
                padded_fips_by_period[period] += 1
            else:
                fips = raw_fips

            if len(fips) != 5 or not fips.isdigit():
                raise ValueError(
                    f'Unexpected non-5-digit FIPS {raw_fips!r} for variable {code!r} on row {total_rows}'
                )

            dup_key = (fips, code)
            if dup_key in seen_fips_var:
                raise ValueError(f'Duplicate USDA FEA (FIPS, Variable_Code) key: {dup_key}')
            seen_fips_var.add(dup_key)

            if fips.endswith('000'):
                excluded_rows[period]['state_or_national_fips_000'] += 1
                continue

            parsed_val, status = classify_value(raw_val, classify_measure, classify_cfg)
            val = to_decimal(raw_val) if parsed_val is not None else None
            row = make_row(
                config,
                measure['measure_id'],
                period,
                'county',
                fips,
                value=val,
                status=status,
                source_value=raw_val,
            )
            problems = row_problems(row, config)
            if problems:
                raise ValueError(f'USDA FEA row {row.key} failed row contract: {problems}')
            rows_by_period[period].append(row)
            kept_rows_by_variable[code] += 1

    missing_periods = sorted(p for p, rows in rows_by_period.items() if not rows)
    if missing_periods:
        raise ValueError(f'USDA FEA values CSV has no kept rows for declared periods: {missing_periods}')

    evidence.clear()
    evidence.update({
        'header_sha256': _header_sha(header),
        'column_count': len(header),
        'total_rows': total_rows,
        'variable_counts': dict(sorted(variable_counts.items())),
        'ignored_variables': dict(sorted(ignored_variables.items())),
        'padded_fips_total': sum(padded_fips_by_period.values()),
        'padded_fips_by_period': dict(sorted(padded_fips_by_period.items())),
        'excluded_rows': {
            p: dict(sorted(counts.items())) for p, counts in sorted(excluded_rows.items())
        },
        'kept_rows_by_variable': dict(sorted(kept_rows_by_variable.items())),
        'emitted_rows': {p: len(rows_by_period[p]) for p in sorted(rows_by_period)},
    })

    for period in sorted(rows_by_period):
        yield f'period_{period}', sorted(rows_by_period[period], key=lambda r: r.key)
