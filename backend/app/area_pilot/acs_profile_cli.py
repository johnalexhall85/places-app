"""Supervised ACS community-characteristics lifecycle: boundaries, candidate, review, publish, rollback."""
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
from app.area_pilot.acs_profile import (LEVELS, ProfileClient, load_cd_boundaries, load_registry,
                                        parse_observation, semantic_sha)
from app.area_pilot.cli import report_candidate
from app.area_pilot.source import digest, same_label_revision
from app.db import DATABASE_URL

S = 'area_pilot'
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'acs5_2024_profile'


def metadata_matches(current, previous):
    return current['variables'] == previous['variables'] and current['geography'] == previous['geography']


def boundary_files(config, directory):
    """Provenance rows for district archives already on disk (loaded by `load-cd-boundaries`)."""
    from datetime import datetime, timezone
    from app.area_pilot.acs_profile import cd_boundary_sources
    result = []
    for state, url in cd_boundary_sources(config):
        path = directory / url.rsplit('/', 1)[-1]
        if path.is_file():
            result.append({'role': f'tiger2024_cd119_{state}', 'path': str(path), 'url': url,
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           'byte_count': path.stat().st_size, 'retrieved_at': datetime.now(timezone.utc)})
    return result


def unmatched(conn, records):
    """Source GEOIDs with no official boundary, per level."""
    missing = {}
    for level in LEVELS:
        keys = [geoid for item_level, geoid in records if item_level == level]
        table = (f"(SELECT geoid FROM {S}.cd_boundary_119) b" if level == 'cd'
                 else f"(SELECT geoid FROM {S}.acs_boundary_2024 WHERE level='{level}') b")
        found = set()
        for start in range(0, len(keys), 5000):
            found.update(conn.execute(text(f'SELECT geoid FROM {table} WHERE geoid = ANY(:keys)'),
                                      {'keys': keys[start:start + 5000]}).scalars())
        missing[level] = sorted(set(keys) - found)
    return missing


def observation_rows(candidate_id, config, level, geoid, row):
    return [{'release': candidate_id, 'level': level, 'geoid': geoid, 'measure': m['measure_id'],
             'period': m['observation_period'], 'population': m['population'], 'type': config['value_type'],
             **parse_observation(row, m)} for m in config['measures']]


