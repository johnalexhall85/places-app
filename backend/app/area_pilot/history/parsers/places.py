"""CDC PLACES county and tract history parser (releases 2020-2024, data years 2017-2022)."""
from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from app.area_pilot.history.rows import HistoryRow, make_row, row_problems, to_decimal

SCHEMA_VERSION = '1'
ZERO = Decimal('0')
HUNDRED = Decimal('100')


def _header_sha(header: list[str]) -> str:
    return hashlib.sha256('|'.join(header).encode('utf-8')).hexdigest()


def _validate_config(
    config: dict,
) -> tuple[
    str,
    list[str],
    dict[str, list[str]],
    dict[tuple[str, str, str], tuple[dict, dict]],
    dict[tuple[str, str], str],
]:
    if '_index' not in config:
        config['_index'] = {
            (m['measure_id'], p['period']): (m, p)
            for m in config.get('measures', [])
            for p in m.get('periods', [])
        }

    if config.get('levels') != ['county', 'tract']:
        raise ValueError(f'PLACES history levels must be county and tract, got {config.get("levels")!r}')

    selection = config.get('selection') or {}
    datavaluetypeid = selection.get('datavaluetypeid')
    if datavaluetypeid != 'CrdPrv':
        raise ValueError(f'PLACES selection.datavaluetypeid must be CrdPrv, got {datavaluetypeid!r}')
    releases_cfg = selection.get('releases') or {}
    if not releases_cfg:
        raise ValueError('PLACES history registry is missing selection.releases')

    declared_by_locator: dict[tuple[str, str, str], tuple[dict, dict]] = {}
    winning_release_by_measure_year: dict[tuple[str, str], str] = {}
    releases_used: set[str] = set()

    for measure in config.get('measures', []):
        mid = measure.get('measure_id')
        if not mid:
            raise ValueError('PLACES history measure missing measure_id')
        for spec in measure.get('periods', []):
            if not spec.get('available', True):
                continue
            period = str(spec.get('period', ''))
            locator = spec.get('locator') or {}
            release = str(locator.get('release', ''))
            measureid = str(locator.get('measureid', ''))
            year = str(locator.get('year', ''))
            if (
                not re.fullmatch(r'20[0-9]{2}', period)
                or year != period
                or release not in releases_cfg
                or not measureid
            ):
                raise ValueError(f'PLACES measure {mid} period {period!r} has invalid locator {locator!r}')
            loc_key = (release, measureid, year)
            if loc_key in declared_by_locator:
                raise ValueError(f'PLACES history registry repeats locator {loc_key}')
            if (measureid, year) in winning_release_by_measure_year:
                raise ValueError(f'PLACES history registry declares duplicate (measureid, year) {(measureid, year)}')
            declared_by_locator[loc_key] = (measure, spec)
            winning_release_by_measure_year[(measureid, year)] = release
            releases_used.add(release)

    if not declared_by_locator:
        raise ValueError('PLACES history registry declares no available periods')

    sources_by_role = {s['role']: s for s in config.get('sources', [])}
    expected_headers: dict[str, list[str]] = {}
    for release in sorted(releases_used):
        for level in ('county', 'tract'):
            role = f'places{release}_{level}'
            src = sources_by_role.get(role)
            if src is None:
                raise ValueError(f'PLACES history registry is missing source role {role!r}')
            select_cols = ((src.get('params') or {}).get('$select') or '').split(',')
            select_cols = [c.strip() for c in select_cols if c.strip()]
            if not select_cols:
                raise ValueError(f'PLACES source role {role!r} is missing params.$select')
            expected_headers[role] = select_cols

    return (
        datavaluetypeid,
        sorted(releases_used),
        expected_headers,
        declared_by_locator,
        winning_release_by_measure_year,
    )


def _build_2020_county_map(tract_path: Path, expected_header: list[str]) -> dict[tuple[str, str], str]:
    """Stream places2020_tract.csv to map (stateabbr, countyname) -> countyfips."""
    codes_by_name: dict[tuple[str, str], set[str]] = defaultdict(set)
    with tract_path.open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        header = list(reader.fieldnames or [])
        if header != expected_header:
            raise ValueError(
                f'PLACES places2020_tract CSV header {header!r} does not match expected {expected_header!r}'
            )
        for row_num, row in enumerate(reader, start=1):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f'PLACES places2020_tract row {row_num} has an unexpected column count')
            stateabbr = row['stateabbr'].strip()
            countyname = row['countyname'].strip()
            countyfips = row['countyfips'].strip()
            if stateabbr == 'US' or countyfips in ('59', 'US'):
                continue
            if len(countyfips) != 5 or not countyfips.isdigit() or countyfips.endswith('000'):
                raise ValueError(
                    f'PLACES places2020_tract row {row_num} has invalid countyfips {countyfips!r} '
                    f'for ({stateabbr!r}, {countyname!r})'
                )
            if not stateabbr or not countyname:
                raise ValueError(f'PLACES places2020_tract row {row_num} has blank stateabbr or countyname')
            codes_by_name[(stateabbr, countyname)].add(countyfips)

    if not codes_by_name:
        raise ValueError('PLACES places2020_tract contained no county mappings')

    ambiguous = {
        name: sorted(codes)
        for name, codes in sorted(codes_by_name.items())
        if len(codes) != 1
    }
    if ambiguous:
        formatted = ', '.join(f'{st} {nm} -> {codes}' for (st, nm), codes in ambiguous.items())
        raise ValueError(f'Ambiguous 2020 PLACES county names in tract file: {formatted}')

    return {name: next(iter(codes)) for name, codes in codes_by_name.items()}


