"""HRSA Area Health Resources Files (AHRF) county history parser (2015, 2017-2020, 2022)."""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

from app.area_pilot.ahrf import load_registry, parse_count
from app.area_pilot.history.rows import HistoryRow, make_row, row_problems, to_decimal

SCHEMA_VERSION = '1'
SAS_FIELD_RE = re.compile(r'^\s*@(\d+)\s+(f\d+)\s+(?:\$\s*)?(\d+)\.\s*/\*(.*?)\*/\s*$')


def _header_sha(header: list[str]) -> str:
    return hashlib.sha256('|'.join(header).encode('utf-8')).hexdigest()


def _collapse_ws(text: str) -> str:
    return ' '.join(text.split())


def _validate_config(
    config: dict,
) -> tuple[
    dict[str, list[tuple[dict, dict, str]]],
    dict[str, list[tuple[dict, dict, dict]]],
]:
    if '_index' not in config:
        config['_index'] = {
            (m['measure_id'], p['period']): (m, p)
            for m in config.get('measures', [])
            for p in m.get('periods', [])
        }

    if config.get('levels') != ['county']:
        raise ValueError(f'AHRF history levels must be county only, got {config.get("levels")!r}')

    selection = config.get('selection') or {}
    for key in ('ascii_member', 'layout_member', 'fips_field'):
        if key not in selection:
            raise ValueError(f'AHRF history registry is missing selection.{key}')
    fips_field = selection['fips_field']
    if (
        not isinstance(fips_field, dict)
        or not fips_field.get('name')
        or int(fips_field.get('start', 0)) < 1
        or int(fips_field.get('width', 0)) != 5
    ):
        raise ValueError(f'AHRF history registry has invalid selection.fips_field: {fips_field!r}')

    current_registry = load_registry()
    current_measures = {m['measure_id']: m for m in current_registry['measures']}

    csv_locators: dict[str, list[tuple[dict, dict, str]]] = defaultdict(list)
    asc_locators_by_year: dict[str, list[tuple[dict, dict, dict]]] = defaultdict(list)

    for measure in config.get('measures', []):
        mid = measure.get('measure_id')
        if mid not in current_measures:
            raise ValueError(f'AHRF history measure {mid!r} is not in the current AHRF registry')
        for spec in measure.get('periods', []):
            if not spec.get('available', True):
                continue
            period = str(spec.get('period', ''))
            if not re.fullmatch(r'20[0-9]{2}', period):
                raise ValueError(f'AHRF measure {mid} has invalid period {period!r}')
            locator = spec.get('locator') or {}
            file_role = locator.get('file')
            if file_role in ('current_hp', 'current_hf'):
                col = locator.get('column')
                if not col or period != '2022':
                    raise ValueError(f'AHRF measure {mid} period {period} has invalid CSV locator {locator!r}')
                csv_locators[file_role].append((measure, spec, col))
            elif file_role == 'ahrf2122_zip':
                field = locator.get('field')
                start = locator.get('start')
                width = locator.get('width')
                label = locator.get('label')
                if (
                    not field
                    or not isinstance(start, int)
                    or start < 1
                    or not isinstance(width, int)
                    or width < 1
                    or label is None
                ):
                    raise ValueError(f'AHRF measure {mid} period {period} has invalid ASCII locator {locator!r}')
                asc_locators_by_year[period].append((measure, spec, locator))
            else:
                raise ValueError(f'AHRF measure {mid} period {period} has unknown locator file {file_role!r}')

    if not csv_locators and not asc_locators_by_year:
        raise ValueError('AHRF history registry declares no available periods')

    return dict(csv_locators), dict(asc_locators_by_year)


