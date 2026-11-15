"""Supervised BRFSS state prevalence lifecycle: candidate, review, publish, rollback, deactivate."""
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

from app.area_pilot.acs_cli import file_rows
from app.area_pilot.brfss import (BrfssClient, expected_keys, load_registry, metadata_payload, parse_observation,
                                  semantic_sha)
from app.area_pilot.cli import report_candidate
from app.area_pilot.source import digest, same_label_revision
from app.db import DATABASE_URL

S = 'area_pilot'
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'brfss_state_2023'
OBSERVATION_FIELDS = ('observation_period', 'population', 'value_type', 'value', 'ci_low', 'ci_high', 'sample_size',
                      'status', 'location_kind')


def observation_row(candidate_id, config, measure, geoid, record):
    return {'release': candidate_id, 'geoid': geoid, 'measure': measure['measure_id'],
            'observation_period': measure['observation_period'], 'population': measure['population'],
            'value_type': config['value_type'], **parse_observation(record, measure, config)}


def state_coverage(conn, config, records):
    """Compare source locations with CHIP's state boundaries, per year."""
    boundary = set(conn.execute(text(f"SELECT geoid FROM {S}.acs_boundary_2024 WHERE level='state'")).scalars())
    abbr = {}
    for locations in config['expected_locations'].values():
        abbr.update(locations)
    special = set(config['median_locations']) | set(config['source_only_locations'])
    unmatched, undocumented_gaps = set(), {}
    for measure in config['measures']:
        source = {geoid for item, geoid in records if item == measure['measure_id']}
        unmatched |= source - boundary - special
        missing = sorted(abbr.get(geoid, geoid) for geoid in boundary - source)
        if missing != sorted(measure.get('documented_unavailable_states', [])):
            undocumented_gaps[measure['measure_id']] = missing
    return sorted(unmatched), undocumented_gaps


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


