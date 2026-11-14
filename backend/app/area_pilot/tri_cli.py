"""Manual EPA TRI facility candidate, checksum review, publication, and pointer recovery.

Commands (from backend/):
  .venv/bin/python -m app.area_pilot.tri_cli fetch-stage-validate
  .venv/bin/python -m app.area_pilot.tri_cli review CANDIDATE
  .venv/bin/python -m app.area_pilot.tri_cli approve-publish CANDIDATE --semantic-sha256 .. --schema-sha256 .. --metadata-sha256 ..
  .venv/bin/python -m app.area_pilot.tri_cli release-reviewed-hold CANDIDATE --semantic-sha256 .. --schema-sha256 .. --metadata-sha256 .. --operator-note ..
  .venv/bin/python -m app.area_pilot.tri_cli rollback RELEASE
  .venv/bin/python -m app.area_pilot.tri_cli deactivate
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import time
import uuid
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text

from app.area_pilot.acs_cli import file_rows
from app.area_pilot.source import digest, same_label_revision
from app.area_pilot.tri import (MAPPED, apply_boundary, build_relationships, facility_attributes, facility_locations,
                                facility_record_sha, file_evidence, iter_rows, keyset_sha, load_registry,
                                location_digest, profile_csv, retrieve, row_sha, semantic_sha, summarize, validate,
                                verify_basic_page, verify_documentation)
from app.db import DATABASE_URL

S = 'area_pilot'
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'epa_tri_facilities'
REQUIRED_ROLES = {'basic_page', 'documentation_pdf', 'basic_csv'}
RELEASABLE_HOLDS = ('same_label_semantic_revision', 'large_change_vs_active')
BLOCKING = ('reporting_year', 'report_keys_valid_unique', 'facility_and_chemical_ids_valid')
BATCH = 2000


def schema_payload(config):
    return {key: config[key] for key in ('expected_header', 'fields', 'facility_fields', 'report_level_facility_fields',
                                         'chemical_fields', 'facility_id_pattern', 'doc_ctrl_num_pattern',
                                         'chemical_id_pattern', 'vocabularies', 'industry_sectors', 'reporting_year',
                                         'documentation_phrases')}


def metadata_payload(config, final):
    return {'dataset_id': config['dataset_id'], 'source_urls': config['source_urls'],
            'reporting_year': config['reporting_year'], 'location_policy': config['location_policy'],
            'boundary': config['boundary'], 'state_fips': config['state_fips'], 'detail_link': config['detail_link'],
            'usage_terms': config['usage_terms'], 'location_sha256': location_digest(final),
            'schema': schema_payload(config)}


def source_label(config):
    return f'TRI RY{config["reporting_year"]} basic US file'


def derive_counties(conn, locations):
    """Spatially derived 2024 county for each mapped facility (kept apart from the published county name).

    A point on a shared county edge intersects both polygons; the lowest GEOID is recorded.
    """
    payload = [{'f': fid, 'x': str(item['lon']), 'y': str(item['lat'])}
               for fid, item in locations.items() if item['status'] == MAPPED]
    if not payload:
        return {}
    rows = conn.execute(text(f'''SELECT v.f, min(b.geoid) FROM jsonb_to_recordset(CAST(:payload AS jsonb)) AS v(f text, x text, y text)
        JOIN {S}.acs_boundary_2024 b ON b.level='county'
         AND b.geom && ST_SetSRID(ST_MakePoint(CAST(v.x AS float8), CAST(v.y AS float8)), 4326)
         AND ST_Intersects(b.geom, ST_SetSRID(ST_MakePoint(CAST(v.x AS float8), CAST(v.y AS float8)), 4326))
        GROUP BY v.f'''), {'payload': json.dumps(payload)}).all()
    return dict(rows)


def expected_rows(profile, final, config, candidate_id):
    """Typed read-model rows derived from the profile; used for staging and for review."""
    facilities, pairs, chemicals = build_relationships(profile)
    names = profile.chemical_names
    chem_fields = config['chemical_fields']
    reports = [{'release': candidate_id, 'doc': r[0], 'facility': r[1], 'chemical': r[2], 'name': r[3], 'form': r[4],
                'sector': r[5], 'sector_label': r[6], 'naics': r[7] or None, 'metal': r[8] or None}
               for r in profile.reports]
    chemical_rows = []
    for chem, agg in chemicals.items():
        attrs = dict(zip(chem_fields, profile.chemicals[chem]))
        chemical_rows.append({'release': candidate_id, 'chemical': chem, 'names': sorted(names[chem]),
                              'cas': attrs['cas'] or None, 'srs': attrs['srs_id'] or None,
                              'classification': attrs['classification'] or None,
                              'attributes': json.dumps({k: (v or None) for k, v in attrs.items()}, sort_keys=True),
                              'reports': agg['reports'], 'facilities': len(agg['facilities'])})
    facility_rows = []
    for fid, agg in facilities.items():
        item = final[fid]
        attrs = facility_attributes(profile, fid, config)
        mapped = item['status'] == MAPPED
        facility_rows.append({
            'release': candidate_id, 'facility': fid, 'record_sha': facility_record_sha(profile, fid, config, facilities, pairs),
            'frs': attrs['frs_id'], 'name': attrs['facility_name'] or '', 'city': attrs['city'], 'county': attrs['county'],
            'state': attrs['state'], 'sectors': sorted(agg['sectors']), 'naics': sorted(agg['naics']),
            'reports': agg['reports'], 'form_r': agg['forms']['R'], 'form_a': agg['forms']['A'],
            'chemical_count': len(agg['chemicals']), 'location_status': item['status'], 'reason': item['exclusion_reason'],
            'boundary_check': item['boundary_check'], 'derived_county': item['derived_county_geoid'],
            'lat_raw': attrs['latitude'], 'lon_raw': attrs['longitude'],
            'decimals': item['decimals'], 'x': str(item['lon']) if mapped else None, 'y': str(item['lat']) if mapped else None,
            'attributes': json.dumps(attrs, ensure_ascii=False, sort_keys=True)})
    pair_rows = [{'release': candidate_id, 'facility': fid, 'chemical': chem, 'reports': p['reports'],
                  'forms': sorted(p['forms']), 'names': sorted(p['names'])} for (fid, chem), p in pairs.items()]
    return reports, chemical_rows, facility_rows, pair_rows


def _files_on_failure(directory):
    if not directory.is_dir():
        return []
    return [file_evidence(path, 'retained-on-failure', f'partial:{path.name}')
            for path in sorted(directory.iterdir()) if path.is_file() and not path.name.endswith('.part')]


def _hold(engine, config, run_id, candidate_id, reason, files, checks=None, issues=None):
    with engine.begin() as conn:
        conn.execute(text(f'''INSERT INTO {S}.release
            (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
             keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:source,'held',:empty,:empty,:empty,:empty,'{{}}'::jsonb,'{{}}'::jsonb,CAST(:report AS jsonb))'''),
            {'id': candidate_id, 'dataset': config['dataset_id'], 'source': source_label(config),
             'empty': digest([]), 'report': json.dumps({'hold_reason': reason, 'files_retained': len(files),
                                                        'checks': checks, 'issues': issues}, default=str)})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'fetch-stage-validate','held',CAST(:detail AS jsonb))'''),
            {'run': run_id, 'id': candidate_id, 'detail': json.dumps({'error': reason})})
        for name, passed in (checks or {'source_retrieval': False}).items():
            conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
                VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
                {'id': candidate_id, 'name': name, 'passed': passed,
                 'detail': json.dumps({'error': reason} if not passed else {})})
        file_rows(conn, run_id, candidate_id, files)
    return candidate_id, {'status': 'held', 'hold_reason': reason, **({'checks': checks} if checks else {}),
                          **({'issues': issues} if issues else {})}


def compare_with_active(conn, config, facility_rows, profile):
    active = conn.execute(text(f'''SELECT a.release_id,r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
        JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
        {'dataset': config['dataset_id']}).mappings().one_or_none()
    if not active:
        return None, None
    previous = dict(conn.execute(text(f'SELECT facility_id,record_sha256 FROM {S}.tri_facility WHERE release_id=:id'),
                                 {'id': active['release_id']}).all())
    previous_docs = set(conn.execute(text(f'SELECT doc_ctrl_num FROM {S}.tri_report WHERE release_id=:id'),
                                     {'id': active['release_id']}).scalars())
    current = {row['facility']: row['record_sha'] for row in facility_rows}
    docs = set(profile.row_hashes)
    added, removed = sorted(set(current) - set(previous)), sorted(set(previous) - set(current))
    changed = sorted(k for k in set(current) & set(previous) if current[k] != previous[k])
    fraction = (len(added) + len(removed) + len(changed)) / max(1, len(previous))
    return active, {'active_release_id': str(active['release_id']), 'active_facilities': len(previous),
                    'facilities_added': len(added), 'facilities_removed': len(removed), 'facilities_changed': len(changed),
                    'changed_fraction': round(fraction, 5), 'reports_added': len(docs - previous_docs),
                    'reports_no_longer_present': len(previous_docs - docs),
                    'added_sample': added[:20], 'removed_sample': removed[:20], 'changed_sample': changed[:20],
                    'note': 'Reports no longer present may be EPA withdrawals or resubmissions under a new control number; '
                            'the basic file carries no revision or withdrawal flag.'}


def stage_raw(conn, csv_path, config, candidate_id, row_hashes):
    """Re-stream the archived CSV into raw staging; refuses a file that differs from the profiled one."""
    doc_i = config['expected_header'].index(config['fields']['doc_ctrl_num'])
    batch, seen = [], 0
    for line, values in iter_rows(csv_path, config):
        doc = values[doc_i]
        if row_hashes.get(doc) != row_sha(values):
            raise ValueError('EPA TRI archived CSV changed between profiling and staging')
        batch.append({'release': candidate_id, 'doc': doc, 'line': line,
                      'record': json.dumps(values, ensure_ascii=False, separators=(',', ':'))})
        seen += 1
        if len(batch) == BATCH:
            conn.execute(text(f'''INSERT INTO {S}.stage_tri_report (release_id,doc_ctrl_num,line_number,record)
                VALUES (:release,:doc,:line,CAST(:record AS jsonb))'''), batch)
            batch = []
    if batch:
        conn.execute(text(f'''INSERT INTO {S}.stage_tri_report (release_id,doc_ctrl_num,line_number,record)
            VALUES (:release,:doc,:line,CAST(:record AS jsonb))'''), batch)
    if seen != len(row_hashes):
        raise ValueError('EPA TRI archived CSV row count changed between profiling and staging')


def insert_read_model(conn, reports, chemical_rows, facility_rows, pair_rows):
    for start in range(0, len(reports), BATCH):
        conn.execute(text(f'''INSERT INTO {S}.tri_report (release_id,doc_ctrl_num,facility_id,chemical_id,chemical_name,
            form_type,industry_sector_code,industry_sector,primary_naics,elemental_metal_included)
            VALUES (:release,:doc,:facility,:chemical,:name,:form,:sector,:sector_label,:naics,:metal)'''),
            reports[start:start + BATCH])
    conn.execute(text(f'''INSERT INTO {S}.tri_chemical (release_id,chemical_id,names,cas_number,srs_id,classification,
        attributes,report_count,facility_count) VALUES (:release,:chemical,:names,:cas,:srs,:classification,
        CAST(:attributes AS jsonb),:reports,:facilities)'''), chemical_rows)
    for start in range(0, len(facility_rows), BATCH):
        conn.execute(text(f'''INSERT INTO {S}.tri_facility (release_id,facility_id,record_sha256,frs_id,facility_name,city,
            county_name,state_abbr,sector_codes,naics_codes,report_count,form_r_count,form_a_count,chemical_count,
            location_status,exclusion_reason,boundary_check,derived_county_geoid,source_latitude,source_longitude,
            coordinate_decimals,geom,attributes)
            VALUES (:release,:facility,:record_sha,:frs,:name,:city,:county,:state,:sectors,:naics,:reports,:form_r,:form_a,
             :chemical_count,:location_status,:reason,:boundary_check,:derived_county,:lat_raw,:lon_raw,:decimals,
             CASE WHEN CAST(:x AS text) IS NULL THEN NULL
                  ELSE ST_SetSRID(ST_MakePoint(CAST(:x AS float8),CAST(:y AS float8)),4326) END,
             CAST(:attributes AS jsonb))'''), facility_rows[start:start + BATCH])
    for start in range(0, len(pair_rows), BATCH):
        conn.execute(text(f'''INSERT INTO {S}.tri_facility_chemical (release_id,facility_id,chemical_id,report_count,
            form_types,names) VALUES (:release,:facility,:chemical,:reports,:forms,:names)'''), pair_rows[start:start + BATCH])


def fetch_stage(engine, config, directory=ROOT, fetched=None):
    """Retrieve, validate, and stage one candidate. ``fetched`` injects (profile, files, provenance) for tests."""
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    run_dir = directory / str(run_id)
    started = time.monotonic()
    try:
        profile, files, provenance = fetched or retrieve(config, run_dir)
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        return _hold(engine, config, run_id, candidate_id, reason, _files_on_failure(run_dir))

    checks, issues = validate(profile, config)
    if not all(checks[name] for name in BLOCKING):
        # Forms cannot be keyed or belong to another year; keep the archive and evidence, stage nothing.
        return _hold(engine, config, run_id, candidate_id, 'blocking_validation_failed', files, checks, issues)

    label = source_label(config)
    processed = provenance['page']['processed_as_of']
    semantic, keyset = semantic_sha(profile), keyset_sha(profile)
    locations = facility_locations(profile, config)
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        final = apply_boundary(locations, derive_counties(conn, locations), profile, config)
        reports, chemical_rows, facility_rows, pair_rows = expected_rows(profile, final, config, candidate_id)
        facilities, pairs, chemicals = build_relationships(profile)
        summary = summarize(profile, final, facilities, pairs, chemicals)
        checks |= {
            'location_accounting': summary['mapped'] + summary['not_mapped'] == len(profile.facility) == len(facility_rows),
            'report_facility_chemical_relationships': (
                sum(p['reports'] for p in pair_rows) == len(reports) == sum(f['reports'] for f in facility_rows)
                and {p['facility'] for p in pair_rows} == set(profile.facility)
                and {p['chemical'] for p in pair_rows} == set(profile.chemicals)
                and sum(f['chemical_count'] for f in facility_rows) == len(pair_rows)),
            'boundary_cross_check': summary['boundary_check_counts'].get('outside_published_state', 0)
                                    <= config['max_outside_published_state'],
        }
        meta = metadata_payload(config, final)
        schema, metadata_sha = digest(meta['schema']), digest(meta)
        existing = conn.execute(text(f'''SELECT id,status,source_release_id FROM {S}.release WHERE dataset_id=:dataset
            AND semantic_sha256=:semantic AND schema_sha256=:schema AND metadata_sha256=:metadata
            AND keyset_sha256=:keyset AND (status IN ('ready','published') OR
                 (status='held' AND report->>'hold_reason' IN ('same_label_semantic_revision','large_change_vs_active')))
            ORDER BY created_at LIMIT 1'''),
            {'dataset': config['dataset_id'], 'semantic': semantic, 'schema': schema,
             'metadata': metadata_sha, 'keyset': keyset}).mappings().one_or_none()
        if existing and all(checks.values()):
            run_status = 'held' if existing['status'] == 'held' else 'duplicate'
            conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
                VALUES (:run,:id,'fetch-stage-validate',:status,CAST(:detail AS jsonb))'''),
                {'run': run_id, 'id': existing['id'], 'status': run_status,
                 'detail': json.dumps({'same_semantic_content': True, 'confirmed_processed_as_of': processed,
                                       'provenance': {k: v for k, v in provenance.items() if k != 'csv_path'}}, default=str)})
            file_rows(conn, run_id, existing['id'], files)
            return existing['id'], {'status': run_status, 'checks': checks, 'existing_label': existing['source_release_id'],
                                    'confirmed_processed_as_of': processed,
                                    'duration_seconds': round(time.monotonic() - started, 2)}
        active, change = compare_with_active(conn, config, facility_rows, profile)
        revision_hold = same_label_revision(active, label, semantic)
        large_change = bool(change and change['changed_fraction'] > config['change_hold_fraction'])
        status = 'ready' if all(checks.values()) and not revision_hold and not large_change else 'held'
        hold_reason = ('validation_failed' if not all(checks.values()) else
                       'same_label_semantic_revision' if revision_hold else
                       'large_change_vs_active' if large_change else None)
        excluded = {fid: {'reason': item['exclusion_reason']} for fid, item in sorted(final.items()) if item['status'] != MAPPED}
        report = {'checks': checks, 'hold_reason': hold_reason, 'issues': issues, 'summary': summary,
                  'reporting_year': config['reporting_year'], 'processed_as_of': processed,
                  'retrieved_at': provenance['retrieved_at'], 'basic_page': provenance['page'],
                  'documentation': provenance['documentation'], 'change_vs_active': change,
                  'excluded_facilities': excluded, 'metadata_payload': meta, 'report_count': len(reports)}
        source_state = json.dumps({'reporting_year': config['reporting_year'], 'processed_as_of': processed,
                                   'http': provenance['http']})
        conn.execute(text(f'''INSERT INTO {S}.release
            (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
             keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:source,:status,:semantic,:schema,:metadata,:keyset,
                    CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:report AS jsonb))'''),
            {'id': candidate_id, 'dataset': config['dataset_id'], 'source': label, 'status': status,
             'semantic': semantic, 'schema': schema, 'metadata': metadata_sha, 'keyset': keyset,
             'before': source_state, 'after': source_state, 'report': json.dumps(report, default=str)})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'fetch-stage-validate',:status,CAST(:detail AS jsonb))'''),
            {'run': run_id, 'id': candidate_id, 'status': status, 'detail': json.dumps({'archive_files': len(files)})})
        file_rows(conn, run_id, candidate_id, files)
        for name, passed in checks.items():
            conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
                VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
                {'id': candidate_id, 'name': name, 'passed': passed, 'detail': json.dumps(issues if not passed else {})})
        stage_raw(conn, provenance['csv_path'], config, candidate_id, profile.row_hashes)
        insert_read_model(conn, reports, chemical_rows, facility_rows, pair_rows)
    return candidate_id, {k: v for k, v in report.items() if k not in ('excluded_facilities', 'metadata_payload')} | {
        'status': status, 'semantic_sha256': semantic, 'schema_sha256': schema, 'metadata_sha256': metadata_sha,
        'keyset_sha256': keyset, 'source_release_id': label, 'duration_seconds': round(time.monotonic() - started, 2)}


def review(engine, candidate_id, config, connection=None):
    """Re-hash archives, re-verify the page and documentation, re-parse the CSV, and match every stored row."""
    with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                           {'id': candidate_id, 'dataset': config['dataset_id']}).mappings().one()
        if row['status'] not in ('ready', 'published', 'held'):
            raise ValueError('Invalid TRI candidate status')
        files = conn.execute(text(f'''SELECT DISTINCT ON (role) role,path,sha256 FROM {S}.source_file
            WHERE release_id=:id AND role = ANY(:roles) ORDER BY role,retrieved_at'''),
            {'id': candidate_id, 'roles': sorted(REQUIRED_ROLES)}).mappings().all()
        if {item['role'] for item in files} != REQUIRED_ROLES:
            raise ValueError('TRI archive evidence incomplete')
        for item in files:
            if not Path(item['path']).is_file() or file_evidence(item['path'], '', '')['sha256'] != item['sha256']:
                raise ValueError(f'TRI archived source checksum mismatch: {item["role"]}')
        paths = {item['role']: item['path'] for item in files}
        page = verify_basic_page(Path(paths['basic_page']).read_text(encoding='utf-8', errors='replace'), config)
        verify_documentation(paths['documentation_pdf'], config)
        if page['processed_as_of'] != row['report'].get('processed_as_of'):
            raise ValueError('TRI archived page processing date differs from the candidate report')
        profile = profile_csv(paths['basic_csv'], config)
        if semantic_sha(profile) != row['semantic_sha256'] or keyset_sha(profile) != row['keyset_sha256']:
            raise ValueError('TRI archived CSV differs from the candidate checksums')
        locations = facility_locations(profile, config)
        final = apply_boundary(locations, derive_counties(conn, locations), profile, config)
        meta = row['report']['metadata_payload']
        if metadata_payload(config, final) != meta or digest(meta) != row['metadata_sha256'] or digest(meta['schema']) != row['schema_sha256']:
            raise ValueError('TRI candidate metadata, location classification, or registry changed')
        reports, chemical_rows, facility_rows, pair_rows = expected_rows(profile, final, config, candidate_id)

        # Raw staging: stream in file order and compare value-for-value.
        staged = conn.execute(text(f'''SELECT doc_ctrl_num,line_number,record
            FROM {S}.stage_tri_report WHERE release_id=:id ORDER BY line_number'''), {'id': candidate_id},
            execution_options={'stream_results': True, 'yield_per': BATCH})
        staged_count = 0
        doc_i = config['expected_header'].index(config['fields']['doc_ctrl_num'])
        source = iter_rows(paths['basic_csv'], config)
        for stored in staged:
            line, values = next(source, (None, None))
            if values is None or stored.line_number != line or stored.doc_ctrl_num != values[doc_i] or stored.record != values:
                raise ValueError(f'TRI staged raw form differs from the archived CSV: {stored.doc_ctrl_num}')
            staged_count += 1
        if next(source, None) is not None or staged_count != len(profile.reports):
            raise ValueError('TRI staged raw form count differs from the archived CSV')

        want_reports = {r['doc']: r for r in reports}
        actual = conn.execute(text(f'''SELECT doc_ctrl_num,facility_id,chemical_id,chemical_name,form_type,
            industry_sector_code,industry_sector,primary_naics,elemental_metal_included FROM {S}.tri_report
            WHERE release_id=:id'''), {'id': candidate_id}).all()
        if len(actual) != len(want_reports):
            raise ValueError('TRI report read-model count differs from the archived CSV')
        for r in actual:
            w = want_reports.get(r[0])
            if w is None or tuple(r[1:]) != (w['facility'], w['chemical'], w['name'], w['form'], w['sector'],
                                             w['sector_label'], w['naics'], w['metal']):
                raise ValueError(f'TRI report read model differs from archived source: {r[0]}')

        want_chem = {c['chemical']: c for c in chemical_rows}
        actual = conn.execute(text(f'''SELECT chemical_id,names,cas_number,srs_id,classification,attributes,report_count,
            facility_count FROM {S}.tri_chemical WHERE release_id=:id'''), {'id': candidate_id}).all()
        if len(actual) != len(want_chem):
            raise ValueError('TRI chemical read-model count differs from the archived CSV')
        for r in actual:
            w = want_chem.get(r[0])
            if w is None or (list(r[1]), r[2], r[3], r[4], r[5], r[6], r[7]) != (
                    w['names'], w['cas'], w['srs'], w['classification'], json.loads(w['attributes']), w['reports'], w['facilities']):
                raise ValueError(f'TRI chemical read model differs from archived source: {r[0]}')

        want_pairs = {(p['facility'], p['chemical']): p for p in pair_rows}
        actual = conn.execute(text(f'''SELECT facility_id,chemical_id,report_count,form_types,names
            FROM {S}.tri_facility_chemical WHERE release_id=:id'''), {'id': candidate_id}).all()
        if len(actual) != len(want_pairs):
            raise ValueError('TRI facility-chemical relationship count differs from the archived CSV')
        for r in actual:
            w = want_pairs.get((r[0], r[1]))
            if w is None or (r[2], list(r[3]), list(r[4])) != (w['reports'], w['forms'], w['names']):
                raise ValueError(f'TRI facility-chemical relationship differs from archived source: {r[0]} {r[1]}')

        want_fac = {f['facility']: f for f in facility_rows}
        actual = conn.execute(text(f'''SELECT facility_id,record_sha256,frs_id,facility_name,city,county_name,state_abbr,
            sector_codes,naics_codes,report_count,form_r_count,form_a_count,chemical_count,location_status,exclusion_reason,
            boundary_check,derived_county_geoid,source_latitude,source_longitude,coordinate_decimals,attributes,
            ST_X(geom) AS lon,ST_Y(geom) AS lat,ST_SRID(geom) AS srid FROM {S}.tri_facility WHERE release_id=:id'''),
            {'id': candidate_id}).mappings().all()
        if len(actual) != len(want_fac):
            raise ValueError('TRI facility read-model count differs from the archived CSV')
        compare = (('record_sha256', 'record_sha'), ('frs_id', 'frs'), ('facility_name', 'name'), ('city', 'city'),
                   ('county_name', 'county'), ('state_abbr', 'state'), ('report_count', 'reports'),
                   ('form_r_count', 'form_r'), ('form_a_count', 'form_a'), ('chemical_count', 'chemical_count'),
                   ('location_status', 'location_status'), ('exclusion_reason', 'reason'),
                   ('boundary_check', 'boundary_check'), ('derived_county_geoid', 'derived_county'),
                   ('source_latitude', 'lat_raw'), ('source_longitude', 'lon_raw'), ('coordinate_decimals', 'decimals'))
        for item in actual:
            w = want_fac.get(item['facility_id'])
            if (w is None or any(item[a] != w[b] for a, b in compare) or list(item['sector_codes']) != w['sectors']
                    or list(item['naics_codes']) != w['naics'] or item['attributes'] != json.loads(w['attributes'])):
                raise ValueError(f'TRI facility read model differs from archived source: {item["facility_id"]}')
            if w['x'] is None:
                if item['lon'] is not None:
                    raise ValueError(f'TRI facility has geometry despite location status: {item["facility_id"]}')
            elif (item['srid'] != 4326 or abs(Decimal(repr(item['lon'])) - Decimal(w['x'])) > Decimal('1e-9')
                  or abs(Decimal(repr(item['lat'])) - Decimal(w['y'])) > Decimal('1e-9')):
                raise ValueError(f'TRI facility geometry differs from published coordinates: {item["facility_id"]}')
        mapped = sorted((i for i in actual if i['location_status'] == MAPPED), key=lambda i: i['facility_id'])
        samples = [{'facility_id': i['facility_id'], 'facility_name': i['facility_name'], 'state': i['state_abbr'],
                    'source_latitude': i['source_latitude'], 'source_longitude': i['source_longitude'],
                    'db_lat': i['lat'], 'db_lon': i['lon'], 'derived_county_geoid': i['derived_county_geoid'],
                    'boundary_check': i['boundary_check'], 'chemicals': i['chemical_count'], 'forms': i['report_count']}
                   for i in mapped[::max(1, len(mapped) // 8)][:8]]
        return {'candidate_id': str(candidate_id), 'status': row['status'], 'source_release_id': row['source_release_id'],
                'semantic_sha256': row['semantic_sha256'], 'schema_sha256': row['schema_sha256'],
                'metadata_sha256': row['metadata_sha256'], 'keyset_sha256': row['keyset_sha256'],
                'archive_files_verified': len(files), 'staged_forms_verified': staged_count,
                'reports_verified': len(want_reports), 'chemicals_verified': len(want_chem),
                'facility_chemical_relationships_verified': len(want_pairs), 'facilities_verified': len(want_fac),
                'mapped_facilities_verified': len(mapped), 'representative_facilities': samples,
                'report': {k: v for k, v in row['report'].items() if k not in ('excluded_facilities', 'metadata_payload')}}


def _bound_candidate(conn, config, candidate_id, statuses):
    conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
    row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'), {'id': candidate_id}).mappings().one()
    if row['dataset_id'] != config['dataset_id'] or row['status'] not in statuses:
        raise ValueError('TRI candidate is not ready' if statuses == ('ready',) else
                         'TRI candidate is not an eligible reviewed hold')
    return row


def _checksums_match(row, semantic, schema, metadata):
    return (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) == (semantic, schema, metadata)


def publish(engine, config, candidate_id, semantic, schema, metadata):
    with engine.begin() as conn:
        row = _bound_candidate(conn, config, candidate_id, ('ready',))
        if not _checksums_match(row, semantic, schema, metadata):
            raise ValueError('TRI candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('TRI candidate has failed checks')
        review(engine, candidate_id, config, connection=conn)
        conn.execute(text(f"UPDATE {S}.release SET status='published',published_at=now() WHERE id=:id"), {'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
            ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
            {'dataset': config['dataset_id'], 'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'publish','complete',jsonb_build_object('reason','checksum_bound_operator_approval'))'''),
            {'run': uuid.uuid4(), 'id': candidate_id})


def release_reviewed_hold(engine, config, candidate_id, semantic, schema, metadata, note):
    """Move a same-label revision or large-change hold back to ready after an operator review."""
    if not note.strip():
        raise ValueError('TRI operator review note is required')
    with engine.begin() as conn:
        row = _bound_candidate(conn, config, candidate_id, ('held',))
        reason = row['report'].get('hold_reason')
        if reason not in RELEASABLE_HOLDS:
            raise ValueError('TRI candidate is not an eligible reviewed hold')
        if not _checksums_match(row, semantic, schema, metadata):
            raise ValueError('TRI held candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('TRI held candidate has failed checks')
        review(engine, candidate_id, config, connection=conn)
        active = conn.execute(text(f'''SELECT a.release_id,r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).mappings().one_or_none()
        compared = (row['report'].get('change_vs_active') or {}).get('active_release_id')
        if reason == 'same_label_semantic_revision' and not same_label_revision(active, row['source_release_id'], row['semantic_sha256']):
            raise ValueError('TRI active release changed since the held revision was staged')
        if reason == 'large_change_vs_active' and (not active or str(active['release_id']) != compared):
            raise ValueError('TRI active release changed since the large-change hold was staged')
        conn.execute(text(f'''UPDATE {S}.release SET status='ready',
            report=jsonb_set(report,'{{hold_reason}}','null'::jsonb) WHERE id=:id'''), {'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'release-reviewed-hold','complete',CAST(:detail AS jsonb))'''),
            {'run': uuid.uuid4(), 'id': candidate_id, 'detail': json.dumps({'reason': reason, 'operator_note': note})})


def set_pointer(engine, config, action, release_id=None):
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        if action == 'rollback':
            status = conn.execute(text(f'SELECT status FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                                  {'id': release_id, 'dataset': config['dataset_id']}).scalar_one_or_none()
            if status != 'published':
                raise ValueError('TRI rollback target must be a retained published TRI release')
            conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
                ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
                {'dataset': config['dataset_id'], 'id': release_id})
        else:
            conn.execute(text(f'DELETE FROM {S}.active_release WHERE dataset_id=:dataset'), {'dataset': config['dataset_id']})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db-url', default=os.getenv('DATABASE_URL', DATABASE_URL))
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('fetch-stage-validate')
    review_cmd = sub.add_parser('review'); review_cmd.add_argument('candidate_id', type=uuid.UUID)
    for name in ('approve-publish', 'release-reviewed-hold'):
        cmd = sub.add_parser(name); cmd.add_argument('candidate_id', type=uuid.UUID)
        for field in ('semantic_sha256', 'schema_sha256', 'metadata_sha256'):
            cmd.add_argument('--' + field.replace('_', '-'), required=True)
        if name == 'release-reviewed-hold':
            cmd.add_argument('--operator-note', required=True)
    rollback = sub.add_parser('rollback'); rollback.add_argument('release_id', type=uuid.UUID)
    sub.add_parser('deactivate')
    args = parser.parse_args()
    config = load_registry()
    engine = create_engine(args.db_url, pool_pre_ping=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'ingest.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'fetch-stage-validate':
            candidate, report = fetch_stage(engine, config)
            print(json.dumps({'candidate_id': str(candidate), 'report': report}, indent=2, default=str))
        elif args.action == 'review':
            print(json.dumps(review(engine, args.candidate_id, config), indent=2, default=str))
        elif args.action == 'approve-publish':
            publish(engine, config, args.candidate_id, args.semantic_sha256, args.schema_sha256, args.metadata_sha256)
            print(f'Published EPA TRI facility release {args.candidate_id}')
        elif args.action == 'release-reviewed-hold':
            release_reviewed_hold(engine, config, args.candidate_id, args.semantic_sha256, args.schema_sha256,
                                  args.metadata_sha256, args.operator_note)
            print(f'Released reviewed EPA TRI hold {args.candidate_id}')
        else:
            set_pointer(engine, config, args.action, getattr(args, 'release_id', None))
            print('EPA TRI facility active pointer updated')


if __name__ == '__main__':
    main()