def _verify_sas_layout(
    sas_text: str,
    fips_field: dict,
    asc_locators_by_year: dict[str, list[tuple[dict, dict, dict]]],
) -> dict[str, dict]:
    """Parse DOC/AHRF2021-2022.sas and verify fips_field and every ASCII locator."""
    parsed_fields: dict[str, tuple[int, int, str]] = {}
    for line in sas_text.splitlines():
        m = SAS_FIELD_RE.match(line)
        if m:
            start = int(m.group(1))
            fname = m.group(2)
            width = int(m.group(3))
            comment = _collapse_ws(m.group(4))
            if fname in parsed_fields:
                raise ValueError(f'Duplicate field {fname!r} in AHRF SAS layout')
            parsed_fields[fname] = (start, width, comment)

    fips_name = fips_field['name']
    if fips_name not in parsed_fields:
        raise ValueError(f'AHRF SAS layout is missing FIPS field {fips_name!r}')
    f_start, f_width, f_comment = parsed_fields[fips_name]
    if f_start != fips_field['start'] or f_width != fips_field['width']:
        raise ValueError(
            f'AHRF SAS layout for FIPS field {fips_name} is (@{f_start}, {f_width}.), '
            f'expected (@{fips_field["start"]}, {fips_field["width"]}.)'
        )
    if 'fips' not in f_comment.lower():
        raise ValueError(f'AHRF SAS layout FIPS field {fips_name} comment unexpected: {f_comment!r}')
    if 'label' in fips_field:
        exp_fips_comment = _collapse_ws(f"{fips_field['label']} {fips_field.get('sublabel', '')}")
        if f_comment != exp_fips_comment:
            raise ValueError(
                f'AHRF SAS layout FIPS field {fips_name} comment {f_comment!r} != {exp_fips_comment!r}'
            )

    verified: dict[str, dict] = {
        fips_name: {'start': f_start, 'width': f_width, 'comment': f_comment},
    }
    for year in sorted(asc_locators_by_year):
        for measure, _spec, locator in asc_locators_by_year[year]:
            fname = locator['field']
            if fname not in parsed_fields:
                raise ValueError(
                    f'AHRF SAS layout is missing field {fname!r} for {measure["measure_id"]} ({year})'
                )
            s_start, s_width, s_comment = parsed_fields[fname]
            if s_start != locator['start'] or s_width != locator['width']:
                raise ValueError(
                    f'AHRF SAS layout for {fname} is (@{s_start}, {s_width}.), '
                    f'expected (@{locator["start"]}, {locator["width"]}.)'
                )
            exp_comment = _collapse_ws(f"{locator['label']} {locator.get('sublabel', '')}")
            if s_comment != exp_comment:
                raise ValueError(
                    f'AHRF SAS layout comment for {fname} is {s_comment!r}, expected {exp_comment!r}'
                )
            verified[fname] = {'start': s_start, 'width': s_width, 'comment': s_comment}

    return verified


def _parse_current_csvs(
    config: dict,
    files: dict[str, Path],
    csv_locators: dict[str, list[tuple[dict, dict, str]]],
) -> tuple[list[HistoryRow], dict]:
    headers_sha: dict[str, str] = {}
    source_rows: dict[str, int] = {}
    dropped_000: dict[str, int] = {}
    keysets: dict[str, set[str]] = {}
    status_counts: Counter[str] = Counter()
    part_rows: list[HistoryRow] = []

    for role in ('current_hp', 'current_hf'):
        if role not in csv_locators:
            continue
        path = Path(files[role])
        loc_list = csv_locators[role]
        required_cols = ['fips_st_cnty', *[col for _, _, col in loc_list]]

        with path.open(newline='', encoding='utf-8-sig') as source:
            reader = csv.DictReader(source)
            header = list(reader.fieldnames or [])
            if not header or len(header) != len(set(header)):
                raise ValueError(f'AHRF {role} CSV has missing or duplicate header columns')
            missing_cols = [c for c in required_cols if c not in header]
            if missing_cols:
                raise ValueError(f'AHRF {role} CSV is missing required columns: {missing_cols}')
            headers_sha[role] = _header_sha(header)

            seen_geoids: set[str] = set()
            total = 0
            dropped = 0
            for row in reader:
                total += 1
                if None in row or any(v is None for v in row.values()):
                    raise ValueError(f'AHRF {role} CSV row {total} has an unexpected column count')
                geoid = row['fips_st_cnty'].strip()
                if not re.fullmatch(r'[0-9]{5}', geoid):
                    raise ValueError(f'Invalid AHRF county FIPS in {role} row {total}: {geoid!r}')
                if geoid in seen_geoids:
                    raise ValueError(f'Duplicate AHRF county FIPS in {role}: {geoid!r}')
                seen_geoids.add(geoid)

                if geoid.endswith('000'):
                    dropped += 1
                    continue

                for measure, spec, col in loc_list:
                    raw = row[col].strip()
                    num, status, _ = parse_count(raw)
                    val = to_decimal(str(num)) if num is not None else None
                    history_row = make_row(
                        config,
                        measure['measure_id'],
                        str(spec['period']),
                        'county',
                        geoid,
                        value=val,
                        status=status,
                        source_value=raw,
                    )
                    problems = row_problems(history_row, config)
                    if problems:
                        raise ValueError(f'AHRF row {history_row.key} failed row contract: {problems}')
                    part_rows.append(history_row)
                    status_counts[status] += 1

            if not seen_geoids - {g for g in seen_geoids if g.endswith('000')}:
                raise ValueError(f'AHRF {role} CSV contained no county rows')
            source_rows[role] = total
            dropped_000[role] = dropped
            keysets[role] = {g for g in seen_geoids if not g.endswith('000')}

    if 'current_hp' in keysets and 'current_hf' in keysets and keysets['current_hp'] != keysets['current_hf']:
        raise ValueError('AHRF current_hp and current_hf county FIPS sets do not match')

    ordered = sorted(part_rows, key=lambda r: r.key)
    info = {
        'header_sha256': headers_sha,
        'source_row_counts': source_rows,
        'dropped_state_or_us_000': dropped_000,
        'kept_counties': len(next(iter(keysets.values()))) if keysets else 0,
        'status_counts': dict(sorted(status_counts.items())),
    }
    return ordered, info