def fetch_stage(engine, config, directory, client=None):
    from app.area_pilot.operations import disk_guard
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    client = client or BrfssClient(config, directory / str(run_id))
    try:
        disk_guard(directory, 1024**3)
        before, after, records, stable = client.fetch()
    except Exception as exc:
        reason = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__
        return _hold(engine, config, run_id, candidate_id, reason, client.files)

    by_id = {m['measure_id']: m for m in config['measures']}
    metadata = metadata_payload(config, before['columns'])
    semantic, schema_sha, metadata_sha = semantic_sha(records), digest(before['columns']), digest(metadata)
    keyset_sha = digest(sorted(records))
    statuses = {}
    for (measure_id, geoid), record in records.items():
        status = parse_observation(record, by_id[measure_id], config)['status']
        statuses[status] = statuses.get(status, 0) + 1
    checks = {
        'source_stable': stable,
        'schema_matches_registry': schema_sha == config['expected_schema_sha256'],
        'exact_keyset': sorted(records) == expected_keys(config),
        'medians_present': all((m['measure_id'], geoid) in records for m in config['measures']
                               for geoid in config['median_locations']),
    }
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        unmatched, gaps = state_coverage(conn, config, records)
        checks['boundary_join'] = not unmatched
        checks['documented_missing_states'] = not gaps
        existing = conn.execute(text(f'''SELECT id,status FROM {S}.release WHERE dataset_id=:dataset
            AND semantic_sha256=:semantic AND schema_sha256=:schema AND metadata_sha256=:metadata AND keyset_sha256=:keyset
            AND (status IN ('ready','published') OR
                 (status='held' AND report->>'hold_reason'='same_label_semantic_revision')) LIMIT 1'''),
            {'dataset': config['dataset_id'], 'semantic': semantic, 'schema': schema_sha, 'metadata': metadata_sha,
             'keyset': keyset_sha}).mappings().one_or_none()
        if existing and all(checks.values()):
            run_status = 'held' if existing['status'] == 'held' else 'duplicate'
            conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
                VALUES (:run,:id,'fetch-stage-validate',:status,
                    jsonb_build_object('same_semantic_content',true,'reused_held_candidate',:reused))'''),
                {'run': run_id, 'id': existing['id'], 'status': run_status, 'reused': run_status == 'held'})
            file_rows(conn, run_id, existing['id'], client.files)
            return existing['id'], {'status': run_status, 'statuses': statuses}
        prior = conn.execute(text(f'''SELECT r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).mappings().one_or_none()
        revision_hold = same_label_revision(prior, config['source_release_id'], semantic)
        status = 'ready' if all(checks.values()) and not revision_hold else 'held'
        report = {'checks': checks, 'statuses': statuses, 'observation_count': len(records),
                  'measure_count': len(config['measures']),
                  'unmatched_locations': unmatched, 'undocumented_state_gaps': gaps,
                  'hold_reason': 'same_label_semantic_revision' if revision_hold else None,
                  'source_revision': before['revision'], 'metadata_payload': metadata,
                  'source_consistency_limitation': 'No transactional Socrata snapshot. Pre/post revision, schema, and row-count agreement cannot detect a value changed and restored between the checks.'}
        conn.execute(text(f'''INSERT INTO {S}.release
            (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
             keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:source,:status,:semantic,:schema,:metadata,:keyset,
                    CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:report AS jsonb))'''),
            {'id': candidate_id, 'dataset': config['dataset_id'], 'source': config['source_release_id'],
             'status': status, 'semantic': semantic, 'schema': schema_sha, 'metadata': metadata_sha,
             'keyset': keyset_sha, 'before': json.dumps(before), 'after': json.dumps(after),
             'report': json.dumps(report)})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'fetch-stage-validate',:status,CAST(:detail AS jsonb))'''),
            {'run': run_id, 'id': candidate_id, 'status': status, 'detail': json.dumps({'files': len(client.files)})})
        file_rows(conn, run_id, candidate_id, client.files)
        conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
            VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
            [{'id': candidate_id, 'name': name, 'passed': passed, 'detail': json.dumps({'value': passed})}
             for name, passed in checks.items()])
        items = sorted(records.items())
        conn.execute(text(f'''INSERT INTO {S}.stage_brfss (release_id,measure_id,geoid,record)
            VALUES (:release,:measure,:geoid,CAST(:record AS jsonb))'''),
            [{'release': candidate_id, 'measure': measure_id, 'geoid': geoid, 'record': json.dumps(record)}
             for (measure_id, geoid), record in items])
        conn.execute(text(f'''INSERT INTO {S}.observation_brfss
            (release_id,geoid,measure_id,observation_period,population,value_type,value,ci_low,ci_high,
             sample_size,status,location_kind)
            VALUES (:release,:geoid,:measure,:observation_period,:population,:value_type,:value,:ci_low,:ci_high,
                    :sample_size,:status,:location_kind)'''),
            [observation_row(candidate_id, config, by_id[measure_id], geoid, record)
             for (measure_id, geoid), record in items])
    return candidate_id, {k: v for k, v in report.items() if k != 'metadata_payload'} | {'status': status}


def review(engine, candidate_id, config, connection=None):
    """Recheck archived bytes, staged content, and every observation against the staged source rows."""
    with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                           {'id': candidate_id, 'dataset': config['dataset_id']}).mappings().one()
        files = conn.execute(text(f'SELECT path,sha256 FROM {S}.source_file WHERE release_id=:id'),
                             {'id': candidate_id}).all()
        if not files or any(not Path(path).is_file() or hashlib.sha256(Path(path).read_bytes()).hexdigest() != sha
                            for path, sha in files):
            raise ValueError('Archived source checksum mismatch')
        staged = conn.execute(text(f'SELECT measure_id,geoid,record FROM {S}.stage_brfss WHERE release_id=:id'),
                              {'id': candidate_id}).mappings().all()
        records = {(item['measure_id'], item['geoid']): item['record'] for item in staged}
        if semantic_sha(records) != row['semantic_sha256'] or digest(sorted(records)) != row['keyset_sha256']:
            raise ValueError('Staged BRFSS content differs from candidate checksums')
        if digest(row['report']['metadata_payload']) != row['metadata_sha256']:
            raise ValueError('Candidate metadata changed since staging')
        columns = None
        if row['source_before']:
            columns = row['source_before'].get('columns')
        if columns is None or digest(metadata_payload(config, columns)) != row['metadata_sha256']:
            raise ValueError('Registry selection or measure set changed since the candidate was staged')
        by_id = {m['measure_id']: m for m in config['measures']}
        expected = {}
        for (measure_id, geoid), record in records.items():
            item = observation_row(candidate_id, config, by_id[measure_id], geoid, record)
            expected[(geoid, measure_id)] = tuple(item[field] for field in OBSERVATION_FIELDS)
        observed = conn.execute(text(f'''SELECT geoid,measure_id,{",".join(OBSERVATION_FIELDS)}
            FROM {S}.observation_brfss WHERE release_id=:id'''), {'id': candidate_id}).all()
        if len(observed) != len(expected):
            raise ValueError('BRFSS observation count differs from source')
        for item in observed:
            if expected.get(tuple(item[:2])) != tuple(item[2:]):
                raise ValueError(f'BRFSS observation differs from staged source at {item[:2]}')
        return report_candidate(conn, candidate_id) | {
            'archive_files_verified': len(files), 'staged_rows_verified': len(records),
            'observations_verified': len(observed)}


def publish(engine, candidate_id, semantic, schema, metadata, config):
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'),
                           {'id': candidate_id}).mappings().one()
        if row['dataset_id'] != config['dataset_id'] or row['status'] != 'ready':
            raise ValueError('Candidate is not ready for approval')
        if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (semantic, schema, metadata):
            raise ValueError('Candidate checksums differ from reviewed values')
        review(engine, candidate_id, config, connection=conn)
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('Candidate has failed validation')
        conn.execute(text(f"UPDATE {S}.release SET status='published',published_at=now() WHERE id=:id"), {'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
            ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
            {'dataset': config['dataset_id'], 'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'publish','complete',jsonb_build_object('reason','checksum_bound_operator_approval'))'''),
            {'run': uuid.uuid4(), 'id': candidate_id})