def _parse_value_and_ci(
    raw_val: str,
    raw_low: str,
    raw_high: str,
    raw_symbol: str,
    context: str,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, str]:
    val_text = raw_val.strip()
    low_text = raw_low.strip()
    high_text = raw_high.strip()
    sym_text = raw_symbol.strip()

    if val_text == '':
        if low_text != '' or high_text != '':
            raise ValueError(f'PLACES blank value has confidence limit(s) at {context}')
        status = 'suppressed' if sym_text != '' else 'missing'
        return None, None, None, status

    if low_text == '' or high_text == '':
        raise ValueError(f'PLACES present value is missing confidence limit(s) at {context}')

    val = to_decimal(val_text)
    low = to_decimal(low_text)
    high = to_decimal(high_text)
    assert val is not None and low is not None and high is not None

    for label, num in (('data_value', val), ('low_confidence_limit', low), ('high_confidence_limit', high)):
        if num < ZERO or num > HUNDRED:
            raise ValueError(f'PLACES {label} {num} outside [0, 100] at {context}')

    if not (low <= val <= high):
        raise ValueError(f'PLACES CI [{low}, {high}] does not bracket value {val} at {context}')

    status = 'true_zero' if val == ZERO else 'available'
    return val, low, high, status


def _is_droppable_non_target_location(level: str, stateabbr: str, locationname: str, locationid: str) -> str | None:
    if stateabbr == 'US' or locationid in ('59', 'US') or locationname == 'United States':
        return 'national_us'
    if level == 'county' and len(locationid) == 2 and locationid.isdigit():
        return 'state_summary'
    return None