def parse(config: dict, files: dict[str, Path], evidence: dict) -> Iterator[tuple[str, list[HistoryRow]]]:
    """Parse archived HRSA AHRF current CSVs and 2021-2022 ASCII/SAS ZIP into HistoryRow parts."""
    for role in ('current_hp', 'current_hf', 'ahrf2122_zip'):
        if role not in files:
            raise ValueError(f'Missing required AHRF source file role {role!r}')

    csv_locators, asc_locators_by_year = _validate_config(config)
    selection = config['selection']
    ascii_member = selection['ascii_member']
    layout_member = selection['layout_member']
    fips_field = selection['fips_field']
    fips_start = int(fips_field['start'])
    fips_width = int(fips_field['width'])

    current_rows, current_info = _parse_current_csvs(config, files, csv_locators)

    zip_path = Path(files['ahrf2122_zip'])
    rows_by_year: dict[str, list[HistoryRow]] = {yr: [] for yr in sorted(asc_locators_by_year)}
    asc_statuses_by_year: dict[str, Counter[str]] = {yr: Counter() for yr in sorted(asc_locators_by_year)}
    sas_dot_missing_by_year: Counter[str] = Counter()

    min_line_width = max(
        [fips_start - 1 + fips_width]
        + [
            int(loc['start']) - 1 + int(loc['width'])
            for loc_list in asc_locators_by_year.values()
            for _, _, loc in loc_list
        ]
    )

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        for member in (layout_member, ascii_member):
            if member not in names:
                raise ValueError(f'AHRF ZIP {zip_path.name} is missing required member {member!r}')

        sas_text = archive.read(layout_member).decode('latin-1')
        verified_layout = _verify_sas_layout(sas_text, fips_field, asc_locators_by_year)

        seen_asc_geoids: set[str] = set()
        asc_total_lines = 0
        asc_dropped_000 = 0

        with archive.open(ascii_member) as raw_asc:
            text_stream = io.TextIOWrapper(raw_asc, encoding='latin-1', newline='')
            for raw_line in text_stream:
                line = raw_line.rstrip('\r\n')
                if not line:
                    continue
                asc_total_lines += 1
                if len(line) < min_line_width:
                    raise ValueError(
                        f'AHRF ASCII line {asc_total_lines} has length {len(line)}, expected at least {min_line_width}'
                    )

                geoid = line[fips_start - 1 : fips_start - 1 + fips_width]
                if not re.fullmatch(r'[0-9]{5}', geoid):
                    raise ValueError(f'Invalid AHRF ASCII FIPS on line {asc_total_lines}: {geoid!r}')
                if geoid in seen_asc_geoids:
                    raise ValueError(f'Duplicate AHRF ASCII FIPS: {geoid!r}')
                seen_asc_geoids.add(geoid)

                if geoid.endswith('000'):
                    asc_dropped_000 += 1
                    continue

                for year, loc_list in asc_locators_by_year.items():
                    for measure, spec, locator in loc_list:
                        start = int(locator['start'])
                        width = int(locator['width'])
                        raw_slice = line[start - 1 : start - 1 + width]
                        stripped = raw_slice.strip()
                        if stripped == '.':
                            cleaned = ''
                            sas_dot_missing_by_year[year] += 1
                        else:
                            cleaned = stripped
                        num, status, _ = parse_count(cleaned)
                        val = to_decimal(str(num)) if num is not None else None
                        history_row = make_row(
                            config,
                            measure['measure_id'],
                            str(spec['period']),
                            'county',
                            geoid,
                            value=val,
                            status=status,
                            source_value=stripped,
                        )
                        problems = row_problems(history_row, config)
                        if problems:
                            raise ValueError(f'AHRF ASCII row {history_row.key} failed row contract: {problems}')
                        rows_by_year[year].append(history_row)
                        asc_statuses_by_year[year][status] += 1

    if asc_total_lines - asc_dropped_000 <= 0:
        raise ValueError('AHRF ASCII file contained no county rows')

    emitted_rows: dict[str, int] = {'current_2022': len(current_rows)}
    for year in sorted(rows_by_year):
        rows_by_year[year].sort(key=lambda r: r.key)
        emitted_rows[f'ahrf2122_{year}'] = len(rows_by_year[year])

    evidence.clear()
    evidence.update({
        'current_2022': current_info,
        'ahrf2122': {
            'verified_fields': verified_layout,
            'total_lines': asc_total_lines,
            'dropped_state_or_us_000': asc_dropped_000,
            'kept_counties': asc_total_lines - asc_dropped_000,
            'sas_dot_missing_by_year': dict(sorted(sas_dot_missing_by_year.items())),
            'status_counts': {
                yr: dict(sorted(counts.items())) for yr, counts in sorted(asc_statuses_by_year.items())
            },
        },
        'emitted_rows': emitted_rows,
        'emitted_total': sum(emitted_rows.values()),
    })

    yield 'current_2022', current_rows
    for year in sorted(rows_by_year):
        yield f'ahrf2122_{year}', rows_by_year[year]
