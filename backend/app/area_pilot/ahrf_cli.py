"""Manual AHRF candidate, checksum review, publication, and pointer rollback."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import uuid
from contextlib import nullcontext
from pathlib import Path

from sqlalchemy import create_engine, text

from app.area_pilot.ahrf import (ZIP_FILES, file_evidence, load_registry, parse_count,
                                  retrieve, semantic_sha)
from app.area_pilot.acs_cli import file_rows
from app.area_pilot.source import digest, same_label_revision
from app.db import DATABASE_URL

S = 'area_pilot'
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'ahrf_2024_2025'


def source_files_on_failure(directory, config):
    result = []
    catalog = directory / 'hrsa_ahrf_download_catalog.html'
    if catalog.is_file():
        result.append(file_evidence(catalog, 'https://data.hrsa.gov/data/download?data=AHRF', 'release_catalog'))
    for role, key in [('county_csv_zip', 'source_data_url'), ('technical_documentation_zip', 'source_documentation_url')]:
        url = config[key]
        path = directory / url.rsplit('/', 1)[-1]
        if path.is_file():
            result.append(file_evidence(path, url, role))
    return result


def fetch_stage(engine, config, directory=ROOT):
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    run_dir = directory / str(run_id)
    try:
        records, dictionary, headers, files = retrieve(config, run_dir)
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        files = source_files_on_failure(run_dir, config)
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

    semantic = semantic_sha(records)
    schema = digest(dictionary)
    metadata_payload = {'source_release_id': config['source_release_id'], 'dictionary': dictionary,
                        'selected_headers': headers, 'documentation_sha256': config['documentation_sha256']}
    metadata = digest(metadata_payload)
    keyset = digest(sorted(records))
    selected_keys = set(records)
    observations = []
    for geoid, row in sorted(records.items()):
        for measure in config['measures']:
            value, status, source_code = parse_count(row[measure['measure_id']])
            observations.append({'geoid': geoid, 'measure': measure, 'value': value,
                                 'status': status, 'source_code': source_code})
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        boundary_keys = set(conn.execute(text(f"SELECT geoid FROM {S}.acs_boundary_2024 WHERE level='county'")).scalars())
        source_only = selected_keys - boundary_keys
        boundary_only = boundary_keys - selected_keys
        checks = {'source_rows': len(records) == config['expected_source_rows'],
                  'selected_definitions': len(dictionary) == 5,
                  'boundary_coverage': not boundary_only,
                  'documented_source_only_geographies': source_only == set(config['source_only_geographies']),
                  'observation_keys_unique': len(observations) == len(records) * 5}
        counts = {m['measure_id']: {'available': 0, 'true_zero': 0, 'missing': 0} for m in config['measures']}
        for item in observations:
            if item['geoid'] in boundary_keys:
                counts[item['measure']['measure_id']][item['status']] += 1
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
                 'detail': json.dumps({'same_semantic_content': True})})
            file_rows(conn, run_id, existing['id'], files)
            return existing['id'], {'status': run_status, 'checks': checks, 'counts': counts}
        prior = conn.execute(text(f'''SELECT r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).mappings().one_or_none()
        revision_hold = same_label_revision(prior, config['source_release_id'], semantic)
        status = 'ready' if all(checks.values()) and not revision_hold else 'held'
        report = {'checks': checks, 'source_rows': len(records), 'mapped_counties': len(boundary_keys),
                  'observation_count': len(boundary_keys) * 5, 'source_only_geographies': sorted(source_only),
                  'boundary_only_geographies': sorted(boundary_only), 'counts': counts,
                  'hold_reason': 'same_label_semantic_revision' if revision_hold else None,
                  'metadata_payload': metadata_payload,
                  'year_rule': 'latest documented year for each selected definition; all five are 2023',
                  'boundary_rule': 'join exact 2024 TIGER county equivalent GEOID only'}
        conn.execute(text(f'''INSERT INTO {S}.release
            (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
             keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:source,:status,:semantic,:schema,:metadata,:keyset,
                    CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:report AS jsonb))'''),
            {'id': candidate_id, 'dataset': config['dataset_id'], 'source': config['source_release_id'],
             'status': status, 'semantic': semantic, 'schema': schema, 'metadata': metadata,
             'keyset': keyset, 'before': json.dumps(metadata_payload), 'after': json.dumps(metadata_payload),
             'report': json.dumps(report)})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'fetch-stage-validate',:status,CAST(:detail AS jsonb))'''),
            {'run': run_id, 'id': candidate_id, 'status': status,
             'detail': json.dumps({'archive_files': len(files)})})
        file_rows(conn, run_id, candidate_id, files)
        for name, passed in checks.items():
            conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
                VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
                {'id': candidate_id, 'name': name, 'passed': passed,
                 'detail': json.dumps({'source_only': sorted(source_only) if name == 'documented_source_only_geographies' else None})})
        stages = [{'id': candidate_id, 'geoid': geoid, 'record': json.dumps(row)}
                  for geoid, row in sorted(records.items())]
        for start in range(0, len(stages), 500):
            conn.execute(text(f'''INSERT INTO {S}.stage_ahrf (release_id,geoid,record)
                VALUES (:id,:geoid,CAST(:record AS jsonb))'''), stages[start:start+500])
        rows = [{'id': candidate_id, 'geoid': item['geoid'], 'measure': item['measure']['measure_id'],
                 'period': item['measure']['observation_period'], 'population': item['measure']['population'],
                 'type': config['value_type'], 'value': item['value'], 'status': item['status'],
                 'source_code': item['source_code']}
                for item in observations if item['geoid'] in boundary_keys]
        for start in range(0, len(rows), 500):
            conn.execute(text(f'''INSERT INTO {S}.observation_ahrf
                (release_id,geoid,measure_id,observation_period,population,value_type,value,status,source_code)
                VALUES (:id,:geoid,:measure,:period,:population,:type,:value,:status,:source_code)'''),
                rows[start:start+500])
    return candidate_id, report | {'status': status}


def review(engine, candidate_id, config, connection=None):
    with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                           {'id': candidate_id, 'dataset': config['dataset_id']}).mappings().one()
        if row['status'] not in ('ready','published','held'):
            raise ValueError('Invalid AHRF candidate status')
        files = conn.execute(text(f'SELECT path,sha256 FROM {S}.source_file WHERE release_id=:id'),
                             {'id': candidate_id}).all()
        if len(files) < 4 or any(not Path(path).is_file() or
                hashlib.sha256(Path(path).read_bytes()).hexdigest() != sha for path, sha in files):
            raise ValueError('AHRF archived source checksum mismatch')
        staged = conn.execute(text(f'SELECT geoid,record FROM {S}.stage_ahrf WHERE release_id=:id'),
                              {'id': candidate_id}).mappings().all()
        records = {item['geoid']: item['record'] for item in staged}
        if len(records) != config['expected_source_rows'] or semantic_sha(records) != row['semantic_sha256']:
            raise ValueError('AHRF staged content differs from reviewed checksum')
        if (digest(sorted(records)) != row['keyset_sha256'] or
                digest(row['report']['metadata_payload']) != row['metadata_sha256'] or
                digest(row['report']['metadata_payload']['dictionary']) != row['schema_sha256']):
            raise ValueError('AHRF candidate metadata or geography changed')
        observations = conn.execute(text(f'''SELECT geoid,measure_id,value,status,source_code FROM {S}.observation_ahrf
            WHERE release_id=:id'''), {'id': candidate_id}).mappings().all()
        if len(observations) != row['report']['observation_count']:
            raise ValueError('AHRF observation count differs')
        for item in observations:
            value, status, code = parse_count(records[item['geoid']][item['measure_id']])
            if (item['value'], item['status'], item['source_code']) != (value,status,code):
                raise ValueError('AHRF observation differs from archived source')
        return {'candidate_id': str(candidate_id), 'status': row['status'], 'report': row['report'],
                'semantic_sha256': row['semantic_sha256'], 'schema_sha256': row['schema_sha256'],
                'metadata_sha256': row['metadata_sha256'], 'keyset_sha256': row['keyset_sha256'],
                'archive_files_verified': len(files), 'observations_verified': len(observations)}


def publish(engine, config, candidate_id, semantic, schema, metadata):
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'),
                           {'id': candidate_id}).mappings().one()
        if row['dataset_id'] != config['dataset_id'] or row['status'] != 'ready':
            raise ValueError('AHRF candidate is not ready')
        if (row['semantic_sha256'],row['schema_sha256'],row['metadata_sha256']) != (semantic,schema,metadata):
            raise ValueError('AHRF candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('AHRF candidate has failed checks')
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
        raise ValueError('AHRF operator review note is required')
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'),
                           {'id': candidate_id}).mappings().one()
        if (row['dataset_id'] != config['dataset_id'] or row['status'] != 'held' or
                row['report'].get('hold_reason') != 'same_label_semantic_revision'):
            raise ValueError('AHRF candidate is not an eligible same-label revision hold')
        if (row['semantic_sha256'],row['schema_sha256'],row['metadata_sha256']) != (semantic,schema,metadata):
            raise ValueError('AHRF held candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id':candidate_id}).scalar_one():
            raise ValueError('AHRF held candidate has failed checks')
        review(engine,candidate_id,config,connection=conn)
        active = conn.execute(text(f'''SELECT r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset':config['dataset_id']}).mappings().one_or_none()
        if not same_label_revision(active,row['source_release_id'],row['semantic_sha256']):
            raise ValueError('AHRF active release changed since the held revision was staged')
        conn.execute(text(f'''UPDATE {S}.release SET status='ready',
            report=jsonb_set(report,'{{hold_reason}}','null'::jsonb) WHERE id=:id'''),
            {'id':candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'release-reviewed-hold','complete',CAST(:detail AS jsonb))'''),
            {'run':uuid.uuid4(),'id':candidate_id,
             'detail':json.dumps({'reason':'same_label_semantic_revision','operator_note':note})})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db-url', default=os.getenv('DATABASE_URL',DATABASE_URL))
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('fetch-stage-validate')
    review_parser = sub.add_parser('review'); review_parser.add_argument('candidate_id', type=uuid.UUID)
    approve = sub.add_parser('approve-publish'); approve.add_argument('candidate_id', type=uuid.UUID)
    for field in ('semantic_sha256','schema_sha256','metadata_sha256'):
        approve.add_argument('--'+field.replace('_','-'), required=True)
    held = sub.add_parser('release-reviewed-hold'); held.add_argument('candidate_id',type=uuid.UUID)
    for field in ('semantic_sha256','schema_sha256','metadata_sha256'):
        held.add_argument('--'+field.replace('_','-'), required=True)
    held.add_argument('--operator-note',required=True)
    rollback = sub.add_parser('rollback'); rollback.add_argument('release_id',type=uuid.UUID)
    sub.add_parser('deactivate')
    args = parser.parse_args()
    config = load_registry()
    engine = create_engine(args.db_url,pool_pre_ping=True)
    ROOT.mkdir(parents=True,exist_ok=True)
    with (ROOT/'ingest.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.action == 'fetch-stage-validate':
            candidate, report = fetch_stage(engine,config)
            print(json.dumps({'candidate_id':str(candidate),'report':report},indent=2))
        elif args.action == 'review':
            print(json.dumps(review(engine,args.candidate_id,config),indent=2,default=str))
        elif args.action == 'approve-publish':
            publish(engine,config,args.candidate_id,args.semantic_sha256,args.schema_sha256,args.metadata_sha256)
            print(f'Published AHRF release {args.candidate_id}')
        elif args.action == 'release-reviewed-hold':
            release_reviewed_hold(engine,config,args.candidate_id,args.semantic_sha256,args.schema_sha256,
                                  args.metadata_sha256,args.operator_note)
            print(f'Released reviewed AHRF hold {args.candidate_id}')
        else:
            with engine.begin() as conn:
                conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'),{'dataset':config['dataset_id']})
                if args.action == 'rollback':
                    status = conn.execute(text(f'''SELECT status FROM {S}.release WHERE id=:id AND dataset_id=:dataset'''),
                                          {'id':args.release_id,'dataset':config['dataset_id']}).scalar_one_or_none()
                    if status != 'published':
                        raise ValueError('AHRF rollback target must be a retained published release')
                    conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
                        ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
                        {'dataset':config['dataset_id'],'id':args.release_id})
                else:
                    conn.execute(text(f'DELETE FROM {S}.active_release WHERE dataset_id=:dataset'),
                                 {'dataset':config['dataset_id']})
            print('AHRF active pointer updated')


if __name__ == '__main__':
    main()