def parse(config: dict, files: dict[str, Path], evidence: dict) -> Iterator[tuple[str, list[HistoryRow]]]:
    """Stream archived CDC PLACES CSV files into per-(release, level) HistoryRow parts."""
    (
        expected_dtype,
        releases,
        expected_headers,
        declared_by_locator,
        winning_release_by_measure_year,
    ) = _validate_config(config)

    missing_roles = sorted(set(expected_headers) - set(files))
    if missing_roles:
        raise ValueError(f'Missing required PLACES source file roles: {missing_roles}')

    county_map_2020: dict[tuple[str, str], str] = {}
    if '2020' in releases:
        county_map_2020 = _build_2020_county_map(
            Path(files['places2020_tract']),
            expected_headers['places2020_tract'],
        )

    header_hashes: dict[str, str] = {}
    source_row_counts: dict[str, int] = {}
    skipped_duplicate_data_years: dict[str, dict[str, int]] = defaultdict(dict)
    skipped_undeclared_measure_years: dict[str, dict[str, int]] = defaultdict(dict)
    dropped_non_target_locations: dict[str, dict[str, int]] = defaultdict(dict)
    status_counts: dict[str, dict[str, int]] = {}
    emitted_rows: dict[str, int] = {}
    mapped_2020_county_rows = 0
    mapped_2020_unique_counties: set[str] = set()

    # Pre-validate headers on all required files before yielding parts
    for role, exp_hdr in sorted(expected_headers.items()):
        path = Path(files[role])
        with path.open(newline='', encoding='utf-8-sig') as source:
            reader = csv.reader(source)
            hdr = next(reader, None)
            if hdr != exp_hdr:
                raise ValueError(f'PLACES {role} CSV header {hdr!r} does not match expected {exp_hdr!r}')
            header_hashes[role] = _header_sha(hdr)

    evidence.clear()
    evidence.update({
        'header_sha256': header_hashes,
        'county_2020_tract_map_count': len(county_map_2020),
        'county_2020_mapped_rows': 0,
        'county_2020_mapped_unique_counties': 0,
        'source_row_counts': source_row_counts,
        'skipped_duplicate_data_years': skipped_duplicate_data_years,
        'skipped_undeclared_measure_years': skipped_undeclared_measure_years,
        'dropped_non_target_locations': dropped_non_target_locations,
        'status_counts': status_counts,
        'emitted_rows': emitted_rows,
        'emitted_total': 0,
    })

    for release in releases:
        for level in ('county', 'tract'):
            role = f'places{release}_{level}'
            part_name = f'r{release}_{level}'
            exp_hdr = expected_headers[role]
            path = Path(files[role])

            part_rows: list[HistoryRow] = []
            part_statuses: Counter[str] = Counter()
            dup_year_counter: Counter[str] = Counter()
            undeclared_counter: Counter[str] = Counter()
            dropped_loc_counter: Counter[str] = Counter()
            seen_keys: set[tuple[str, str, str, str]] = set()
            unmapped_2020_names: set[str] = set()
            total_rows = 0

            with path.open(newline='', encoding='utf-8-sig') as source:
                reader = csv.DictReader(source)
                hdr = list(reader.fieldnames or [])
                if hdr != exp_hdr:
                    raise ValueError(f'PLACES {role} CSV header {hdr!r} does not match expected {exp_hdr!r}')

                for row in reader:
                    total_rows += 1
                    if None in row or any(v is None for v in row.values()):
                        raise ValueError(f'PLACES {role} row {total_rows} has an unexpected column count')

                    dtype = row['datavaluetypeid'].strip()
                    if dtype != expected_dtype:
                        raise ValueError(
                            f'PLACES {role} row {total_rows} has datavaluetypeid {dtype!r}; expected {expected_dtype!r}'
                        )

                    stateabbr = row['stateabbr'].strip()
                    locationname = row['locationname'].strip()
                    locationid = row.get('locationid', '').strip() if 'locationid' in row else ''
                    measureid = row['measureid'].strip()
                    year = row['year'].strip()

                    drop_reason = _is_droppable_non_target_location(level, stateabbr, locationname, locationid)
                    if drop_reason is not None:
                        dropped_loc_counter[drop_reason] += 1
                        continue

                    target = declared_by_locator.get((release, measureid, year))
                    if target is None:
                        my_key = f'{measureid}:{year}'
                        if (measureid, year) in winning_release_by_measure_year or (
                            measureid == 'DENTAL' and year == '2022'
                        ):
                            dup_year_counter[my_key] += 1
                        else:
                            undeclared_counter[my_key] += 1
                        continue

                    measure, spec = target
                    mid = measure['measure_id']
                    period = str(spec['period'])

                    if release == '2020' and level == 'county':
                        geoid = county_map_2020.get((stateabbr, locationname), '')
                        if not geoid:
                            unmapped_2020_names.add(f'{stateabbr}:{locationname}')
                            continue
                        mapped_2020_county_rows += 1
                        mapped_2020_unique_counties.add(geoid)
                    elif level == 'county':
                        if len(locationid) != 5 or not locationid.isdigit() or locationid.endswith('000'):
                            raise ValueError(
                                f'PLACES {role} row {total_rows} has invalid county locationid {locationid!r}'
                            )
                        geoid = locationid
                    else:
                        if len(locationid) != 11 or not locationid.isdigit():
                            raise ValueError(
                                f'PLACES {role} row {total_rows} has invalid tract locationid {locationid!r}'
                            )
                        if release == '2020':
                            countyfips = row['countyfips'].strip()
                            if locationid[:5] != countyfips:
                                raise ValueError(
                                    f'PLACES {role} row {total_rows} tract {locationid!r} '
                                    f'does not match countyfips {countyfips!r}'
                                )
                        geoid = locationid

                    row_key = (level, geoid, mid, period)
                    if row_key in seen_keys:
                        raise ValueError(f'Duplicate PLACES key in {role}: {row_key}')
                    seen_keys.add(row_key)

                    raw_dv = row['data_value']
                    val, low, high, status = _parse_value_and_ci(
                        raw_dv,
                        row['low_confidence_limit'],
                        row['high_confidence_limit'],
                        row['data_value_footnote_symbol'],
                        f'{role} row {total_rows} ({geoid} {measureid} {year})',
                    )

                    history_row = make_row(
                        config,
                        mid,
                        period,
                        level,
                        geoid,
                        value=val,
                        status=status,
                        source_value=raw_dv,
                        low=low,
                        high=high,
                    )
                    problems = row_problems(history_row, config)
                    if problems:
                        raise ValueError(f'PLACES row {history_row.key} failed row contract: {problems}')

                    part_rows.append(history_row)
                    part_statuses[status] += 1

            if unmapped_2020_names:
                raise ValueError(
                    f'Unmapped 2020 PLACES county names: {sorted(unmapped_2020_names)}'
                )
            if not part_rows:
                raise ValueError(f'PLACES {role} produced no rows for declared locators')

            ordered = sorted(part_rows, key=lambda r: r.key)
            source_row_counts[role] = total_rows
            if dup_year_counter:
                skipped_duplicate_data_years[role] = dict(sorted(dup_year_counter.items()))
            if undeclared_counter:
                skipped_undeclared_measure_years[role] = dict(sorted(undeclared_counter.items()))
            if dropped_loc_counter:
                dropped_non_target_locations[role] = dict(sorted(dropped_loc_counter.items()))
            status_counts[part_name] = dict(sorted(part_statuses.items()))
            emitted_rows[part_name] = len(ordered)
            evidence['county_2020_mapped_rows'] = mapped_2020_county_rows
            evidence['county_2020_mapped_unique_counties'] = len(mapped_2020_unique_counties)
            evidence['emitted_total'] = sum(emitted_rows.values())

            yield part_name, ordered