def fetch_stage(engine, config, directory, client=None):
    from app.area_pilot.operations import disk_guard
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    client = client or ProfileClient(config, directory / str(run_id))
    try:
        disk_guard(directory, 2 * 1024**3)
        before, after, records, excluded, stable = client.fetch()
        disk_guard(directory, 2 * 1024**3)
    except Exception as exc:
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
    schema_sha = digest(before['variables'])
    metadata_sha = digest(before)
    keyset_sha = digest(sorted(records))
    counts = {level: sum(item_level == level for item_level, _ in records) for level in LEVELS}
    archive = boundary_files(config, directory / 'cd_boundaries')
    excluded_states = sorted(key[:2] for (_, key) in excluded)
    checks = {
        'source_stable': stable,
        'state_coverage': {key for level, key in records if level == 'state'} == set(config['supported_state_fips']),
        'all_partitions': all(counts[level] > 0 for level in LEVELS),
        'district_count': counts['cd'] == config['cd']['expected_count'],
        'documented_district_exclusions': excluded_states == sorted(config['cd']['expected_excluded_states']),
        'district_boundary_archive_complete': len(archive) == len(config['supported_state_fips']),
        'annotations_valid': True,   # parse_response validated every cell of every source row
    }
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        prior_metadata = conn.execute(text(f'''SELECT r.source_before FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).scalar_one_or_none()
        # First release: the registry pins variable labels and concepts (checked during retrieval).
        checks['metadata_source_pinned'] = metadata_matches(before, prior_metadata) if prior_metadata else (
            digest(before['variables']) == config['source_variables_sha256'])
        missing = unmatched(conn, records)
        checks['exact_source_boundary_join'] = not any(missing.values())
        boundary_only = conn.execute(text(f'''SELECT geoid FROM {S}.acs_boundary_2024 WHERE level='tract' '''
                                          )).scalars().all()
        source_tracts = {key for level, key in records if level == 'tract'}
        checks['documented_boundary_only_tracts'] = (
            sorted(set(boundary_only) - source_tracts) == sorted(config['boundary_only_tracts']))
        district_only = set(conn.execute(text(f'SELECT geoid FROM {S}.cd_boundary_119')).scalars()) - {
            key for level, key in records if level == 'cd'}
        checks['every_district_boundary_has_estimates'] = not district_only
        existing = conn.execute(text(f'''SELECT id,status FROM {S}.release WHERE dataset_id=:dataset
            AND semantic_sha256=:semantic AND schema_sha256=:schema AND keyset_sha256=:keyset
            AND (status IN ('ready','published') OR
                 (status='held' AND report->>'hold_reason'='same_label_semantic_revision')) LIMIT 1'''),
            {'dataset': config['dataset_id'], 'semantic': semantic, 'schema': schema_sha,
             'keyset': keyset_sha}).mappings().one_or_none()
        if existing and all(checks.values()):
            run_status = 'held' if existing['status'] == 'held' else 'duplicate'
            conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
                VALUES (:run,:id,'fetch-stage-validate',:status,
                    jsonb_build_object('same_semantic_content',true,'reused_held_candidate',:reused))'''),
                {'run': run_id, 'id': existing['id'], 'status': run_status, 'reused': run_status == 'held'})
            file_rows(conn, run_id, existing['id'], client.files + archive)
            return existing['id'], {'status': run_status, 'counts': counts}
        prior = conn.execute(text(f'''SELECT r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).mappings().one_or_none()
        revision_hold = same_label_revision(prior, config['source_release_id'], semantic)
        status = 'ready' if all(checks.values()) and not revision_hold else 'held'
        report = {'checks': checks, 'counts': counts, 'observation_count': len(records) * len(config['measures']),
                  'excluded_source_rows': {key: row['NAME'] for (_, key), row in sorted(excluded.items())},
                  'unmatched_boundaries': {level: keys[:50] for level, keys in missing.items() if keys},
                  'hold_reason': 'same_label_semantic_revision' if revision_hold else None,
                  'metadata_payload': before,
                  'source_consistency_limitation': 'Census API partitions are not a transactional snapshot; pre/post metadata agreement cannot detect an unannounced edit and reversion.'}
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
        file_rows(conn, run_id, candidate_id, client.files + archive)
        conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
            VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
            [{'id': candidate_id, 'name': name, 'passed': passed, 'detail': json.dumps({'value': passed})}
             for name, passed in checks.items()])
        items = sorted(records.items())
        for start in range(0, len(items), 500):
            stage, observations = [], []
            for (level, geoid), row in items[start:start + 500]:
                stage.append({'release': candidate_id, 'level': level, 'geoid': geoid, 'record': json.dumps(row)})
                observations.extend(observation_rows(candidate_id, config, level, geoid, row))
            conn.execute(text(f'''INSERT INTO {S}.stage_acs_profile (release_id,level,geoid,record)
                VALUES (:release,:level,:geoid,CAST(:record AS jsonb))'''), stage)
            conn.execute(text(f'''INSERT INTO {S}.observation_acs_profile
                (release_id,level,geoid,measure_id,observation_period,population,value_type,
                 value,moe,estimate_annotation,moe_annotation,status,moe_confidence)
                VALUES (:release,:level,:geoid,:measure,:period,:population,:type,
                        :value,:moe,:estimate_annotation,:moe_annotation,:status,:moe_confidence)'''), observations)
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
        staged = conn.execute(text(f'SELECT level,geoid,record FROM {S}.stage_acs_profile WHERE release_id=:id'),
                              {'id': candidate_id}).mappings().all()
        records = {(item['level'], item['geoid']): item['record'] for item in staged}
        if semantic_sha(records) != row['semantic_sha256'] or digest(sorted(records)) != row['keyset_sha256']:
            raise ValueError('Staged ACS content differs from candidate checksums')
        if digest(row['report']['metadata_payload']) != row['metadata_sha256']:
            raise ValueError('Candidate metadata changed since staging')
        expected = {}
        for (level, geoid), record in records.items():
            for item in observation_rows(candidate_id, config, level, geoid, record):
                expected[(level, geoid, item['measure'])] = (
                    item['period'], item['population'], item['type'], item['value'], item['moe'],
                    item['estimate_annotation'], item['moe_annotation'], item['status'], item['moe_confidence'])
        observed = conn.execute(text(f'''SELECT level,geoid,measure_id,observation_period,population,value_type,value,moe,
            estimate_annotation,moe_annotation,status,moe_confidence FROM {S}.observation_acs_profile
            WHERE release_id=:id'''), {'id': candidate_id}).all()
        if len(observed) != len(expected):
            raise ValueError('ACS observation count differs from source')
        for item in observed:
            if expected.get(tuple(item[:3])) != tuple(item[3:]):
                raise ValueError(f'ACS observation differs from staged source at {item[:3]}')
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
    sub.add_parser('load-cd-boundaries')
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
        if args.action == 'load-cd-boundaries':
            files = load_cd_boundaries(engine, config, ROOT / 'cd_boundaries')
            print(json.dumps({'boundary_files': len(files), 'status': 'loaded'}))
        elif args.action == 'fetch-stage-validate':
            candidate, report = fetch_stage(engine, config, ROOT)
            print(json.dumps({'candidate_id': str(candidate), 'report': report}, indent=2, default=str))
        elif args.action == 'review':
            result = review(engine, args.candidate_id, config)
            result['report'] = {k: v for k, v in result['report'].items() if k != 'metadata_payload'}
            result.pop('source_before', None); result.pop('source_after', None)
            print(json.dumps(result, default=str, indent=2))
        elif args.action == 'approve-publish':
            publish(engine, args.candidate_id, args.semantic_sha256, args.schema_sha256, args.metadata_sha256, config)
            print(f'Published ACS community release {args.candidate_id}')
        elif args.action == 'rollback':
            rollback(engine, config, args.release_id); print(f'Active release reset to {args.release_id}')
        else:
            print(f'Deactivated; prior active release was {deactivate(engine, config)}')


if __name__ == '__main__':
    main()
