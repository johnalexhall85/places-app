"""Manual CMS nursing home candidate, checksum review, publication, and pointer recovery."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import time
import uuid
from contextlib import nullcontext
from pathlib import Path

from sqlalchemy import create_engine, text

from app.area_pilot.acs_cli import file_rows
from app.area_pilot.cms_nursing_homes import (PRODUCT, file_evidence, load_registry, official_csv_url,
    parse_csv, parse_dictionary, retrieve, summarize, typed, validate)
from app.area_pilot.source import digest
from app.db import DATABASE_URL

S = 'area_pilot'
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / PRODUCT
REQUIRED = {'metadata', 'api_count', 'dictionary_pdf', 'provider_csv'}
RELEASABLE = {'same_label_semantic_revision', 'large_change_vs_active'}


def checksums(rows, records, config, metadata, files):
    evidence = {f['role']: f['sha256'] for f in files}
    semantic = digest([row for row in sorted(rows, key=lambda item: item[config['ccn_field']])])
    keyset = digest(sorted(row[config['ccn_field']] for row in rows))
    schema = digest({'header': config['expected_header'], 'rating_fields': config['rating_fields'],
                     'footnotes': config['footnotes'], 'dictionary_sha256': evidence['dictionary_pdf']})
    meta = {'source_metadata': metadata, 'location_policy': config['location_policy'],
            'care_compare_pattern': config['care_compare_pattern'],
            'location_sha256': digest([[item['ccn'], item['location_status'], item['lon'], item['lat']]
                                       for item in sorted(records, key=lambda item: item['ccn'])]),
            'schema_sha256': schema}
    return semantic, schema, digest(meta), keyset, meta


def _hold(engine, config, run_id, candidate, reason, files, checks=None, issues=None, label='NH Provider Information unknown'):
    with engine.begin() as conn:
        conn.execute(text(f'''INSERT INTO {S}.release (id,dataset_id,source_release_id,status,
            semantic_sha256,schema_sha256,metadata_sha256,keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:label,'held',:empty,:empty,:empty,:empty,'{{}}'::jsonb,'{{}}'::jsonb,CAST(:report AS jsonb))'''),
            {'id': candidate, 'dataset': PRODUCT, 'label': label, 'empty': digest([]),
             'report': json.dumps({'hold_reason': reason, 'checks': checks, 'issues': issues, 'files_retained': len(files)})})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'fetch-stage-validate','held',CAST(:detail AS jsonb))'''),
            {'run': run_id, 'id': candidate, 'detail': json.dumps({'hold_reason': reason})})
        for name, passed in (checks or {'source_retrieval': False}).items():
            conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
                VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
                {'id': candidate, 'name': name, 'passed': passed, 'detail': json.dumps(issues if not passed else {})})
        file_rows(conn, run_id, candidate, files)
    return candidate, {'status': 'held', 'hold_reason': reason, 'checks': checks, 'issues': issues}


def fetch_stage(engine, config, directory=ROOT, fetched=None):
    run_id, candidate = uuid.uuid4(), uuid.uuid4()
    started = time.monotonic()
    run_dir = directory / str(run_id)
    try:
        rows, metadata, files, provenance = fetched or retrieve(config, run_dir)
    except (Exception, KeyboardInterrupt) as exc:
        files = [file_evidence(path, '', f'partial:{path.name}') for path in sorted(run_dir.glob('*'))
                 if path.is_file() and not path.name.endswith('.part')]
        return _hold(engine, config, run_id, candidate, str(exc), files)
    checks, issues, records = validate(rows, config)
    processing = next(iter(issues['processing_dates'])) if checks['single_processing_date'] else None
    label = f'NH Provider Information processed {processing}' if processing else 'NH Provider Information unknown'
    checks['metadata_date_matches_processing'] = bool(processing and metadata.get('modified') == processing)
    checks['source_count_matches_api'] = bool(provenance.get('api_count', len(rows)) == len(rows))
    if not all(checks.values()):
        return _hold(engine, config, run_id, candidate, 'blocking_validation_failed', files, checks, issues, label)
    semantic, schema, meta_sha, keyset, meta = checksums(rows, records, config, metadata, files)
    summary = summarize(rows, records)
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': PRODUCT})
        existing = conn.execute(text(f'''SELECT id,status,source_release_id FROM {S}.release
            WHERE dataset_id=:dataset AND semantic_sha256=:semantic AND schema_sha256=:schema
            AND metadata_sha256=:metadata AND keyset_sha256=:keyset
            AND (status IN ('ready','published') OR (status='held' AND report->>'hold_reason' IN
                 ('same_label_semantic_revision','large_change_vs_active'))) ORDER BY created_at LIMIT 1'''),
            {'dataset': PRODUCT, 'semantic': semantic, 'schema': schema, 'metadata': meta_sha,
             'keyset': keyset}).mappings().one_or_none()
        if existing:
            status = 'held' if existing['status'] == 'held' else 'duplicate'
            conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
                VALUES (:run,:id,'fetch-stage-validate',:status,CAST(:detail AS jsonb))'''),
                {'run': run_id, 'id': existing['id'], 'status': status,
                 'detail': json.dumps({'same_semantic_content': True, 'retrieved_at': provenance['retrieved_at']})})
            file_rows(conn, run_id, existing['id'], files)
            return existing['id'], {'status': status, 'source_release_id': existing['source_release_id'],
                                    'semantic_sha256': semantic, 'schema_sha256': schema,
                                    'metadata_sha256': meta_sha, 'keyset_sha256': keyset}
        active = conn.execute(text(f'''SELECT a.release_id,r.source_release_id,r.semantic_sha256,
            r.schema_sha256,r.metadata_sha256
            FROM {S}.active_release a JOIN {S}.release r ON r.id=a.release_id
            WHERE a.dataset_id=:dataset'''), {'dataset': PRODUCT}).mappings().one_or_none()
        change = None
        if active:
            previous = dict(conn.execute(text(f'SELECT ccn,record_sha256 FROM {S}.cms_nursing_home WHERE release_id=:id'),
                                         {'id': active['release_id']}).all())
            current = {item['ccn']: item['sha'] for item in records}
            added = set(current)-set(previous); removed = set(previous)-set(current)
            changed = {key for key in set(current)&set(previous) if current[key] != previous[key]}
            fraction = (len(added)+len(removed)+len(changed))/max(1,len(previous))
            change = {'active_release_id': str(active['release_id']), 'added': len(added),
                      'removed': len(removed), 'changed': len(changed), 'changed_fraction': round(fraction,5),
                      'added_sample': sorted(added)[:20], 'removed_sample': sorted(removed)[:20],
                      'changed_sample': sorted(changed)[:20]}
        same_label_change = bool(active and active['source_release_id'] == label and
            (active['semantic_sha256'],active['schema_sha256'],active['metadata_sha256']) !=
            (semantic,schema,meta_sha))
        reason = ('same_label_semantic_revision' if same_label_change else
                  'large_change_vs_active' if change and change['changed_fraction'] > config['change_hold_fraction'] else None)
        status = 'held' if reason else 'ready'
        report = {'hold_reason': reason, 'checks': checks, 'issues': issues, 'summary': summary,
                  'change_vs_active': change, 'source_url': provenance['csv_url'],
                  'retrieved_at': provenance['retrieved_at'], 'metadata_payload': meta}
        conn.execute(text(f'''INSERT INTO {S}.release (id,dataset_id,source_release_id,status,
            semantic_sha256,schema_sha256,metadata_sha256,keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:label,:status,:semantic,:schema,:metadata,:keyset,
                    CAST(:source AS jsonb),CAST(:source AS jsonb),CAST(:report AS jsonb))'''),
            {'id': candidate, 'dataset': PRODUCT, 'label': label, 'status': status,
             'semantic': semantic, 'schema': schema, 'metadata': meta_sha, 'keyset': keyset,
             'source': json.dumps({k: metadata.get(k) for k in ('issued','modified','released','nextUpdateDate')}),
             'report': json.dumps(report)})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'fetch-stage-validate',:status,CAST(:detail AS jsonb))'''),
            {'run': run_id, 'id': candidate, 'status': status, 'detail': json.dumps({'archive_files': len(files)})})
        file_rows(conn, run_id, candidate, files)
        for name, passed in checks.items():
            conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
                VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
                {'id': candidate, 'name': name, 'passed': passed, 'detail': '{}'})
        for start in range(0,len(rows),1000):
            raw = [{'release': candidate, 'ccn': row[config['ccn_field']], 'line': index+2,
                    'record': json.dumps(row, ensure_ascii=False)}
                   for index,row in enumerate(rows[start:start+1000],start)]
            conn.execute(text(f'''INSERT INTO {S}.stage_cms_nursing_home (release_id,ccn,line_number,record)
                VALUES (:release,:ccn,:line,CAST(:record AS jsonb))'''), raw)
            values = [item | {'release': candidate, 'footnotes': json.dumps(item['footnotes'])}
                      for item in records[start:start+1000]]
            conn.execute(text(f'''INSERT INTO {S}.cms_nursing_home (release_id,ccn,record_sha256,
                provider_name,provider_address,city,state_abbr,zip_code,county_name,provider_type,ownership_type,
                certified_beds,overall_rating,health_inspection_rating,staffing_rating,quality_measure_rating,
                rating_footnotes,geocoding_footnote,processing_date,source_latitude,source_longitude,
                location_status,geom) VALUES (:release,:ccn,:sha,:name,:address,:city,:state,:zip,:county,
                :provider_type,:ownership_type,:beds,:overall,:health,:staffing,:qm,CAST(:footnotes AS jsonb),
                :geocoding_footnote,:processing_date,:source_latitude,:source_longitude,:location_status,
                CASE WHEN CAST(:lon AS text) IS NULL THEN NULL ELSE
                  ST_SetSRID(ST_MakePoint(CAST(:lon AS float8),CAST(:lat AS float8)),4326) END)'''), values)
    return candidate, {'status': status, 'hold_reason': reason, 'checks': checks, 'summary': summary,
                       'source_release_id': label, 'semantic_sha256': semantic, 'schema_sha256': schema,
                       'metadata_sha256': meta_sha, 'keyset_sha256': keyset,
                       'duration_seconds': round(time.monotonic()-started,2)}


def review(engine, candidate, config, connection=None):
    with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
        release = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                               {'id': candidate, 'dataset': PRODUCT}).mappings().one()
        files = conn.execute(text(f'''SELECT DISTINCT ON (role) role,path,url,sha256 FROM {S}.source_file
            WHERE release_id=:id AND role=ANY(:roles) ORDER BY role,retrieved_at'''),
            {'id': candidate, 'roles': sorted(REQUIRED)}).mappings().all()
        if {f['role'] for f in files} != REQUIRED:
            raise ValueError('CMS nursing home archive evidence is incomplete')
        for item in files:
            if file_evidence(item['path'], item['url'], item['role'])['sha256'] != item['sha256']:
                raise ValueError(f'CMS archive checksum mismatch: {item["role"]}')
        paths = {item['role']: item['path'] for item in files}
        metadata = json.loads(Path(paths['metadata']).read_text(encoding='utf-8'))
        if official_csv_url(metadata, config) != next(item['url'] for item in files if item['role']=='provider_csv'):
            raise ValueError('CMS CSV URL no longer matches archived metadata')
        parse_dictionary(paths['dictionary_pdf'])
        rows = parse_csv(paths['provider_csv'], config)
        if json.loads(Path(paths['api_count']).read_text(encoding='utf-8')).get('count') != len(rows):
            raise ValueError('CMS archive source count differs from API evidence')
        checks, issues, records = validate(rows, config)
        if not all(checks.values()):
            raise ValueError(f'CMS archived source validation failed: {issues}')
        semantic,schema,meta_sha,keyset,_ = checksums(rows,records,config,metadata,
            [{'role': item['role'], 'sha256': item['sha256']} for item in files])
        if (semantic,schema,meta_sha,keyset) != tuple(release[key] for key in
                ('semantic_sha256','schema_sha256','metadata_sha256','keyset_sha256')):
            raise ValueError('CMS candidate checksum differs from archived source')
        staged = dict(conn.execute(text(f'SELECT ccn,record FROM {S}.stage_cms_nursing_home WHERE release_id=:id'),
                                   {'id': candidate}).all())
        if staged != {row[config['ccn_field']]:row for row in rows}:
            raise ValueError('CMS staged rows differ from archived source')
        actual = conn.execute(text(f'''SELECT ccn,record_sha256,provider_name,provider_address,city,state_abbr,
            zip_code,county_name,provider_type,ownership_type,processing_date,certified_beds,
            overall_rating,health_inspection_rating,staffing_rating,quality_measure_rating,
            rating_footnotes,geocoding_footnote,location_status,source_latitude,source_longitude,
            ST_X(geom) AS lon,ST_Y(geom) AS lat,ST_SRID(geom) AS srid
            FROM {S}.cms_nursing_home WHERE release_id=:id'''), {'id':candidate}).mappings().all()
        if len(actual)!=len(records):
            raise ValueError('CMS read-model row count changed')
        expected={item['ccn']:item for item in records}
        for row in actual:
            item=expected[row['ccn']]
            pairs=(('record_sha256','sha'),('provider_name','name'),('provider_address','address'),
                   ('city','city'),('state_abbr','state'),('zip_code','zip'),('county_name','county'),
                   ('provider_type','provider_type'),('ownership_type','ownership_type'),
                   ('processing_date','processing_date'),('certified_beds','beds'),
                   ('overall_rating','overall'),('health_inspection_rating','health'),
                   ('staffing_rating','staffing'),('quality_measure_rating','qm'),
                   ('geocoding_footnote','geocoding_footnote'),('location_status','location_status'),
                   ('source_latitude','source_latitude'),('source_longitude','source_longitude'))
            if any(row[a]!=item[b] for a,b in pairs) or row['rating_footnotes']!=item['footnotes']:
                raise ValueError(f'CMS typed row changed: {row["ccn"]}')
            if item['lon'] is None:
                if row['lon'] is not None: raise ValueError(f'CMS excluded location mapped: {row["ccn"]}')
            elif row['srid']!=4326 or abs(row['lon']-float(item['lon']))>1e-9 or abs(row['lat']-float(item['lat']))>1e-9:
                raise ValueError(f'CMS geometry changed: {row["ccn"]}')
        return {'candidate_id':str(candidate),'status':release['status'], 'source_release_id':release['source_release_id'],
                'semantic_sha256':semantic,'schema_sha256':schema,'metadata_sha256':meta_sha,'keyset_sha256':keyset,
                'archive_files_verified':len(files),'rows_verified':len(actual),'summary':summarize(rows,records)}


def _bound(conn,candidate,status):
    conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'),{'dataset':PRODUCT})
    row=conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'),{'id':candidate}).mappings().one()
    if row['dataset_id']!=PRODUCT or row['status']!=status:
        raise ValueError('CMS nursing home candidate has wrong product or status')
    return row


def _approve_checks(conn,row,semantic,schema,metadata):
    if (row['semantic_sha256'],row['schema_sha256'],row['metadata_sha256'])!=(semantic,schema,metadata):
        raise ValueError('CMS nursing home candidate differs from approved checksums')
    if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),{'id':row['id']}).scalar_one():
        raise ValueError('CMS nursing home candidate has failed checks')


def publish(engine,config,candidate,semantic,schema,metadata):
    with engine.begin() as conn:
        row=_bound(conn,candidate,'ready'); _approve_checks(conn,row,semantic,schema,metadata)
        review(engine,candidate,config,conn)
        conn.execute(text(f"UPDATE {S}.release SET status='published',published_at=now() WHERE id=:id"),{'id':candidate})
        conn.execute(text(f'''INSERT INTO {S}.active_release(dataset_id,release_id) VALUES(:dataset,:id)
          ON CONFLICT(dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
          {'dataset':PRODUCT,'id':candidate})
        conn.execute(text(f'''INSERT INTO {S}.run(id,release_id,action,status,detail)
          VALUES(:run,:id,'publish','complete','{{"reason":"checksum_bound_operator_approval"}}'::jsonb)'''),
          {'run':uuid.uuid4(),'id':candidate})


def release_reviewed_hold(engine,config,candidate,semantic,schema,metadata,note):
    if not note.strip(): raise ValueError('Operator review note is required')
    with engine.begin() as conn:
        row=_bound(conn,candidate,'held'); reason=row['report'].get('hold_reason')
        if reason not in RELEASABLE: raise ValueError('CMS hold cannot be released by review')
        _approve_checks(conn,row,semantic,schema,metadata); review(engine,candidate,config,conn)
        active=conn.execute(text(f'''SELECT a.release_id,r.source_release_id,r.semantic_sha256,
          r.schema_sha256,r.metadata_sha256 FROM {S}.active_release a
          JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),{'dataset':PRODUCT}).mappings().one_or_none()
        if (not active or str(active['release_id'])!=(row['report'].get('change_vs_active') or {}).get('active_release_id')
                or (reason=='same_label_semantic_revision' and
                    (active['source_release_id']!=row['source_release_id'] or
                     (active['semantic_sha256'],active['schema_sha256'],active['metadata_sha256'])==
                     (row['semantic_sha256'],row['schema_sha256'],row['metadata_sha256'])))):
            raise ValueError('Active CMS release changed since the hold was staged')
        conn.execute(text(f'''UPDATE {S}.release SET status='ready',report=jsonb_set(report,'{{hold_reason}}','null'::jsonb)
          WHERE id=:id'''),{'id':candidate})
        conn.execute(text(f'''INSERT INTO {S}.run(id,release_id,action,status,detail)
          VALUES(:run,:id,'release-reviewed-hold','complete',CAST(:detail AS jsonb))'''),
          {'run':uuid.uuid4(),'id':candidate,'detail':json.dumps({'reason':reason,'operator_note':note})})


def set_pointer(engine,action,release_id=None):
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'),{'dataset':PRODUCT})
        if action=='rollback':
            status=conn.execute(text(f'SELECT status FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                                {'id':release_id,'dataset':PRODUCT}).scalar_one_or_none()
            if status!='published': raise ValueError('Rollback target must be a published CMS nursing home release')
            conn.execute(text(f'''INSERT INTO {S}.active_release(dataset_id,release_id) VALUES(:dataset,:id)
              ON CONFLICT(dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
              {'dataset':PRODUCT,'id':release_id})
        else:
            conn.execute(text(f'DELETE FROM {S}.active_release WHERE dataset_id=:dataset'),{'dataset':PRODUCT})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db-url',default=os.getenv('DATABASE_URL',DATABASE_URL))
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('fetch-stage-validate')
    sub.add_parser('review').add_argument('candidate_id',type=uuid.UUID)
    for name in ('approve-publish','release-reviewed-hold'):
        cmd=sub.add_parser(name);cmd.add_argument('candidate_id',type=uuid.UUID)
        for field in ('semantic','schema','metadata'):
            cmd.add_argument(f'--{field}-sha256',required=True)
        if name=='release-reviewed-hold':cmd.add_argument('--operator-note',required=True)
    sub.add_parser('rollback').add_argument('release_id',type=uuid.UUID)
    sub.add_parser('deactivate')
    args=parser.parse_args(); config=load_registry(); engine=create_engine(args.db_url,pool_pre_ping=True)
    ROOT.mkdir(parents=True,exist_ok=True)
    with (ROOT/'ingest.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.action=='fetch-stage-validate':
            candidate,report=fetch_stage(engine,config);print(json.dumps({'candidate_id':str(candidate),'report':report},indent=2))
        elif args.action=='review':print(json.dumps(review(engine,args.candidate_id,config),indent=2))
        elif args.action=='approve-publish':
            publish(engine,config,args.candidate_id,args.semantic_sha256,args.schema_sha256,args.metadata_sha256)
            print(f'Published CMS nursing home release {args.candidate_id}')
        elif args.action=='release-reviewed-hold':
            release_reviewed_hold(engine,config,args.candidate_id,args.semantic_sha256,args.schema_sha256,
                                  args.metadata_sha256,args.operator_note);print('Released reviewed CMS hold')
        else:set_pointer(engine,args.action,getattr(args,'release_id',None));print('CMS nursing home pointer updated')


if __name__=='__main__':main()
