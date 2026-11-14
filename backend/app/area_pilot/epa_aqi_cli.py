"""Manual EPA AQI candidate, checksum review, publication, and independent pointer recovery."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import time
import uuid
from contextlib import nullcontext
from pathlib import Path

from sqlalchemy import create_engine, text

from app.area_pilot.acs_cli import file_rows
from app.area_pilot.epa_aqi import (classify, days_in_year, file_evidence, load_lookup, load_registry,
                                    map_counties, observation_values, retrieve, semantic_sha)
from app.area_pilot.source import digest, same_label_revision
from app.db import DATABASE_URL

S = 'area_pilot'
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'epa_aqi_county_2025'
ADVISORY_NOTE = ('EPA PM2.5 data advisory (posted 2024-08-26): original Teledyne T640/T640X PM2.5 data '
                 '(method codes 236/238) are retained in AQS alongside corrected codes 736/738. The county '
                 'AQI file has no method field, so users cannot exclude them here. Values are shown as published.')


def schema_payload(config):
    return {'header': config['expected_header'],
            'measures': [{k: m[k] for k in ('measure_id', 'source_field', 'unit', 'kind', 'official_definition')}
                         for m in config['measures']],
            'documentation_phrases': config['documentation_phrases']}


def metadata_payload(config, classified):
    mapping = [[s, c, item['epa_code'], item['geoid'], item['method'], item['boundary_status'],
                item['exclusion_reason']] for (s, c), item in sorted(classified.items())]
    return {'source_release_id': config['source_release_id'], 'observation_year': config['observation_year'],
            'source_urls': config['source_urls'], 'boundary': config['boundary'],
            'identifier_rule': config['identifier_rule'], 'mapping_sha256': digest(mapping),
            'schema': schema_payload(config)}


def keyset_sha(classified):
    return digest([[s, c, item['geoid']] for (s, c), item in sorted(classified.items())])


def _files_on_failure(directory):
    if not directory.is_dir():
        return []
    return [file_evidence(path, 'retained-on-failure', f'partial:{path.name}')
            for path in sorted(directory.iterdir()) if path.is_file() and not path.name.endswith('.part')]


def _hold(engine, config, run_id, candidate_id, reason, files):
    with engine.begin() as conn:
        conn.execute(text(f'''INSERT INTO {S}.release
            (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
             keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:source,'held',:empty,:empty,:empty,:empty,'{{}}'::jsonb,'{{}}'::jsonb,CAST(:report AS jsonb))'''),
            {'id': candidate_id, 'dataset': config['dataset_id'], 'source': config['source_release_id'],
             'empty': digest([]), 'report': json.dumps({'hold_reason': reason, 'files_retained': len(files)})})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'fetch-stage-validate','held',CAST(:detail AS jsonb))'''),
            {'run': run_id, 'id': candidate_id, 'detail': json.dumps({'error': reason})})
        conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
            VALUES (:id,'source_retrieval',false,CAST(:detail AS jsonb))'''),
            {'id': candidate_id, 'detail': json.dumps({'error': reason})})
        file_rows(conn, run_id, candidate_id, files)
    return candidate_id, {'status': 'held', 'hold_reason': reason}


def summarize(config, records, classified):
    year = config['observation_year']
    counts = {m['measure_id']: {'available': 0, 'true_zero': 0} for m in config['measures']}
    beyond, partial_year = [], 0
    for key, item in classified.items():
        if item['boundary_status'] != 'matched':
            continue
        values = observation_values(records[key], config)
        for value in values:
            counts[value['measure']['measure_id']][value['status']] += 1
            if value['value_note']:
                beyond.append(item['geoid'])
        partial_year += int(records[key]['Days with AQI']) < days_in_year(year)
    return counts, sorted(beyond), partial_year


def fetch_stage(engine, config, directory=ROOT, today=None, boundary_geoids=None, lookup=None):
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    run_dir = directory / str(run_id)
    started = time.monotonic()
    try:
        records, site_codes, files, provenance = retrieve(config, run_dir, today)
        counties, states, lookup_files = lookup or load_lookup(config)
        files = files + lookup_files
        mapping, unused_variants = map_counties(records, site_codes, counties, states, config)
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        return _hold(engine, config, run_id, candidate_id, reason, _files_on_failure(run_dir))

    semantic = semantic_sha(records)
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        boundaries = boundary_geoids if boundary_geoids is not None else set(conn.execute(text(
            f"SELECT geoid FROM {S}.acs_boundary_2024 WHERE level='county'")).scalars())
        classified, issues = classify(records, mapping, boundaries, config)
        meta = metadata_payload(config, classified)
        schema, metadata, keyset = digest(meta['schema']), digest(meta), keyset_sha(classified)
        matched = sorted(item['geoid'] for item in classified.values() if item['boundary_status'] == 'matched')
        exclusions = {f'{s}|{c}': {'epa_code': item['epa_code'], 'tiger_geoid_if_any': item['geoid'] or
                                   (item['epa_code'] if item['method'] == 'reviewed_variant' else None),
                                   'reason': item['exclusion_reason'], 'method': item['method']}
                      for (s, c), item in classified.items() if item['boundary_status'] != 'matched'}
        counts, beyond, partial_year = summarize(config, records, classified)
        checks = {
            'source_rows': len(records) == config['expected_source_rows'],
            'selected_completed_year': provenance['selection']['year'] == config['observation_year'],
            'epa_codes_unique': all(item['epa_code'] for item in classified.values()
                                    if item['exclusion_reason'] != 'non_us_jurisdiction') and not issues['duplicate_geoids'],
            'identifier_cross_check': not issues['unexplained'] and not unused_variants,
            'exclusions_match_registry': not issues['expected_exclusions_absent'] and
                len(exclusions) == len(config['expected_exclusions']),
            'row_accounting': len(matched) + len(exclusions) == len(records),
        }
        existing = conn.execute(text(f'''SELECT id,status FROM {S}.release WHERE dataset_id=:dataset
            AND semantic_sha256=:semantic AND schema_sha256=:schema AND metadata_sha256=:metadata
            AND keyset_sha256=:keyset AND (status IN ('ready','published') OR
                 (status='held' AND report->>'hold_reason'='same_label_semantic_revision'))
            ORDER BY created_at LIMIT 1'''),
            {'dataset': config['dataset_id'], 'semantic': semantic, 'schema': schema,
             'metadata': metadata, 'keyset': keyset}).mappings().one_or_none()
        if existing and all(checks.values()):
            run_status = 'held' if existing['status'] == 'held' else 'duplicate'
            conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
                VALUES (:run,:id,'fetch-stage-validate',:status,CAST(:detail AS jsonb))'''),
                {'run': run_id, 'id': existing['id'], 'status': run_status,
                 'detail': json.dumps({'same_semantic_content': True, 'provenance': provenance}, default=str)})
            file_rows(conn, run_id, existing['id'], files)
            return existing['id'], {'status': run_status, 'checks': checks,
                                    'duration_seconds': round(time.monotonic() - started, 2)}
        prior = conn.execute(text(f'''SELECT r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).mappings().one_or_none()
        revision_hold = same_label_revision(prior, config['source_release_id'], semantic)
        status = 'ready' if all(checks.values()) and not revision_hold else 'held'
        hold_reason = ('identifier_mismatch' if not checks['identifier_cross_check'] or not checks['epa_codes_unique'] else
                       'validation_failed' if not all(checks.values()) else
                       'same_label_semantic_revision' if revision_hold else None)
        report = {'checks': checks, 'hold_reason': hold_reason, 'source_rows': len(records),
                  'unique_source_counties': len(records), 'mapped_counties': len(matched),
                  'source_rows_without_compatible_boundary': len(exclusions), 'exclusions': exclusions,
                  'boundary_counties_without_observation': len(boundaries - set(matched)),
                  'boundary_counties': len(boundaries), 'observation_count': len(matched) * len(config['measures']),
                  'counts': counts, 'max_aqi_above_500': beyond, 'counties_reporting_fewer_days_than_calendar': partial_year,
                  'method_counts': {m: sum(1 for i in classified.values() if i['method'] == m)
                                    for m in sorted({i['method'] for i in classified.values()})},
                  'unexplained': [list(k) for k in issues['unexplained']], 'unused_variants': [list(k) for k in unused_variants],
                  'provenance': provenance, 'advisory': ADVISORY_NOTE, 'metadata_payload': meta,
                  'year_rule': 'latest calendar year before the retrieval year, built after May 1 of the following year',
                  'boundary_rule': 'EPA county code joined to exact TIGER/Line 2024 county GEOID; no reassignment of legacy Connecticut counties'}
        conn.execute(text(f'''INSERT INTO {S}.release
            (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
             keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:source,:status,:semantic,:schema,:metadata,:keyset,
                    CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:report AS jsonb))'''),
            {'id': candidate_id, 'dataset': config['dataset_id'], 'source': config['source_release_id'],
             'status': status, 'semantic': semantic, 'schema': schema, 'metadata': metadata, 'keyset': keyset,
             'before': json.dumps(provenance['selection']), 'after': json.dumps(provenance['selection']),
             'report': json.dumps(report, default=str)})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'fetch-stage-validate',:status,CAST(:detail AS jsonb))'''),
            {'run': run_id, 'id': candidate_id, 'status': status,
             'detail': json.dumps({'archive_files': len(files)})})
        file_rows(conn, run_id, candidate_id, files)
        for name, passed in checks.items():
            conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
                VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
                {'id': candidate_id, 'name': name, 'passed': passed,
                 'detail': json.dumps({'unexplained': report['unexplained'], 'unused_variants': report['unused_variants']}
                                      if name == 'identifier_cross_check' else {})})
        stages, observations = [], []
        for (state, county), item in sorted(classified.items()):
            stages.append({'release': candidate_id, 'state': state, 'county': county,
                           'record': json.dumps(records[(state, county)], separators=(',', ':')),
                           'code': item['epa_code'], 'geoid': item['geoid'] if item['boundary_status'] == 'matched' else None,
                           'method': item['method'], 'boundary_status': item['boundary_status'],
                           'reason': item['exclusion_reason'], 'mapping': json.dumps(item)})
            if item['boundary_status'] == 'matched':
                for value in observation_values(records[(state, county)], config):
                    measure = value['measure']
                    observations.append({'release': candidate_id, 'geoid': item['geoid'], 'measure': measure['measure_id'],
                                         'period': measure['observation_period'], 'population': measure['population'],
                                         'type': config['value_type'], 'value': value['value'], 'status': value['status'],
                                         'days': value['days_with_aqi'], 'note': value['value_note'],
                                         'state': state, 'county': county})
        conn.execute(text(f'''INSERT INTO {S}.stage_epa_aqi
            (release_id,source_state,source_county,record,epa_code,geoid,match_method,boundary_status,exclusion_reason,mapping)
            VALUES (:release,:state,:county,CAST(:record AS jsonb),:code,:geoid,:method,:boundary_status,:reason,
                    CAST(:mapping AS jsonb))'''), stages)
        for start in range(0, len(observations), 1000):
            conn.execute(text(f'''INSERT INTO {S}.observation_epa_aqi
                (release_id,geoid,measure_id,observation_period,population,value_type,value,status,
                 days_with_aqi,value_note,source_state,source_county)
                VALUES (:release,:geoid,:measure,:period,:population,:type,:value,:status,:days,:note,:state,:county)'''),
                observations[start:start + 1000])
    return candidate_id, report | {'status': status, 'semantic_sha256': semantic, 'schema_sha256': schema,
                                   'metadata_sha256': metadata, 'keyset_sha256': keyset,
                                   'duration_seconds': round(time.monotonic() - started, 2)}


def review(engine, candidate_id, config, connection=None):
    with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                           {'id': candidate_id, 'dataset': config['dataset_id']}).mappings().one()
        if row['status'] not in ('ready', 'published', 'held'):
            raise ValueError('Invalid EPA AQI candidate status')
        files = conn.execute(text(f'SELECT role,path,sha256 FROM {S}.source_file WHERE release_id=:id'),
                             {'id': candidate_id}).mappings().all()
        required = {'download_page', 'file_list', 'documentation', 'pm25_advisory', 'county_zip', 'county_csv',
                    'site_listing_zip', 'site_listing_csv', 'name_lookup_county', 'name_lookup_state'}
        if not required <= {item['role'] for item in files}:
            raise ValueError('EPA AQI archive evidence incomplete')
        for item in files:
            if not Path(item['path']).is_file() or file_evidence(item['path'], '', '')['sha256'] != item['sha256']:
                raise ValueError(f'EPA AQI archived source checksum mismatch: {item["role"]}')
        staged = conn.execute(text(f'''SELECT source_state,source_county,record,epa_code,geoid,match_method,
            boundary_status,exclusion_reason,mapping FROM {S}.stage_epa_aqi WHERE release_id=:id'''),
            {'id': candidate_id}).mappings().all()
        records = {(s['source_state'], s['source_county']): s['record'] for s in staged}
        classified = {(s['source_state'], s['source_county']): s['mapping'] for s in staged}
        if len(records) != config['expected_source_rows'] or semantic_sha(records) != row['semantic_sha256']:
            raise ValueError('EPA AQI staged content differs from reviewed checksum')
        meta = row['report']['metadata_payload']
        if (keyset_sha(classified) != row['keyset_sha256'] or digest(meta) != row['metadata_sha256'] or
                digest(meta['schema']) != row['schema_sha256'] or
                metadata_payload(config, classified) != meta):
            raise ValueError('EPA AQI candidate metadata, mapping, or registry changed')
        expected = {}
        for key, item in classified.items():
            if item['boundary_status'] == 'matched':
                for value in observation_values(records[key], config):
                    expected[(item['geoid'], value['measure']['measure_id'])] = (
                        value['value'], value['status'], value['days_with_aqi'], value['value_note'],
                        value['measure']['observation_period'], value['measure']['population'], config['value_type'],
                        key[0], key[1])
        observations = conn.execute(text(f'''SELECT geoid,measure_id,value,status,days_with_aqi,value_note,
            observation_period,population,value_type,source_state,source_county
            FROM {S}.observation_epa_aqi WHERE release_id=:id'''), {'id': candidate_id}).all()
        actual = {(o[0], o[1]): tuple(o[2:]) for o in observations}
        if len(observations) != row['report']['observation_count'] or actual != expected:
            raise ValueError('EPA AQI observation differs from archived source')
        samples = [{'geoid': g, 'measure_id': m, 'value': actual[(g, m)][0], 'days_with_aqi': actual[(g, m)][2],
                    'source': f'{actual[(g, m)][7]}|{actual[(g, m)][8]}'}
                   for g, m in sorted(actual)[::997][:8]]
        return {'candidate_id': str(candidate_id), 'status': row['status'],
                'semantic_sha256': row['semantic_sha256'], 'schema_sha256': row['schema_sha256'],
                'metadata_sha256': row['metadata_sha256'], 'keyset_sha256': row['keyset_sha256'],
                'archive_files_verified': len(files), 'staged_rows': len(staged),
                'observations_verified': len(observations), 'representative_cells': samples,
                'report': row['report']}


def _bound_candidate(conn, config, candidate_id, semantic, schema, metadata, statuses):
    conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
    row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'),
                       {'id': candidate_id}).mappings().one()
    if row['dataset_id'] != config['dataset_id'] or row['status'] not in statuses:
        raise ValueError('EPA AQI candidate is not ready' if statuses == ('ready',) else
                         'EPA AQI candidate is not an eligible same-label revision hold')
    return row


def publish(engine, config, candidate_id, semantic, schema, metadata):
    with engine.begin() as conn:
        row = _bound_candidate(conn, config, candidate_id, semantic, schema, metadata, ('ready',))
        if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (semantic, schema, metadata):
            raise ValueError('EPA AQI candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('EPA AQI candidate has failed checks')
        review(engine, candidate_id, config, connection=conn)
        conn.execute(text(f"UPDATE {S}.release SET status='published',published_at=now() WHERE id=:id"),
                     {'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
            ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
            {'dataset': config['dataset_id'], 'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'publish','complete',jsonb_build_object('reason','checksum_bound_operator_approval'))'''),
            {'run': uuid.uuid4(), 'id': candidate_id})


def release_reviewed_hold(engine, config, candidate_id, semantic, schema, metadata, note):
    if not note.strip():
        raise ValueError('EPA AQI operator review note is required')
    with engine.begin() as conn:
        row = _bound_candidate(conn, config, candidate_id, semantic, schema, metadata, ('held',))
        if row['report'].get('hold_reason') != 'same_label_semantic_revision':
            raise ValueError('EPA AQI candidate is not an eligible same-label revision hold')
        if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (semantic, schema, metadata):
            raise ValueError('EPA AQI held candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('EPA AQI held candidate has failed checks')
        review(engine, candidate_id, config, connection=conn)
        active = conn.execute(text(f'''SELECT r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).mappings().one_or_none()
        if not same_label_revision(active, row['source_release_id'], row['semantic_sha256']):
            raise ValueError('EPA AQI active release changed since the held revision was staged')
        conn.execute(text(f'''UPDATE {S}.release SET status='ready',
            report=jsonb_set(report,'{{hold_reason}}','null'::jsonb) WHERE id=:id'''), {'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'release-reviewed-hold','complete',CAST(:detail AS jsonb))'''),
            {'run': uuid.uuid4(), 'id': candidate_id,
             'detail': json.dumps({'reason': 'same_label_semantic_revision', 'operator_note': note})})


def set_pointer(engine, config, action, release_id=None):
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        if action == 'rollback':
            status = conn.execute(text(f'SELECT status FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                                  {'id': release_id, 'dataset': config['dataset_id']}).scalar_one_or_none()
            if status != 'published':
                raise ValueError('EPA AQI rollback target must be a retained published release')
            conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
                ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
                {'dataset': config['dataset_id'], 'id': release_id})
        else:
            conn.execute(text(f'DELETE FROM {S}.active_release WHERE dataset_id=:dataset'),
                         {'dataset': config['dataset_id']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
            print(f'Published EPA AQI release {args.candidate_id}')
        elif args.action == 'release-reviewed-hold':
            release_reviewed_hold(engine, config, args.candidate_id, args.semantic_sha256, args.schema_sha256,
                                  args.metadata_sha256, args.operator_note)
            print(f'Released reviewed EPA AQI hold {args.candidate_id}')
        else:
            set_pointer(engine, config, args.action, getattr(args, 'release_id', None))
            print('EPA AQI active pointer updated')


if __name__ == '__main__':
    main()
