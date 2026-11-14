"""Supervised PLACES county/tract pilot lifecycle: fetch, review, publish, rollback."""
from __future__ import annotations
import argparse
import fcntl
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, text
from app.area_pilot.registry import load_registry
from app.area_pilot.source import (LEGACY_MEASURE_SET_SHA256, SourceClient, check_measure_set, digest, measure_set_digest,
                                   parse_observation, semantic_digest, same_label_revision)
from app.db import DATABASE_URL

S = 'area_pilot'


def report_candidate(conn, candidate_id):
    row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id'), {'id': candidate_id}).mappings().one_or_none()
    if row is None:
        raise ValueError('Unknown candidate')
    checks = conn.execute(text(f'SELECT check_name, passed, detail FROM {S}.validation WHERE release_id=:id ORDER BY check_name'), {'id': candidate_id}).mappings().all()
    summary = {key: (str(value) if isinstance(value, uuid.UUID) else value) for key, value in row.items() if key not in ('source_before','source_after','report')}
    summary['report'] = {key: value for key, value in row['report'].items() if key not in ('columns','metadata_payload')}
    return summary | {'source_before': row['source_before'], 'source_after': row['source_after'], 'checks': [dict(item) for item in checks]}


def fetch_stage(engine, config, directory, resume_directory=None):
    from app.area_pilot.operations import disk_guard
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    client = SourceClient(config, resume_directory or directory / str(run_id))
    try:
        disk_guard(directory, 1024**3)
        before, after, records, stable = client.fetch()
        disk_guard(directory, 1024**3)
    except Exception as exc:
        reason = str(exc) if type(exc) in (RuntimeError, ValueError) else type(exc).__name__
        report = {'hold_reason': reason, 'raw_files_retained': len(client.files)}
        with engine.begin() as conn:
            conn.execute(text(f'''INSERT INTO {S}.release
                (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,
                 metadata_sha256,keyset_sha256,source_before,source_after,report)
                VALUES (:id,:dataset,:source,'held',:empty,:empty,:empty,:empty,
                        '{{}}'::jsonb,'{{}}'::jsonb,CAST(:report AS jsonb))'''),
                {'id':candidate_id,'dataset':config['dataset_id'],'source':config['source_release_id'],
                 'empty':digest([]),'report':json.dumps(report)})
            conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
                VALUES (:run,:id,'fetch-stage-validate','held',CAST(:detail AS jsonb))'''),
                {'run':run_id,'id':candidate_id,'detail':json.dumps({'error':reason})})
            conn.execute(text(f'''INSERT INTO {S}.validation
                (release_id,check_name,passed,detail)
                VALUES (:id,'source_retrieval',false,CAST(:detail AS jsonb))'''),
                {'id':candidate_id,'detail':json.dumps({'error':reason})})
            for file in client.files:
                conn.execute(text(f'''INSERT INTO {S}.source_file
                    (id,run_id,release_id,role,path,url,sha256,byte_count,retrieved_at)
                    VALUES (:id,:run,:release,:role,:path,:url,:sha,:bytes,:at)'''),
                    {'id':uuid.uuid4(),'run':run_id,'release':candidate_id,'role':file['role'],
                     'path':file['path'],'url':file['url'],'sha':file['sha256'],
                     'bytes':file['byte_count'],'at':file['retrieved_at']})
        return candidate_id, report
    semantic = semantic_digest(records, before['columns'])
    schema = digest(before['columns'])
    metadata = digest({'revision':before['revision'], 'name':before['metadata'].get('name'), 'description':before['metadata'].get('description'), 'columns':before['columns']})
    keyset = digest(before['keys'])
    measure_set = measure_set_digest(config)
    check = {'source_stable': stable, 'schema_matches_registry': schema == config['expected_schema_sha256'],
             'exact_keyset': [r['countyfips'] for r in records] == before['keys'],
             'county_count': len(records) == config['expected_county_count']}
    observations = []
    documented_statuses = True
    for row in records:
        for measure in config['measures']:
            value, low, high, status = parse_observation(row, measure)
            expected_status = 'not_published' if row['stateabbr'] in measure.get('documented_unavailable_states', []) else 'available'
            documented_statuses = documented_statuses and status == expected_status
            observations.append((row['countyfips'], measure, value, low, high, status))
    check['documented_missing_cells'] = documented_statuses
    with engine.begin() as conn:
        boundary = conn.execute(text('SELECT COUNT(DISTINCT b.statefp || b.countyfp) FROM dim_county_boundary b WHERE b.geom IS NOT NULL AND b.statefp || b.countyfp = ANY(:keys)'), {'keys':before['keys']}).scalar_one()
        existing = conn.execute(text(f'''SELECT id,status FROM {S}.release WHERE dataset_id=:dataset AND semantic_sha256=:semantic
            AND schema_sha256=:schema AND metadata_sha256=:metadata AND keyset_sha256=:keyset
            AND parent_county_release_id IS NULL
            AND COALESCE(report->>'measure_set_sha256',:legacy_measures)=:measures
            AND (status IN ('ready','published') OR
                 (status='held' AND report->>'hold_reason'='same_label_semantic_revision'))
            ORDER BY created_at LIMIT 1'''),
            {'dataset':config['dataset_id'],'semantic':semantic,'schema':schema,'metadata':metadata,'keyset':keyset,
             'measures':measure_set,'legacy_measures':LEGACY_MEASURE_SET_SHA256}).mappings().one_or_none()
        if existing and stable and boundary == len(records):
            run_status = 'held' if existing['status'] == 'held' else 'duplicate'
            conn.execute(text(f"INSERT INTO {S}.run (id,release_id,action,status,detail) VALUES (:id,:release,'fetch-stage-validate',:status,CAST(:detail AS jsonb))"),
                         {'id':run_id,'release':existing['id'],'status':run_status,
                          'detail':json.dumps({'same_semantic_content':True,'reused_held_candidate':run_status=='held'})})
            for file in client.files:
                conn.execute(text(f'''INSERT INTO {S}.source_file (id,run_id,release_id,role,path,url,sha256,byte_count,retrieved_at)
                    VALUES (:id,:run,:release,:role,:path,:url,:sha,:bytes,:at)'''),
                    {'id':uuid.uuid4(),'run':run_id,'release':existing['id'],'role':file['role'],'path':file['path'],'url':file['url'],
                     'sha':file['sha256'],'bytes':file['byte_count'],'at':file['retrieved_at']})
            return existing['id'], {'duplicate':run_status=='duplicate','reused_held_candidate':run_status=='held',
                                    'same_semantic_content':True,'raw_files_retained':len(client.files)}
        check['boundary_join_2023'] = boundary == len(records)
        active = conn.execute(text(f'''SELECT parent.semantic_sha256, parent.schema_sha256,
            parent.metadata_sha256, parent.keyset_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id
            JOIN {S}.release parent ON parent.id=COALESCE(r.parent_county_release_id,r.id)
            WHERE a.dataset_id=:dataset'''), {'dataset':config['dataset_id']}).mappings().one_or_none()
        check['metadata_matches_active'] = active is None or active['metadata_sha256'] == metadata
        check['active_comparison'] = True
        changes = [] if active is None else [key for key, value in [('semantic_sha256',semantic),('schema_sha256',schema),('metadata_sha256',metadata),('keyset_sha256',keyset)] if active[key] != value]
        prior = conn.execute(text(f'''SELECT parent.source_release_id,parent.semantic_sha256
            FROM {S}.active_release a JOIN {S}.release r ON r.id=a.release_id
            JOIN {S}.release parent ON parent.id=COALESCE(r.parent_county_release_id,r.id)
            WHERE a.dataset_id=:dataset'''),
            {'dataset':config['dataset_id']}).mappings().one_or_none()
        revision_hold = same_label_revision(prior, config['source_release_id'], semantic)
        ready = all(check.values()) and not revision_hold
        status = 'ready' if ready else 'held'
        report = {'checks':check, 'county_count':len(records), 'observation_count':len(observations),
                  'measure_set_sha256':measure_set, 'measure_ids':[m['measure_id'] for m in config['measures']],
                  'page_count':sum(f['role'].startswith('page_') for f in client.files), 'active_changes':changes,
                  'hold_reason':'same_label_semantic_revision' if revision_hold else None,
                  'columns':before['columns'],
                  'metadata_payload':{'revision':before['revision'],'name':before['metadata'].get('name'),
                                      'description':before['metadata'].get('description'),'columns':before['columns']},
                  'source_stability_method':'pre/post revision, schema, full ordered key list; keyset pages; exact retrieved key equality',
                  'source_stability_limitation':'No transactional Socrata snapshot. A value changed and restored without revision metadata changing between checks cannot be detected.'}
        conn.execute(text(f'''INSERT INTO {S}.release (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,keyset_sha256,source_before,source_after,report)
             VALUES (:id,:dataset,:source_release,:status,:semantic,:schema,:metadata,:keyset,CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:report AS jsonb))'''),
            {'id':candidate_id,'dataset':config['dataset_id'],'source_release':config['source_release_id'],'status':status,
             'semantic':semantic,'schema':schema,'metadata':metadata,'keyset':keyset,
             'before':json.dumps(before['revision']),'after':json.dumps(after['revision']),'report':json.dumps(report)})
        conn.execute(text(f'INSERT INTO {S}.run (id,release_id,action,status,detail) VALUES (:id,:release,\'fetch-stage-validate\',:status,CAST(:detail AS jsonb))'),
                     {'id':run_id,'release':candidate_id,'status':status,'detail':json.dumps({'files':len(client.files)})})
        for file in client.files:
            conn.execute(text(f'''INSERT INTO {S}.source_file (id,run_id,release_id,role,path,url,sha256,byte_count,retrieved_at)
                VALUES (:id,:run,:release,:role,:path,:url,:sha,:bytes,:at)'''),
                {'id':uuid.uuid4(),'run':run_id,'release':candidate_id,'role':file['role'],'path':file['path'],'url':file['url'],
                 'sha':file['sha256'],'bytes':file['byte_count'],'at':file['retrieved_at']})
        for name, passed in check.items():
            conn.execute(text(f'INSERT INTO {S}.validation (release_id,check_name,passed,detail) VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'),
                         {'id':candidate_id,'name':name,'passed':passed,'detail':json.dumps({'value':passed})})
        for row in records:
            conn.execute(text(f'INSERT INTO {S}.stage_county (release_id,county_fips,record) VALUES (:id,:fips,CAST(:record AS jsonb))'),
                         {'id':candidate_id,'fips':row['countyfips'],'record':json.dumps(row)})
        for fips, measure, value, low, high, value_status in observations:
            conn.execute(text(f'''INSERT INTO {S}.observation (release_id,county_fips,measure_id,observation_period,population,value_type,value,ci_low,ci_high,status)
                 VALUES (:id,:fips,:measure,:period,:population,:type,:value,:low,:high,:status)'''),
                {'id':candidate_id,'fips':fips,'measure':measure['measure_id'],'period':measure['observation_period'],
                 'population':measure['population'],'type':config['value_type'],'value':value,'low':low,'high':high,'status':value_status})
    return candidate_id, report


def publish(engine, config, args):
    with engine.begin() as conn:
        # Serialize pointer changes and approval against a specific reviewed candidate.
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset':config['dataset_id']})
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'), {'id':args.candidate_id}).mappings().one()
        if row['dataset_id'] != config['dataset_id'] or row['status'] != 'ready':
            raise ValueError('Candidate is not ready for approval')
        if (row['semantic_sha256'],row['schema_sha256'],row['metadata_sha256']) != (args.semantic_sha256,args.schema_sha256,args.metadata_sha256):
            raise ValueError('Candidate checksums differ from reviewed values')
        check_measure_set(row, config, args)
        staged = conn.execute(text(f'SELECT county_fips,record FROM {S}.stage_county WHERE release_id=:id ORDER BY county_fips'), {'id':args.candidate_id}).mappings().all()
        if digest(row['report']['columns']) != row['schema_sha256'] or digest(row['report']['metadata_payload']) != row['metadata_sha256']:
            raise ValueError('Candidate schema or metadata changed since review')
        if semantic_digest([item['record'] for item in staged], row['report']['columns']) != row['semantic_sha256']:
            raise ValueError('Candidate staged content changed since review')
        observed = conn.execute(text(f'''SELECT county_fips,measure_id,observation_period,population,value_type,value,ci_low,ci_high,status
            FROM {S}.observation WHERE release_id=:id ORDER BY county_fips,measure_id'''), {'id':args.candidate_id}).mappings().all()
        expected = []
        for item in staged:
            for measure in config['measures']:
                value, low, high, status = parse_observation(item['record'], measure)
                expected.append((item['county_fips'],measure['measure_id'],measure['observation_period'],measure['population'],
                                 config['value_type'],value,low,high,status))
        expected.sort(key=lambda item:(item[0],item[1]))
        if [tuple(item.values()) for item in observed] != expected:
            raise ValueError('Candidate observations changed since review')
        failed = conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'), {'id':args.candidate_id}).scalar_one()
        if failed:
            raise ValueError('Candidate has failed checks')
        source_count = conn.execute(text(f'SELECT count(*) FROM {S}.stage_county WHERE release_id=:id'), {'id':args.candidate_id}).scalar_one()
        obs_count = conn.execute(text(f'SELECT count(*) FROM {S}.observation WHERE release_id=:id'), {'id':args.candidate_id}).scalar_one()
        if source_count != config['expected_county_count'] or obs_count != source_count * len(config['measures']):
            raise ValueError('Candidate contents changed since review')
        conn.execute(text(f"UPDATE {S}.release SET status='published',published_at=now() WHERE id=:id"), {'id':args.candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
                    ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
                    {'dataset':config['dataset_id'],'id':args.candidate_id})
        conn.execute(text(f"INSERT INTO {S}.run (id,release_id,action,status,detail) VALUES (:run,:id,'publish','complete',jsonb_build_object('reason','checksum_bound_operator_approval'))"), {'run':uuid.uuid4(),'id':args.candidate_id})


def rollback(engine, config, release_id):
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset':config['dataset_id']})
        row = conn.execute(text(f'SELECT status FROM {S}.release WHERE id=:id AND dataset_id=:dataset'), {'id':release_id,'dataset':config['dataset_id']}).scalar_one_or_none()
        if row != 'published':
            raise ValueError('Rollback target must be a retained published release')
        conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
                    ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
                    {'id':release_id,'dataset':config['dataset_id']})
        conn.execute(text(f"INSERT INTO {S}.run (id,release_id,action,status,detail) VALUES (:run,:id,'rollback','complete','{{}}'::jsonb)"), {'run':uuid.uuid4(),'id':release_id})


def deactivate(engine, config):
    """Hide the pilot when there is no previous published pointer to restore."""
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset':config['dataset_id']})
        old_release = conn.execute(text(f'DELETE FROM {S}.active_release WHERE dataset_id=:dataset RETURNING release_id'),
                                   {'dataset':config['dataset_id']}).scalar_one_or_none()
        conn.execute(text(f"INSERT INTO {S}.run (id,release_id,action,status,detail) VALUES (:run,:id,'deactivate','complete','{{}}'::jsonb)"),
                     {'run':uuid.uuid4(),'id':old_release})
    return old_release


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db-url', default=os.getenv('DATABASE_URL', DATABASE_URL))
    sub = parser.add_subparsers(dest='action', required=True)
    fetch = sub.add_parser('fetch-stage-validate')
    fetch.add_argument('--geography', choices=('county','tract'), default='county')
    fetch.add_argument('--directory', type=Path)
    fetch.add_argument('--resume-directory', type=Path, help='Existing interrupted run directory; cached pages are reused only if revision, schema, and keys still match')
    review = sub.add_parser('review'); review.add_argument('candidate_id', type=uuid.UUID)
    approve = sub.add_parser('approve-publish'); approve.add_argument('candidate_id', type=uuid.UUID)
    for name in ('semantic_sha256','schema_sha256','metadata_sha256'):
        approve.add_argument(f'--{name.replace("_", "-")}', required=True)
    approve.add_argument('--measure-set-sha256', help='Required when the candidate report records measure_set_sha256')
    undo = sub.add_parser('rollback'); undo.add_argument('release_id', type=uuid.UUID)
    sub.add_parser('deactivate')
    args = parser.parse_args(); config = load_registry(); engine = create_engine(args.db_url, pool_pre_ping=True)
    lock_path = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'places_ingest.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if args.action == 'fetch-stage-validate':
        geography = args.geography
        source_config = load_registry(geography)
        directory = args.directory or (Path(__file__).resolve().parents[3] / 'data' / 'ingest' / f'places_{geography}_2025')
        if geography == 'tract':
            from app.area_pilot.tract import fetch_stage_tract
            candidate_id, report = fetch_stage_tract(engine, source_config, directory, args.resume_directory)
        else:
            candidate_id, report = fetch_stage(engine, source_config, directory, args.resume_directory)
        print(json.dumps({'candidate_id':str(candidate_id),'report':report}, indent=2))
    elif args.action == 'review':
        with engine.connect() as conn:
            tract_candidate = conn.execute(text(f'SELECT parent_county_release_id IS NOT NULL FROM {S}.release WHERE id=:id'),
                                           {'id':args.candidate_id}).scalar_one_or_none()
        if tract_candidate:
            from app.area_pilot.tract import review_source_db_sample
            review_source_db_sample(engine,args.candidate_id,load_registry('tract'))
        with engine.connect() as conn: print(json.dumps(report_candidate(conn,args.candidate_id), default=str, indent=2))
    elif args.action == 'approve-publish':
        with engine.connect() as conn:
            is_tract = conn.execute(text(f'SELECT parent_county_release_id IS NOT NULL FROM {S}.release WHERE id=:id'),
                                    {'id':args.candidate_id}).scalar_one()
        if is_tract:
            from app.area_pilot.tract import publish_tract
            publish_tract(engine,load_registry('tract'),args)
        else:
            publish(engine,config,args)
        print(f'Published {args.candidate_id}')
    elif args.action == 'rollback':
        rollback(engine,config,args.release_id); print(f'Active release reset to {args.release_id}')
    else:
        old_release = deactivate(engine,config); print(f'Pilot deactivated; prior active release was {old_release}')

if __name__ == '__main__': main()
