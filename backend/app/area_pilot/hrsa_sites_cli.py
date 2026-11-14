"""Manual HRSA health center site candidate, checksum review, publication, and pointer recovery.

Commands (from backend/):
  .venv/bin/python -m app.area_pilot.hrsa_sites_cli fetch-stage-validate
  .venv/bin/python -m app.area_pilot.hrsa_sites_cli review CANDIDATE
  .venv/bin/python -m app.area_pilot.hrsa_sites_cli approve-publish CANDIDATE --semantic-sha256 .. --schema-sha256 .. --metadata-sha256 ..
  .venv/bin/python -m app.area_pilot.hrsa_sites_cli release-reviewed-hold CANDIDATE --semantic-sha256 .. --schema-sha256 .. --metadata-sha256 .. --operator-note ..
  .venv/bin/python -m app.area_pilot.hrsa_sites_cli rollback RELEASE
  .venv/bin/python -m app.area_pilot.hrsa_sites_cli deactivate
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
from app.area_pilot.hrsa_sites import (MAPPED, apply_boundary, classification_code, file_evidence, keyset_sha,
                                       load_registry, location_digest, parse_csv, parse_metadata,
                                       provisional_locations, public_attributes, retrieve, semantic_sha,
                                       site_record_sha, summarize, validate_rows)
from app.area_pilot.source import digest, same_label_revision
from app.db import DATABASE_URL

S = 'area_pilot'
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'hrsa_hc_sites'
REQUIRED_ROLES = {'download_page', 'topic_page', 'metadata_xlsx', 'sites_csv'}
RELEASABLE_HOLDS = ('same_label_semantic_revision', 'large_change_vs_active')


def schema_payload(config, metadata_digest):
    return {'header': config['expected_header'], 'site_id_field': config['site_id_field'],
            'site_id_pattern': config['site_id_pattern'], 'snapshot_field': config['snapshot_field'],
            'classifications': config['classifications'], 'display_vocabularies': config['display_vocabularies'],
            'status_values': config['status_values'], 'eligible_statuses': config['eligible_statuses'],
            'exposed_attributes': config['exposed_attributes'], 'metadata_xlsx_digest': metadata_digest}


def metadata_payload(config, metadata_digest, final):
    return {'dataset_id': config['dataset_id'], 'source_urls': config['source_urls'],
            'location_policy': config['location_policy'], 'boundary': config['boundary'],
            'usage_terms': config['usage_terms'], 'location_sha256': location_digest(final),
            'schema': schema_payload(config, metadata_digest)}


def source_label(snapshot):
    return f'HCSD site snapshot {snapshot.isoformat()}'


def boundary_results(conn, rows, provisional, config):
    """Point-in-published-county for provisionally mapped sites whose FIPS is in the 2024 layer."""
    layer_states = set(conn.execute(text(f"SELECT geoid FROM {S}.acs_boundary_2024 WHERE level='state'")).scalars())
    payload = [{'site_id': row[config['site_id_field']],
                'fips': row['State and County Federal Information Processing Standard Code'].strip(),
                'lon': str(provisional[row[config['site_id_field']]]['lon']),
                'lat': str(provisional[row[config['site_id_field']]]['lat'])}
               for row in rows if provisional[row[config['site_id_field']]]['status'] == MAPPED]
    if not payload:
        return {}, layer_states
    result = conn.execute(text(f'''SELECT v.site_id,
            ST_Intersects(b.geom, ST_SetSRID(ST_MakePoint(CAST(v.lon AS float8), CAST(v.lat AS float8)), 4326)) AS inside
        FROM jsonb_to_recordset(CAST(:payload AS jsonb)) AS v(site_id text, fips text, lon text, lat text)
        JOIN {S}.acs_boundary_2024 b ON b.level='county' AND b.geoid=v.fips'''),
        {'payload': json.dumps(payload)}).all()
    return {site: bool(inside) for site, inside in result}, layer_states


def site_values(row, final, config, candidate_id):
    site = row[config['site_id_field']]
    item = final[site]
    suppressed = item['status'] == 'suppressed_source_policy'
    raw_x = row['Geocoding Artifact Address Primary X Coordinate'].strip() or None
    raw_y = row['Geocoding Artifact Address Primary Y Coordinate'].strip() or None
    return {'release': candidate_id, 'site': site, 'record_sha': site_record_sha(row, config),
            'hcn': row['Health Center Number'], 'org': row['Health Center Name'], 'name': row['Site Name'],
            'program': classification_code(row, config, 'program'),
            'site_type': classification_code(row, config, 'site_type'),
            'location_type': classification_code(row, config, 'location_type'),
            'setting': classification_code(row, config, 'setting'),
            'site_status': row['Site Status Description'],
            'eligible': row['Site Status Description'] in config['eligible_statuses'],
            'location_status': item['status'], 'reason': item['exclusion_reason'],
            'boundary_check': item['boundary_check'],
            'source_x': None if suppressed else raw_x, 'source_y': None if suppressed else raw_y,
            'decimals': item['decimals'] if item['status'] == MAPPED else None,
            'x': raw_x if item['status'] == MAPPED else None, 'y': raw_y if item['status'] == MAPPED else None,
            'state': row['Site State Abbreviation'].strip() or None, 'city': row['Site City'].strip() or None,
            'attributes': json.dumps(public_attributes(row, config, item['status']), ensure_ascii=False)}


def _files_on_failure(directory):
    if not directory.is_dir():
        return []
    return [file_evidence(path, 'retained-on-failure', f'partial:{path.name}')
            for path in sorted(directory.iterdir()) if path.is_file() and not path.name.endswith('.part')]


def _hold(engine, config, run_id, candidate_id, reason, files, checks=None, issues=None, label=None):
    with engine.begin() as conn:
        conn.execute(text(f'''INSERT INTO {S}.release
            (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
             keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:source,'held',:empty,:empty,:empty,:empty,'{{}}'::jsonb,'{{}}'::jsonb,CAST(:report AS jsonb))'''),
            {'id': candidate_id, 'dataset': config['dataset_id'], 'source': label or 'HCSD site snapshot unknown',
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


def compare_with_active(conn, config, rows):
    active = conn.execute(text(f'''SELECT a.release_id,r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
        JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
        {'dataset': config['dataset_id']}).mappings().one_or_none()
    if not active:
        return None, None
    previous = dict(conn.execute(text(f'SELECT site_id,record_sha256 FROM {S}.site_hrsa WHERE release_id=:id'),
                                 {'id': active['release_id']}).all())
    current = {row[config['site_id_field']]: site_record_sha(row, config) for row in rows}
    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))
    changed = sorted(k for k in set(current) & set(previous) if current[k] != previous[k])
    fraction = (len(added) + len(removed) + len(changed)) / max(1, len(previous))
    return active, {'active_release_id': str(active['release_id']), 'active_sites': len(previous),
                    'added': len(added), 'removed': len(removed), 'changed': len(changed),
                    'changed_fraction': round(fraction, 5), 'added_sample': added[:20],
                    'removed_sample': removed[:20], 'changed_sample': changed[:20]}


def fetch_stage(engine, config, directory=ROOT, fetched=None):
    """Retrieve, validate, and stage one candidate. ``fetched`` injects (rows, files, provenance, metadata) for tests."""
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    run_dir = directory / str(run_id)
    started = time.monotonic()
    try:
        rows, files, provenance, metadata = fetched or retrieve(config, run_dir)
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        return _hold(engine, config, run_id, candidate_id, reason, _files_on_failure(run_dir))

    checks, issues, snapshot = validate_rows(rows, config)
    label = source_label(snapshot) if snapshot else None
    if not checks['site_ids_valid_unique'] or not checks['single_snapshot_date']:
        # Rows cannot be keyed or labelled; keep the archive and evidence, stage nothing.
        return _hold(engine, config, run_id, candidate_id, 'blocking_validation_failed', files, checks, issues, label)

    provisional = provisional_locations(rows, config)
    semantic, keyset = semantic_sha(rows, config), keyset_sha(rows, config)
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        boundary, layer_states = boundary_results(conn, rows, provisional, config)
        final = apply_boundary(rows, provisional, boundary, layer_states, config)
        summary = summarize(rows, final, config)
        sid = config['site_id_field']
        checks |= {
            'location_accounting': summary['mapped'] + summary['not_mapped'] == len(rows) == len(final),
            'suppression_enforced': all(final[r[sid]]['lon'] is None for r in rows
                                        if r['Health Center Service Delivery Site Location Setting Description']
                                        in config['location_policy']['suppressed_settings']),
            'boundary_cross_check': summary['location_status_counts'].get('outside_published_county', 0)
                                    <= config['max_outside_published_county'],
        }
        meta = metadata_payload(config, metadata['digest'], final)
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
                 'detail': json.dumps({'same_semantic_content': True, 'confirmed_snapshot_date': snapshot.isoformat(),
                                       'provenance': provenance}, default=str)})
            file_rows(conn, run_id, existing['id'], files)
            return existing['id'], {'status': run_status, 'checks': checks, 'existing_label': existing['source_release_id'],
                                    'confirmed_snapshot_date': snapshot.isoformat(),
                                    'duration_seconds': round(time.monotonic() - started, 2)}
        active, change = compare_with_active(conn, config, rows)
        revision_hold = same_label_revision(active, label, semantic)
        large_change = bool(change and change['changed_fraction'] > config['change_hold_fraction'])
        status = 'ready' if all(checks.values()) and not revision_hold and not large_change else 'held'
        hold_reason = ('validation_failed' if not all(checks.values()) else
                       'same_label_semantic_revision' if revision_hold else
                       'large_change_vs_active' if large_change else None)
        excluded = {s: {'reason': item['exclusion_reason']} for s, item in sorted(final.items())
                    if item['status'] != MAPPED}
        report = {'checks': checks, 'hold_reason': hold_reason, 'issues': issues, 'summary': summary,
                  'snapshot_date': snapshot.isoformat(), 'retrieved_at': provenance['retrieved_at'],
                  'source_last_modified': provenance['http'].get('sites_csv', {}).get('last-modified'),
                  'topic_page': provenance['pages'], 'restricted_attributes': provenance['restricted_attributes'],
                  'change_vs_active': change, 'excluded_sites': excluded, 'metadata_payload': meta,
                  'site_count': len(rows)}
        conn.execute(text(f'''INSERT INTO {S}.release
            (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
             keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:source,:status,:semantic,:schema,:metadata,:keyset,
                    CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:report AS jsonb))'''),
            {'id': candidate_id, 'dataset': config['dataset_id'], 'source': label, 'status': status,
             'semantic': semantic, 'schema': schema, 'metadata': metadata_sha, 'keyset': keyset,
             'before': json.dumps({'snapshot_date': snapshot.isoformat(), 'http': provenance['http']}),
             'after': json.dumps({'snapshot_date': snapshot.isoformat(), 'http': provenance['http']}),
             'report': json.dumps(report, default=str)})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'fetch-stage-validate',:status,CAST(:detail AS jsonb))'''),
            {'run': run_id, 'id': candidate_id, 'status': status, 'detail': json.dumps({'archive_files': len(files)})})
        file_rows(conn, run_id, candidate_id, files)
        for name, passed in checks.items():
            conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
                VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
                {'id': candidate_id, 'name': name, 'passed': passed, 'detail': json.dumps(issues if not passed else {})})
        stages = [{'release': candidate_id, 'site': row[sid], 'line': index + 2,
                   'record': json.dumps(row, ensure_ascii=False, separators=(',', ':'))} for index, row in enumerate(rows)]
        sites = [site_values(row, final, config, candidate_id) for row in rows]
        for start in range(0, len(rows), 2000):
            conn.execute(text(f'''INSERT INTO {S}.stage_hrsa_site (release_id,site_id,line_number,record)
                VALUES (:release,:site,:line,CAST(:record AS jsonb))'''), stages[start:start + 2000])
            conn.execute(text(f'''INSERT INTO {S}.site_hrsa
                (release_id,site_id,record_sha256,health_center_number,organization_name,site_name,program_code,
                 site_type_code,location_type_code,setting_code,site_status,eligible,location_status,exclusion_reason,
                 boundary_check,source_x,source_y,coordinate_decimals,geom,state_abbr,city,attributes)
                VALUES (:release,:site,:record_sha,:hcn,:org,:name,:program,:site_type,:location_type,:setting,
                 :site_status,:eligible,:location_status,:reason,:boundary_check,:source_x,:source_y,:decimals,
                 CASE WHEN CAST(:x AS text) IS NULL THEN NULL ELSE ST_SetSRID(ST_MakePoint(CAST(:x AS float8),CAST(:y AS float8)),4326) END,
                 :state,:city,CAST(:attributes AS jsonb))'''), sites[start:start + 2000])
    return candidate_id, {k: v for k, v in report.items() if k not in ('excluded_sites', 'metadata_payload')} | {
        'status': status, 'semantic_sha256': semantic, 'schema_sha256': schema, 'metadata_sha256': metadata_sha,
        'keyset_sha256': keyset, 'source_release_id': label, 'duration_seconds': round(time.monotonic() - started, 2)}


def _expected_sites(conn, rows, config, candidate_id):
    provisional = provisional_locations(rows, config)
    boundary, layer_states = boundary_results(conn, rows, provisional, config)
    final = apply_boundary(rows, provisional, boundary, layer_states, config)
    return final, {row[config['site_id_field']]: site_values(row, final, config, candidate_id) for row in rows}


def review(engine, candidate_id, config, connection=None):
    """Re-hash archives, re-parse the archived CSV, and match every staged and read-model row."""
    with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                           {'id': candidate_id, 'dataset': config['dataset_id']}).mappings().one()
        if row['status'] not in ('ready', 'published', 'held'):
            raise ValueError('Invalid HRSA site candidate status')
        files = conn.execute(text(f'''SELECT DISTINCT ON (role) role,path,sha256 FROM {S}.source_file
            WHERE release_id=:id AND role = ANY(:roles) ORDER BY role,retrieved_at'''),
            {'id': candidate_id, 'roles': sorted(REQUIRED_ROLES)}).mappings().all()
        if {item['role'] for item in files} != REQUIRED_ROLES:
            raise ValueError('HRSA site archive evidence incomplete')
        for item in files:
            if not Path(item['path']).is_file() or file_evidence(item['path'], '', '')['sha256'] != item['sha256']:
                raise ValueError(f'HRSA site archived source checksum mismatch: {item["role"]}')
        paths = {item['role']: item['path'] for item in files}
        rows = parse_csv(paths['sites_csv'], config)
        metadata = parse_metadata(paths['metadata_xlsx'], config)
        if semantic_sha(rows, config) != row['semantic_sha256'] or keyset_sha(rows, config) != row['keyset_sha256']:
            raise ValueError('HRSA archived CSV differs from the candidate checksums')
        final, expected = _expected_sites(conn, rows, config, candidate_id)
        meta = row['report']['metadata_payload']
        if (metadata_payload(config, metadata['digest'], final) != meta or digest(meta) != row['metadata_sha256']
                or digest(meta['schema']) != row['schema_sha256']):
            raise ValueError('HRSA site candidate metadata, location classification, or registry changed')
        staged = dict(conn.execute(text(f'SELECT site_id,record FROM {S}.stage_hrsa_site WHERE release_id=:id'),
                                   {'id': candidate_id}).all())
        if staged != {r[config['site_id_field']]: r for r in rows}:
            raise ValueError('HRSA staged raw records differ from the archived CSV')
        actual = conn.execute(text(f'''SELECT site_id,record_sha256,health_center_number,organization_name,site_name,
            program_code,site_type_code,location_type_code,setting_code,site_status,eligible,location_status,
            exclusion_reason,boundary_check,source_x,source_y,coordinate_decimals,state_abbr,city,attributes,
            ST_X(geom) AS lon,ST_Y(geom) AS lat,ST_SRID(geom) AS srid FROM {S}.site_hrsa WHERE release_id=:id'''),
            {'id': candidate_id}).mappings().all()
        if len(actual) != len(expected):
            raise ValueError('HRSA site read-model row count differs from the archived CSV')
        compare = ('record_sha256', 'record_sha'), ('health_center_number', 'hcn'), ('organization_name', 'org'), \
            ('site_name', 'name'), ('program_code', 'program'), ('site_type_code', 'site_type'), \
            ('location_type_code', 'location_type'), ('setting_code', 'setting'), ('site_status', 'site_status'), \
            ('eligible', 'eligible'), ('location_status', 'location_status'), ('exclusion_reason', 'reason'), \
            ('boundary_check', 'boundary_check'), ('source_x', 'source_x'), ('source_y', 'source_y'), \
            ('coordinate_decimals', 'decimals'), ('state_abbr', 'state'), ('city', 'city')
        for item in actual:
            want = expected.get(item['site_id'])
            if want is None or any(item[a] != want[b] for a, b in compare) or item['attributes'] != json.loads(want['attributes']):
                raise ValueError(f'HRSA site read model differs from archived source: {item["site_id"]}')
            if want['x'] is None:
                if item['lon'] is not None:
                    raise ValueError(f'HRSA site has geometry despite location status: {item["site_id"]}')
            elif (item['srid'] != 4326 or abs(Decimal(repr(item['lon'])) - Decimal(want['x'])) > Decimal('1e-9')
                  or abs(Decimal(repr(item['lat'])) - Decimal(want['y'])) > Decimal('1e-9')):
                raise ValueError(f'HRSA site geometry differs from published coordinates: {item["site_id"]}')
        mapped = sorted((i for i in actual if i['location_status'] == MAPPED), key=lambda i: i['site_id'])
        samples = [{'site_id': i['site_id'], 'site_name': i['site_name'], 'organization': i['organization_name'],
                    'state': i['state_abbr'], 'source_x': i['source_x'], 'source_y': i['source_y'],
                    'db_lon': i['lon'], 'db_lat': i['lat'], 'boundary_check': i['boundary_check']}
                   for i in mapped[::max(1, len(mapped) // 8)][:8]]
        return {'candidate_id': str(candidate_id), 'status': row['status'], 'source_release_id': row['source_release_id'],
                'semantic_sha256': row['semantic_sha256'], 'schema_sha256': row['schema_sha256'],
                'metadata_sha256': row['metadata_sha256'], 'keyset_sha256': row['keyset_sha256'],
                'archive_files_verified': len(files), 'staged_rows': len(staged), 'sites_verified': len(actual),
                'mapped_sites_verified': len(mapped), 'representative_sites': samples,
                'report': {k: v for k, v in row['report'].items() if k not in ('excluded_sites', 'metadata_payload')}}


def _bound_candidate(conn, config, candidate_id, statuses):
    conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
    row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'), {'id': candidate_id}).mappings().one()
    if row['dataset_id'] != config['dataset_id'] or row['status'] not in statuses:
        raise ValueError('HRSA site candidate is not ready' if statuses == ('ready',) else
                         'HRSA site candidate is not an eligible reviewed hold')
    return row


def _checksums_match(row, semantic, schema, metadata):
    return (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) == (semantic, schema, metadata)


def publish(engine, config, candidate_id, semantic, schema, metadata):
    with engine.begin() as conn:
        row = _bound_candidate(conn, config, candidate_id, ('ready',))
        if not _checksums_match(row, semantic, schema, metadata):
            raise ValueError('HRSA site candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('HRSA site candidate has failed checks')
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
        raise ValueError('HRSA site operator review note is required')
    with engine.begin() as conn:
        row = _bound_candidate(conn, config, candidate_id, ('held',))
        reason = row['report'].get('hold_reason')
        if reason not in RELEASABLE_HOLDS:
            raise ValueError('HRSA site candidate is not an eligible reviewed hold')
        if not _checksums_match(row, semantic, schema, metadata):
            raise ValueError('HRSA site held candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('HRSA site held candidate has failed checks')
        review(engine, candidate_id, config, connection=conn)
        active = conn.execute(text(f'''SELECT a.release_id,r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).mappings().one_or_none()
        compared = (row['report'].get('change_vs_active') or {}).get('active_release_id')
        if reason == 'same_label_semantic_revision' and not same_label_revision(active, row['source_release_id'], row['semantic_sha256']):
            raise ValueError('HRSA site active release changed since the held revision was staged')
        if reason == 'large_change_vs_active' and (not active or str(active['release_id']) != compared):
            raise ValueError('HRSA site active release changed since the large-change hold was staged')
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
                raise ValueError('HRSA site rollback target must be a retained published release')
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
            print(f'Published HRSA health center site release {args.candidate_id}')
        elif args.action == 'release-reviewed-hold':
            release_reviewed_hold(engine, config, args.candidate_id, args.semantic_sha256, args.schema_sha256,
                                  args.metadata_sha256, args.operator_note)
            print(f'Released reviewed HRSA site hold {args.candidate_id}')
        else:
            set_pointer(engine, config, args.action, getattr(args, 'release_id', None))
            print('HRSA health center site active pointer updated')


if __name__ == '__main__':
    main()
