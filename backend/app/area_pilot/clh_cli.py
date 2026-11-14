"""Manual CLH candidate, checksum review, publication, and independent rollback."""
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
from app.area_pilot.clh import (file_evidence, load_registry, parse_file, parse_value,
                                 retrieve, semantic_sha, verify_codebook)
from app.area_pilot.source import digest, same_label_revision
from app.db import DATABASE_URL

S = 'area_pilot'
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'clh_2023'
BATCH = 1000


def _chunks(rows, size=BATCH):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def _files_on_failure(directory, config):
    return [file_evidence(directory / url.rsplit('/', 1)[-1], url, role)
            for role, url in config['source_urls'].items()
            if (directory / url.rsplit('/', 1)[-1]).is_file()]


def fetch_stage(engine, config, directory=ROOT):
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    run_dir = directory / str(run_id)
    started = time.monotonic()
    files = []
    try:
        files = retrieve(config, run_dir)
        paths = {role: run_dir / url.rsplit('/', 1)[-1] for role, url in config['source_urls'].items()}
        summaries = verify_codebook(paths['codebook'], config)
        records, layouts = {}, {}
        for level in ('county', 'tract'):
            records[level], layouts[level] = parse_file(paths[level], level, config)
        semantic = semantic_sha(records)
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        files = files or _files_on_failure(run_dir, config)
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

    selected = {m['measure_id']: {k: m[k] for k in ('official_label','unit','population',
                'denominator','observation_period','source','geographies')} for m in config['measures']}
    schema_payload = {'selected': selected, 'layouts': layouts,
                      'codebook_sha256': next(f['sha256'] for f in files if f['role'] == 'codebook')}
    metadata_payload = {'source_release_id': config['source_release_id'],
                        'documentation_sha256': next(f['sha256'] for f in files if f['role'] == 'documentation'),
                        'schema': schema_payload}
    schema = digest(schema_payload)
    metadata = digest(metadata_payload)
    keyset = digest([(level, sorted(records[level])) for level in ('county','tract')])
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        boundaries = {level: set(conn.execute(text(f'''SELECT geoid FROM {S}.acs_boundary_2024
            WHERE level=:level'''), {'level': level}).scalars()) for level in ('county', 'tract')}
        source_only = {level: sorted(set(records[level]) - boundaries[level]) for level in ('county','tract')}
        boundary_only = {level: sorted(boundaries[level] - set(records[level])) for level in ('county','tract')}
        counts = {level: {m['measure_id']: {'available': 0,'true_zero': 0,'missing': 0}
                  for m in config['measures'] if level in m['geographies']} for level in ('county','tract')}
        source_counts = json.loads(json.dumps(counts))
        checks = {'source_row_totals': True, 'selected_variable_coverage': True,
                  'boundary_compatibility': True, 'unique_source_keys': True,
                  'source_codebook_definitions': True}
        for level in ('county','tract'):
            checks['source_row_totals'] &= len(records[level]) == config['expected_source_rows'][level]
            expected_source_only = set(config.get('expected_source_only', {}).get(level, []))
            expected_boundary_only = set(config.get('expected_boundary_only', {}).get(level, []))
            checks['boundary_compatibility'] &= (set(source_only[level]) == expected_source_only and
                                                 set(boundary_only[level]) == expected_boundary_only)
            for geoid, row in records[level].items():
                for measure in config['measures']:
                    if level not in measure['geographies']:
                        continue
                    _, status, _ = parse_value(row[measure['measure_id']], measure['unit'])
                    source_counts[level][measure['measure_id']][status] += 1
                    if geoid in boundaries[level]:
                        counts[level][measure['measure_id']][status] += 1
            for measure in config['measures']:
                if level not in measure['geographies']:
                    continue
                item = summaries[level][measure['measure_id']]
                observed = source_counts[level][measure['measure_id']]
                checks['selected_variable_coverage'] &= (
                    observed['available'] + observed['true_zero'] == item['nonmissing'] and
                    observed['missing'] == item['missing'])
        existing = conn.execute(text(f'''SELECT id,status FROM {S}.release WHERE dataset_id=:dataset
            AND semantic_sha256=:semantic AND schema_sha256=:schema AND metadata_sha256=:metadata
            AND keyset_sha256=:keyset AND status IN ('ready','published') LIMIT 1'''),
            {'dataset': config['dataset_id'], 'semantic': semantic, 'schema': schema,
             'metadata': metadata, 'keyset': keyset}).mappings().one_or_none()
        if existing and all(checks.values()):
            conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
                VALUES (:run,:id,'fetch-stage-validate','duplicate','{{"same_semantic_content":true}}'::jsonb)'''),
                {'run': run_id, 'id': existing['id']})
            file_rows(conn, run_id, existing['id'], files)
            return existing['id'], {'status': 'duplicate', 'checks': checks, 'counts': counts,
                                    'duration_seconds': round(time.monotonic() - started, 2)}
        prior = conn.execute(text(f'''SELECT r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).mappings().one_or_none()
        revision_hold = same_label_revision(prior, config['source_release_id'], semantic)
        status = 'ready' if all(checks.values()) and not revision_hold else 'held'
        hold_reason = ('boundary_mismatch' if not checks['boundary_compatibility'] else
                       'validation_failed' if not all(checks.values()) else
                       'same_label_semantic_revision' if revision_hold else None)
        observation_count = sum(len(set(records[level]) & boundaries[level]) * len(counts[level])
                                for level in ('county','tract'))
        report = {'checks': checks, 'source_rows': {level: len(records[level]) for level in records},
                  'mapped_rows': {level: len(set(records[level]) & boundaries[level]) for level in records},
                  'observation_count': observation_count, 'source_only': source_only,
                  'boundary_only': boundary_only, 'source_counts': source_counts, 'counts': counts,
                  'hold_reason': hold_reason, 'metadata_payload': metadata_payload,
                  'boundary_rule': 'exact GEOID join to existing TIGER/Line 2024 boundaries',
                  'period_rule': 'ACS 2019–2023 five-year estimates; CCBP 2023 establishments'}
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
                 'detail': json.dumps({'source_only': source_only, 'boundary_only': boundary_only}
                                      if name == 'boundary_compatibility' else {})})
        for level in ('county','tract'):
            stages, observations = [], []
            for geoid, record in sorted(records[level].items()):
                matched = geoid in boundaries[level]
                stages.append({'release': candidate_id, 'level': level, 'geoid': geoid,
                               'record': json.dumps(record, separators=(',',':')),
                               'boundary_status': 'matched' if matched else 'source_only',
                               'reason': None if matched else 'no_exact_2024_boundary'})
                if matched:
                    for measure in config['measures']:
                        if level not in measure['geographies']:
                            continue
                        value, item_status, source_code = parse_value(record[measure['measure_id']], measure['unit'])
                        observations.append({'release': candidate_id, 'level': level, 'geoid': geoid,
                            'measure': measure['measure_id'], 'period': measure['observation_period'],
                            'population': measure['population'], 'type': config['value_type'],
                            'value': value, 'status': item_status, 'source_code': source_code})
                if len(stages) >= BATCH:
                    conn.execute(text(f'''INSERT INTO {S}.stage_clh
                        (release_id,level,geoid,record,boundary_status,exclusion_reason)
                        VALUES (:release,:level,:geoid,CAST(:record AS jsonb),:boundary_status,:reason)'''), stages)
                    stages.clear()
                if len(observations) >= BATCH:
                    conn.execute(text(f'''INSERT INTO {S}.observation_clh
                        (release_id,level,geoid,measure_id,observation_period,population,value_type,value,status,source_code)
                        VALUES (:release,:level,:geoid,:measure,:period,:population,:type,:value,:status,:source_code)'''), observations)
                    observations.clear()
            if stages:
                conn.execute(text(f'''INSERT INTO {S}.stage_clh
                    (release_id,level,geoid,record,boundary_status,exclusion_reason)
                    VALUES (:release,:level,:geoid,CAST(:record AS jsonb),:boundary_status,:reason)'''), stages)
            if observations:
                conn.execute(text(f'''INSERT INTO {S}.observation_clh
                    (release_id,level,geoid,measure_id,observation_period,population,value_type,value,status,source_code)
                    VALUES (:release,:level,:geoid,:measure,:period,:population,:type,:value,:status,:source_code)'''), observations)
    return candidate_id, report | {'status': status,
                                   'duration_seconds': round(time.monotonic() - started, 2)}


