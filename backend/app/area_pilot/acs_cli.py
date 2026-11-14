"""Supervised ACS candidate, review, publication, and independent rollback."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

from app.area_pilot.acs import CensusClient, load_registry, parse_observation, semantic_sha
from app.area_pilot.acs_boundary import boundary_sources, load_boundaries
from app.area_pilot.cli import report_candidate
from app.area_pilot.source import digest, same_label_revision
from app.db import DATABASE_URL

S = 'area_pilot'
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'acs5_2024_b19013'


def metadata_matches_published(current, previous):
    return (current['variables'] == previous['variables'] and
            digest(current['geography']) == digest(previous['geography']))


def file_rows(conn, run_id, release_id, files):
    if files:
        conn.execute(text(f'''INSERT INTO {S}.source_file
            (id,run_id,release_id,role,path,url,sha256,byte_count,retrieved_at)
            VALUES (:id,:run,:release,:role,:path,:url,:sha,:bytes,:at)'''),
            [{'id': uuid.uuid4(), 'run': run_id, 'release': release_id, 'role': f['role'],
              'path': f['path'], 'url': f['url'], 'sha': f['sha256'], 'bytes': f['byte_count'],
              'at': f['retrieved_at']} for f in files])


def boundary_files(config, directory):
    result = []
    for level, partition, url in boundary_sources(config):
        path = directory / url.rsplit('/', 1)[-1]
        if not path.is_file():
            continue
        result.append({'role': f'tiger2024_{level}_{partition}', 'path': str(path), 'url': url,
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'byte_count': path.stat().st_size, 'retrieved_at': datetime.now(timezone.utc)})
    return result


def fetch_stage(engine, config, directory):
    from app.area_pilot.operations import disk_guard
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    client = CensusClient(config, directory / str(run_id))
    try:
        disk_guard(directory, 2 * 1024**3)
        before, after, records, stable = client.fetch()
        disk_guard(directory, 2 * 1024**3)
    except Exception as exc:
        # The source archive and a held run survive a failed or interrupted retrieval.
        reason = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__
        with engine.begin() as conn:
            conn.execute(text(f'''INSERT INTO {S}.release
                (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
                 keyset_sha256,source_before,source_after,report)
                VALUES (:id,:dataset,:source,'held',:empty,:empty,:empty,:empty,'{{}}'::jsonb,'{{}}'::jsonb,CAST(:report AS jsonb))'''),
                {'id': candidate_id, 'dataset': config['dataset_id'], 'source': config['source_release_id'],
                 'empty': digest([]), 'report': json.dumps({'hold_reason': reason, 'files_retained': len(client.files)})})
            conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
                VALUES (:run,:id,'fetch-stage-validate','held',CAST(:detail AS jsonb))'''),
                {'run': run_id, 'id': candidate_id, 'detail': json.dumps({'error': reason})})
            conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
                VALUES (:id,'source_retrieval',false,CAST(:detail AS jsonb))'''),
                {'id': candidate_id, 'detail': json.dumps({'error': reason})})
            file_rows(conn, run_id, candidate_id, client.files)
        return candidate_id, {'status': 'held', 'hold_reason': reason}

    semantic = semantic_sha(records)
    schema_payload = before['variables']
    schema_sha = digest(schema_payload)
    metadata_sha = digest(before)
    keyset_sha = digest(sorted(records))
    boundary_archive = boundary_files(config, directory / 'boundaries')
    checks = {'source_stable': stable,
              'metadata_source_pinned': False,
              'state_coverage': {key for level, key in records if level == 'state'} == set(config['supported_state_fips']),
              'all_partitions': sum(level == 'county' for level, _ in records) > 0 and
                                sum(level == 'tract' for level, _ in records) > 0,
              'boundary_archive_complete': len(boundary_archive) == 54}
    counts = {level: sum(item_level == level for item_level, _ in records) for level in ('state', 'county', 'tract')}
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        prior_metadata = conn.execute(text(f'''SELECT r.source_before FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).scalar_one_or_none()
        checks['metadata_source_pinned'] = (
            metadata_matches_published(before, prior_metadata) if prior_metadata else
            before['raw_group_sha256'] == config['source_metadata_sha256'] and
            before['raw_geography_sha256'] == config['geography_metadata_sha256'])
        existing = conn.execute(text(f'''SELECT id,status FROM {S}.release WHERE dataset_id=:dataset
            AND semantic_sha256=:semantic AND schema_sha256=:schema
            AND keyset_sha256=:keyset AND (status IN ('ready','published') OR
                (status='held' AND report->>'hold_reason'='same_label_semantic_revision')) LIMIT 1'''),
            {'dataset': config['dataset_id'], 'semantic': semantic, 'schema': schema_sha,
             'keyset': keyset_sha}).mappings().one_or_none()
        boundary = dict(conn.execute(text(f'''SELECT level,count(*) FROM {S}.acs_boundary_2024
            GROUP BY level''')).all())
        checks['boundary_coverage'] = all(boundary.get(level, 0) >= count for level, count in counts.items())
        missing = conn.execute(text(f'''SELECT count(*) FROM (VALUES
            {','.join(f'(:l{i},:g{i})' for i in range(len(records)))}
            ) AS source(level,geoid) LEFT JOIN {S}.acs_boundary_2024 b
            ON b.level=source.level AND b.geoid=source.geoid WHERE b.geoid IS NULL'''),
            {k: v for i, (level, geoid) in enumerate(records) for k, v in ((f'l{i}', level), (f'g{i}', geoid))}).scalar_one() if len(records) < 1000 else None
        # Large source keysets use one batched lookup per level to avoid enormous SQL text.
        if missing is None:
            missing = 0
            for level in ('state', 'county', 'tract'):
                keys = [geoid for item_level, geoid in records if item_level == level]
                for start in range(0, len(keys), 1000):
                    batch = keys[start:start + 1000]
                    matched = conn.execute(text(f'''SELECT count(*) FROM {S}.acs_boundary_2024
                        WHERE level=:level AND geoid = ANY(:keys)'''),
                        {'level': level, 'keys': batch}).scalar_one()
                    missing += len(batch) - matched
        checks['exact_source_boundary_join'] = missing == 0
        checks['annotations_valid'] = True  # parse_response checked every source row.
        if existing and all(checks.values()):
            run_status = 'held' if existing['status'] == 'held' else 'duplicate'
            conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
                VALUES (:run,:id,'fetch-stage-validate',:status,
                    jsonb_build_object('same_semantic_content',true,'reused_held_candidate',:reused))'''),
                {'run': run_id, 'id': existing['id'], 'status': run_status,
                 'reused': run_status == 'held'})
            file_rows(conn, run_id, existing['id'], client.files + boundary_archive)
            return existing['id'], {'status': run_status, 'counts': counts,
                                    'reused_held_candidate':run_status=='held'}
        prior = conn.execute(text(f'''SELECT r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset':config['dataset_id']}).mappings().one_or_none()
        revision_hold = same_label_revision(prior, config['source_release_id'], semantic)
        report = {'checks': checks, 'counts': counts, 'observation_count': len(records),
                  'hold_reason': 'same_label_semantic_revision' if revision_hold else None,
                  'missing_boundary_count': missing, 'metadata_payload': before,
                  'source_consistency_limitation': 'Census API partitions are not a transactional snapshot; pre/post metadata agreement cannot detect an unannounced edit and reversion.'}
        status = 'ready' if all(checks.values()) and not revision_hold else 'held'
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
        file_rows(conn, run_id, candidate_id, client.files + boundary_archive)
        for name, passed in checks.items():
            conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
                VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
                {'id': candidate_id, 'name': name, 'passed': passed,
                 'detail': json.dumps({'value': passed, 'unmatched': missing if name == 'exact_source_boundary_join' else None})})
        items = sorted(records.items())
        for start in range(0, len(items), 500):
            stage = []
            observations = []
            for (level, geoid), row in items[start:start + 500]:
                stage.append({'release': candidate_id, 'level': level, 'geoid': geoid, 'record': json.dumps(row)})
                observations.append({'release': candidate_id, 'level': level, 'geoid': geoid,
                                     'measure': 'B19013_001E', 'period': config['observation_period'],
                                     'population': 'households', 'type': config['value_type'],
                                     **parse_observation(row)})
            conn.execute(text(f'''INSERT INTO {S}.stage_acs (release_id,level,geoid,record)
                VALUES (:release,:level,:geoid,CAST(:record AS jsonb))'''), stage)
            conn.execute(text(f'''INSERT INTO {S}.observation_acs
                (release_id,level,geoid,measure_id,observation_period,population,value_type,
                 value,moe,estimate_annotation,moe_annotation,status,moe_confidence)
                VALUES (:release,:level,:geoid,:measure,:period,:population,:type,
                        :value,:moe,:estimate_annotation,:moe_annotation,:status,:moe_confidence)'''), observations)
    return candidate_id, report | {'status': status}


def review(engine, candidate_id, config, connection=None):
    with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                           {'id': candidate_id, 'dataset': config['dataset_id']}).mappings().one()
        files = conn.execute(text(f'SELECT path,sha256 FROM {S}.source_file WHERE release_id=:id'),
                             {'id': candidate_id}).all()
        if not files or any(not Path(path).is_file() or hashlib.sha256(Path(path).read_bytes()).hexdigest() != sha
                            for path, sha in files):
            raise ValueError('Archived source checksum mismatch')
        staged = conn.execute(text(f'SELECT level,geoid,record FROM {S}.stage_acs WHERE release_id=:id'),
                              {'id': candidate_id}).mappings().all()
        records = {(item['level'], item['geoid']): item['record'] for item in staged}
        if semantic_sha(records) != row['semantic_sha256'] or digest(sorted(records)) != row['keyset_sha256']:
            raise ValueError('Staged ACS content differs from candidate checksums')
        observations = conn.execute(text(f'''SELECT level,geoid,value,moe,estimate_annotation,moe_annotation,status,moe_confidence
            FROM {S}.observation_acs WHERE release_id=:id'''), {'id': candidate_id}).mappings().all()
        if len(observations) != len(records):
            raise ValueError('ACS observation count differs from source')
        for item in observations:
            expected = parse_observation(records[(item['level'], item['geoid'])])
            for field, value in expected.items():
                if item[field] != value:
                    raise ValueError('ACS observation differs from staged source')
        boundary_only = set(conn.execute(text(f'''SELECT b.geoid FROM {S}.acs_boundary_2024 b
            WHERE b.level='tract' AND NOT EXISTS (SELECT 1 FROM {S}.stage_acs s
                WHERE s.release_id=:id AND s.level=b.level AND s.geoid=b.geoid)'''),
            {'id': candidate_id}).scalars())
        if boundary_only != set(config['boundary_only_tracts']):
            raise ValueError('Unreviewed 2024 TIGER tracts absent from ACS source')
        ct_count = conn.execute(text(f'''SELECT count(*) FROM {S}.stage_acs
            WHERE release_id=:id AND level='county' AND geoid LIKE '09%' '''),
            {'id': candidate_id}).scalar_one()
        if ct_count != 9:
            raise ValueError('Connecticut planning-region coverage changed')
        return report_candidate(conn, candidate_id) | {'archive_files_verified': len(files),
                                                      'staged_observations_verified': len(observations),
                                                      'boundary_only_tracts': sorted(boundary_only),
                                                      'connecticut_planning_regions': ct_count}


def publish(engine, candidate_id, semantic, schema, metadata, config):
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'),
                           {'id': candidate_id}).mappings().one()
        reviewed = review(engine, candidate_id, config, connection=conn)
        if reviewed['status'] != 'ready':
            raise ValueError('Candidate is not ready')
        if row['dataset_id'] != config['dataset_id'] or row['status'] != 'ready':
            raise ValueError('Candidate is not ready for ACS approval')
        if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (semantic, schema, metadata):
            raise ValueError('Candidate checksums differ from reviewed values')
        failed = conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                              {'id': candidate_id}).scalar_one()
        if failed:
            raise ValueError('Candidate has failed validation')
        conn.execute(text(f"UPDATE {S}.release SET status='published',published_at=now() WHERE id=:id"), {'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
            ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
            {'dataset': config['dataset_id'], 'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'publish','complete',jsonb_build_object('reason','checksum_bound_operator_approval'))'''), {'run': uuid.uuid4(), 'id': candidate_id})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db-url', default=os.getenv('DATABASE_URL', DATABASE_URL))
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('load-boundaries')
    sub.add_parser('fetch-stage-validate')
    review_parser = sub.add_parser('review'); review_parser.add_argument('candidate_id', type=uuid.UUID)
    approve = sub.add_parser('approve-publish'); approve.add_argument('candidate_id', type=uuid.UUID)
    for name in ('semantic_sha256', 'schema_sha256', 'metadata_sha256'):
        approve.add_argument(f'--{name.replace("_", "-")}', required=True)
    rollback = sub.add_parser('rollback'); rollback.add_argument('release_id', type=uuid.UUID)
    sub.add_parser('deactivate')
    args = parser.parse_args()
    config = load_registry()
    engine = create_engine(args.db_url, pool_pre_ping=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'ingest.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'load-boundaries':
            files = load_boundaries(engine, config, ROOT / 'boundaries')
            print(json.dumps({'boundary_files': len(files), 'status': 'loaded'}))
        elif args.action == 'fetch-stage-validate':
            candidate, report = fetch_stage(engine, config, ROOT)
            print(json.dumps({'candidate_id': str(candidate), 'report': report}, indent=2))
        elif args.action == 'review':
            print(json.dumps(review(engine, args.candidate_id, config), default=str, indent=2))
        elif args.action == 'approve-publish':
            publish(engine, args.candidate_id, args.semantic_sha256, args.schema_sha256,
                    args.metadata_sha256, config)
            print(f'Published ACS release {args.candidate_id}')
        else:
            with engine.begin() as conn:
                conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
                if args.action == 'rollback':
                    status = conn.execute(text(f'''SELECT status FROM {S}.release
                        WHERE id=:id AND dataset_id=:dataset'''),
                        {'id': args.release_id, 'dataset': config['dataset_id']}).scalar_one_or_none()
                    if status != 'published':
                        raise ValueError('ACS rollback target must be a retained published release')
                    conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id)
                        VALUES (:dataset,:id) ON CONFLICT (dataset_id)
                        DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
                        {'dataset': config['dataset_id'], 'id': args.release_id})
                else:
                    conn.execute(text(f'DELETE FROM {S}.active_release WHERE dataset_id=:dataset'),
                                 {'dataset': config['dataset_id']})
            print('ACS active pointer updated')


if __name__ == '__main__':
    main()