def rollback(engine, config, release_id):
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        status = conn.execute(text(f'SELECT status FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                              {'id': release_id, 'dataset': config['dataset_id']}).scalar_one_or_none()
        if status != 'published':
            raise ValueError('Rollback target must be a retained published release of this product')
        conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
            ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
            {'dataset': config['dataset_id'], 'id': release_id})
        conn.execute(text(f"INSERT INTO {S}.run (id,release_id,action,status,detail) VALUES (:run,:id,'rollback','complete','{{}}'::jsonb)"),
                     {'run': uuid.uuid4(), 'id': release_id})


def deactivate(engine, config):
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        old = conn.execute(text(f'DELETE FROM {S}.active_release WHERE dataset_id=:dataset RETURNING release_id'),
                           {'dataset': config['dataset_id']}).scalar_one_or_none()
        conn.execute(text(f"INSERT INTO {S}.run (id,release_id,action,status,detail) VALUES (:run,:id,'deactivate','complete','{{}}'::jsonb)"),
                     {'run': uuid.uuid4(), 'id': old})
    return old


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db-url', default=os.getenv('DATABASE_URL', DATABASE_URL))
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('fetch-stage-validate')
    sub.add_parser('review').add_argument('candidate_id', type=uuid.UUID)
    approve = sub.add_parser('approve-publish'); approve.add_argument('candidate_id', type=uuid.UUID)
    for name in ('semantic_sha256', 'schema_sha256', 'metadata_sha256'):
        approve.add_argument(f'--{name.replace("_", "-")}', required=True)
    sub.add_parser('rollback').add_argument('release_id', type=uuid.UUID)
    sub.add_parser('deactivate')
    args = parser.parse_args()
    config = load_registry()
    engine = create_engine(args.db_url, pool_pre_ping=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'ingest.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'fetch-stage-validate':
            candidate, report = fetch_stage(engine, config, ROOT)
            print(json.dumps({'candidate_id': str(candidate), 'report': report}, indent=2, default=str))
        elif args.action == 'review':
            result = review(engine, args.candidate_id, config)
            result['report'] = {k: v for k, v in result['report'].items() if k != 'metadata_payload'}
            result.pop('source_before', None); result.pop('source_after', None)
            print(json.dumps(result, default=str, indent=2))
        elif args.action == 'approve-publish':
            publish(engine, args.candidate_id, args.semantic_sha256, args.schema_sha256, args.metadata_sha256, config)
            print(f'Published BRFSS release {args.candidate_id}')
        elif args.action == 'rollback':
            rollback(engine, config, args.release_id); print(f'Active release reset to {args.release_id}')
        else:
            print(f'Deactivated; prior active release was {deactivate(engine, config)}')


if __name__ == '__main__':
    main()