def review(engine, candidate_id, config, connection=None):
    with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
        row = conn.execute(text(f'''SELECT * FROM {S}.release WHERE id=:id AND dataset_id=:dataset'''),
            {'id': candidate_id, 'dataset': config['dataset_id']}).mappings().one()
        files = conn.execute(text(f'''SELECT role,path,sha256 FROM {S}.source_file
            WHERE release_id=:id ORDER BY retrieved_at'''), {'id': candidate_id}).mappings().all()
        by_role = {f['role']: f for f in files}
        if set(by_role) != set(config['source_urls']):
            raise ValueError('CLH archive evidence incomplete')
        for item in by_role.values():
            with Path(item['path']).open('rb') as handle:
                sha = hashlib.sha256()
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    sha.update(block)
            if sha.hexdigest() != item['sha256']:
                raise ValueError('CLH archived file checksum changed')
        stage_count = conn.execute(text(f'''SELECT count(*) FROM {S}.stage_clh WHERE release_id=:id'''),
                                   {'id': candidate_id}).scalar_one()
        obs_count = conn.execute(text(f'''SELECT count(*) FROM {S}.observation_clh WHERE release_id=:id'''),
                                 {'id': candidate_id}).scalar_one()
        if stage_count != sum(config['expected_source_rows'].values()) or obs_count != row['report']['observation_count']:
            raise ValueError('CLH staged source or observation count changed')
        stage_hash = hashlib.sha256()
        stage_hash.update(b'[')
        keysets = {'county': [], 'tract': []}
        staged_rows = conn.execution_options(stream_results=True).execute(text(f'''SELECT level,geoid,record
            FROM {S}.stage_clh WHERE release_id=:id ORDER BY level,geoid'''), {'id': candidate_id})
        for index, staged in enumerate(staged_rows.mappings()):
            if index:
                stage_hash.update(b',')
            stage_hash.update(json.dumps((staged['level'], staged['geoid'], staged['record']),
                sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())
            keysets[staged['level']].append(staged['geoid'])
        stage_hash.update(b']')
        if stage_hash.hexdigest() != row['semantic_sha256'] or digest(
                [(level, keysets[level]) for level in ('county','tract')]) != row['keyset_sha256']:
            raise ValueError('CLH staged content differs from reviewed checksums')
        checked = 0
        observations = conn.execution_options(stream_results=True).execute(text(f'''SELECT o.level,o.geoid,o.measure_id,
            o.observation_period,o.population,o.value_type,o.value,o.status,o.source_code,s.record
            FROM {S}.observation_clh o JOIN {S}.stage_clh s
            ON s.release_id=o.release_id AND s.level=o.level AND s.geoid=o.geoid
            WHERE o.release_id=:id ORDER BY o.level,o.geoid,o.measure_id'''), {'id': candidate_id})
        measures = {m['measure_id']: m for m in config['measures']}
        for item in observations.mappings():
            measure = measures[item['measure_id']]
            value, status, code = parse_value(item['record'][item['measure_id']], measure['unit'])
            if (None if item['value'] is None else float(item['value']), item['status'], item['source_code'],
                item['observation_period'], item['population'], item['value_type']) != (
                    value, status, code, measure['observation_period'], measure['population'], config['value_type']):
                raise ValueError('CLH observation differs from staged source or registry')
            checked += 1
        if checked != obs_count:
            raise ValueError('CLH observation count changed during checksum review')
        conn.execution_options(stream_results=False)
        samples = []
        for level in ('county','tract'):
            examples = conn.execute(text(f'''SELECT s.geoid,s.record,o.measure_id,o.value,o.status FROM {S}.stage_clh s
                JOIN {S}.observation_clh o ON o.release_id=s.release_id AND o.level=s.level AND o.geoid=s.geoid
                WHERE s.release_id=:id AND s.level=:level AND s.boundary_status='matched'
                ORDER BY s.geoid,o.measure_id LIMIT 15'''),
                {'id': candidate_id, 'level': level}).mappings().all()
            for item in examples:
                measure = next(m for m in config['measures'] if m['measure_id'] == item['measure_id'])
                value, status, _ = parse_value(item['record'][item['measure_id']], measure['unit'])
                if (None if item['value'] is None else float(item['value']), item['status']) != (value, status):
                    raise ValueError('CLH representative source-to-database cell differs')
                samples.append({'level': level, 'geoid': item['geoid'], 'measure_id': item['measure_id'],
                                'value': value, 'status': status})
        if digest(row['report']['metadata_payload']) != row['metadata_sha256'] or digest(
                row['report']['metadata_payload']['schema']) != row['schema_sha256']:
            raise ValueError('CLH reviewed metadata changed')
        return {'candidate_id': str(candidate_id), 'status': row['status'],
                'semantic_sha256': row['semantic_sha256'], 'schema_sha256': row['schema_sha256'],
                'metadata_sha256': row['metadata_sha256'], 'keyset_sha256': row['keyset_sha256'],
                'archive_files_verified': len(files), 'staged_rows': stage_count,
                'observations_verified': obs_count, 'representative_cells': samples,
                'report': row['report']}


def publish(engine, config, candidate_id, semantic, schema, metadata):
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'),
                           {'id': candidate_id}).mappings().one()
        if row['dataset_id'] != config['dataset_id'] or row['status'] != 'ready':
            raise ValueError('CLH candidate is not ready')
        if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (semantic, schema, metadata):
            raise ValueError('CLH candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('CLH candidate has failed checks')
        review(engine, candidate_id, config, connection=conn)
        conn.execute(text(f"UPDATE {S}.release SET status='published',published_at=now() WHERE id=:id"),
                     {'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
            ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
            {'dataset': config['dataset_id'], 'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'publish','complete','{{"reason":"checksum_bound_operator_approval"}}'::jsonb)'''),
            {'run': uuid.uuid4(), 'id': candidate_id})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db-url', default=os.getenv('DATABASE_URL', DATABASE_URL))
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('fetch-stage-validate')
    review_cmd = sub.add_parser('review'); review_cmd.add_argument('candidate_id', type=uuid.UUID)
    approve = sub.add_parser('approve-publish'); approve.add_argument('candidate_id', type=uuid.UUID)
    for field in ('semantic_sha256','schema_sha256','metadata_sha256'):
        approve.add_argument('--' + field.replace('_','-'), required=True)
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
            publish(engine, config, args.candidate_id, args.semantic_sha256, args.schema_sha256,
                    args.metadata_sha256)
            print(f'Published CLH release {args.candidate_id}')
        else:
            with engine.begin() as conn:
                conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'),
                             {'dataset': config['dataset_id']})
                if args.action == 'rollback':
                    status = conn.execute(text(f'''SELECT status FROM {S}.release
                        WHERE id=:id AND dataset_id=:dataset'''),
                        {'id': args.release_id, 'dataset': config['dataset_id']}).scalar_one_or_none()
                    if status != 'published':
                        raise ValueError('CLH rollback target must be a retained published release')
                    conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id)
                        VALUES (:dataset,:id) ON CONFLICT (dataset_id)
                        DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
                        {'dataset': config['dataset_id'], 'id': args.release_id})
                else:
                    conn.execute(text(f'DELETE FROM {S}.active_release WHERE dataset_id=:dataset'),
                                 {'dataset': config['dataset_id']})
            print('CLH active pointer updated')


if __name__ == '__main__':
    main()
