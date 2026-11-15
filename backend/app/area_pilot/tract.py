"""PLACES tract extension using the county pilot release and review contract."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import requests
from sqlalchemy import text

from app.area_pilot.source import (LEGACY_MEASURE_SET_SHA256, SourceClient, check_measure_set, digest, measure_set_digest,
                                   parse_observation, semantic_digest, same_label_revision)

S = 'area_pilot'


def boundary_file(config, root: Path):
    directory = root / 'boundary'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'tl_2023_09_tract.zip'
    if not path.exists():
        response = requests.get(config['ct_boundary_url'], timeout=(10, 90))
        response.raise_for_status()
        temporary = path.with_suffix('.tmp')
        temporary.write_bytes(response.content)
        temporary.replace(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if sha != config['ct_boundary_sha256']:
        raise ValueError('Connecticut tract boundary checksum differs from reviewed Census file')
    return path, sha


def ensure_ct_boundaries(engine, config, root):
    path, sha = boundary_file(config, root)
    shapes = gpd.read_file(f'zip://{path}')
    keys = shapes['GEOID'].tolist()
    if len(keys) != 884 or len(set(keys)) != len(keys) or any(len(k) != 11 or not k.startswith('09') for k in keys):
        raise ValueError('Unexpected Census 2023 Connecticut tract boundary keyset')
    with engine.begin() as conn:
        existing = {row[0]:row[1] for row in conn.execute(text(f'SELECT tract_fips,source_sha256 FROM {S}.tract_boundary_ct_2023'))}
        if existing:
            if len(existing) != 884 or set(existing) != set(keys) or set(existing.values()) != {sha}:
                raise ValueError('Stored Connecticut tract boundary differs from reviewed source')
        else:
            rows = [{'key':row.GEOID,'county':row.GEOID[:5],'name':row.NAME,'sha':sha,
                     'geom':row.geometry.wkb} for row in shapes.itertuples()]
            conn.execute(text(f'''INSERT INTO {S}.tract_boundary_ct_2023
                (tract_fips,county_fips,name,source_sha256,geom)
                VALUES (:key,:county,:name,:sha,ST_Multi(ST_GeomFromWKB(:geom,4326)))'''), rows)
    return {'role':'ct_boundary_2023','path':str(path),'url':config['ct_boundary_url'],
            'sha256':sha,'byte_count':path.stat().st_size,'retrieved_at':datetime.now(timezone.utc)}


def boundary_keys(conn):
    non_ct = set(conn.execute(text("SELECT geoid11 FROM tract_shapes WHERE statefp <> '09' AND geom IS NOT NULL")).scalars())
    ct = set(conn.execute(text(f'SELECT tract_fips FROM {S}.tract_boundary_ct_2023 WHERE geom IS NOT NULL')).scalars())
    return non_ct | ct


def _source_file_rows(client, run_id, candidate_id):
    return [{'id':uuid.uuid4(),'run':run_id,'release':candidate_id,'role':f['role'],
             'path':f['path'],'url':f['url'],'sha':f['sha256'],'bytes':f['byte_count'],
             'at':f['retrieved_at']} for f in client.files]


def _write_source_files(conn, client, run_id, candidate_id):
    rows = _source_file_rows(client, run_id, candidate_id)
    if rows:
        conn.execute(text(f'''INSERT INTO {S}.source_file
            (id,run_id,release_id,role,path,url,sha256,byte_count,retrieved_at)
            VALUES (:id,:run,:release,:role,:path,:url,:sha,:bytes,:at)'''), rows)


def _insert_candidate(conn, candidate_id, config, parent_id, status, semantic, schema, metadata,
                      keyset, before, after, report):
    conn.execute(text(f'''INSERT INTO {S}.release
        (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
         keyset_sha256,source_before,source_after,report,parent_county_release_id)
        VALUES (:id,:dataset,:source_release,:status,:semantic,:schema,:metadata,:keyset,
                CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:report AS jsonb),:parent)'''),
        {'id':candidate_id,'dataset':config['dataset_id'],'source_release':config['source_release_id'],
         'status':status,'semantic':semantic,'schema':schema,'metadata':metadata,'keyset':keyset,
         'before':json.dumps(before),'after':json.dumps(after),'report':json.dumps(report),'parent':parent_id})


def fetch_stage_tract(engine, config, directory: Path, resume_directory=None):
    from app.area_pilot.operations import disk_guard
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    archive = resume_directory or directory / str(run_id)
    client = SourceClient(config, archive)
    boundary_provenance = None
    try:
        disk_guard(directory, 2 * 1024**3)
        boundary_provenance = ensure_ct_boundaries(engine, config, directory)
        before, after, records, stable = client.fetch()
        disk_guard(directory, 2 * 1024**3)
    except Exception as exc:
        report = {'product_scope':'county_tract','checks':{'source_retrieval':False},'hold_reason':str(exc),
                  'raw_files_retained':len(client.files)}
        with engine.begin() as conn:
            parent = conn.execute(text(f'SELECT release_id FROM {S}.active_release WHERE dataset_id=:dataset'),
                                  {'dataset':config['dataset_id']}).scalar_one_or_none()
            _insert_candidate(conn,candidate_id,config,parent,'held',digest([]),digest([]),digest([]),
                              digest([]),{}, {},report)
            conn.execute(text(f"INSERT INTO {S}.run (id,release_id,action,status,detail) VALUES (:run,:id,'fetch-stage-validate','held',CAST(:detail AS jsonb))"),
                         {'run':run_id,'id':candidate_id,'detail':json.dumps({'error':str(exc)})})
            if boundary_provenance:
                client.files.append(boundary_provenance)
            _write_source_files(conn,client,run_id,candidate_id)
            conn.execute(text(f"INSERT INTO {S}.validation (release_id,check_name,passed,detail) VALUES (:id,'source_retrieval',false,CAST(:detail AS jsonb))"),
                         {'id':candidate_id,'detail':json.dumps({'error':str(exc)})})
        return candidate_id, report

    client.files.append(boundary_provenance)
    columns = before['columns']
    semantic = semantic_digest(records,columns,'tractfips')
    schema = digest(columns)
    metadata_payload = {'revision':before['revision'],'name':before['metadata'].get('name'),
                        'description':before['metadata'].get('description'),'columns':columns}
    metadata = digest(metadata_payload)
    keyset = digest(before['keys'])
    measure_set = measure_set_digest(config)
    keys = [row['tractfips'] for row in records]
    check = {'source_stable':stable,'schema_matches_registry':schema == config['expected_schema_sha256'],
             'exact_keyset':keys == before['keys'],
             'tract_count':len(records) == config['expected_tract_count'],
             'valid_tract_ids':all(len(key)==11 and key.isdigit() and row['countyfips']==key[:5]
                                   for key,row in zip(keys,records)),
             'documented_missing_cells':True}
    observations = []
    unavailable = 0
    for row in records:
        for measure in config['measures']:
            value,low,high,status = parse_observation(row,measure)
            expected_status = 'not_published' if row['stateabbr'] in measure.get('documented_unavailable_states',[]) else 'available'
            if status != expected_status:
                check['documented_missing_cells'] = False
            if status == 'not_published':
                unavailable += 1
            observations.append({'key':row['tractfips'],'measure':measure['measure_id'],
                                 'period':measure['observation_period'],'population':measure['population'],
                                 'type':config['value_type'],'value':value,'low':low,'high':high,'status':status})
    check['documented_missing_cells'] &= unavailable == config['expected_unavailable_tract_count']
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'),{'dataset':config['dataset_id']})
        parent = conn.execute(text(f'''SELECT a.release_id,r.status FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset':config['dataset_id']}).mappings().one_or_none()
        if not parent or parent['status'] != 'published':
            raise ValueError('Working published county release is required')
        parent_id = parent['release_id']
        county_count = conn.execute(text(f'SELECT count(DISTINCT county_fips) FROM {S}.observation WHERE release_id=:id'),
                                    {'id':parent_id}).scalar_one()
        check['county_parent_complete'] = county_count == 3143
        parent_measures = conn.execute(text(f'''SELECT DISTINCT measure_id,observation_period,population,value_type
            FROM {S}.observation WHERE release_id=:id'''),{'id':parent_id}).all()
        # The tract release republishes the parent's county rows, so both must carry the same measures.
        check['county_parent_measure_set'] = sorted(tuple(r) for r in parent_measures) == sorted(
            (m['measure_id'],m['observation_period'],m['population'],config['value_type']) for m in config['measures'])
        available_boundaries = boundary_keys(conn)
        missing = sorted(set(keys)-available_boundaries)
        check['boundary_join'] = not missing
        check['ct_boundary_join'] = all(k in available_boundaries for k in keys if k.startswith('09'))
        existing = conn.execute(text(f'''SELECT id,status FROM {S}.release WHERE dataset_id=:dataset
            AND parent_county_release_id IS NOT NULL AND semantic_sha256=:semantic AND schema_sha256=:schema
            AND metadata_sha256=:metadata
            AND COALESCE(report->>'measure_set_sha256',:legacy_measures)=:measures
            AND keyset_sha256=:keyset AND (status IN ('ready','published') OR
                (status='held' AND report->>'hold_reason'='same_label_semantic_revision'))
            ORDER BY created_at LIMIT 1'''),
            {'dataset':config['dataset_id'],'semantic':semantic,'schema':schema,
             'metadata':metadata,'keyset':keyset,'measures':measure_set,
             'legacy_measures':LEGACY_MEASURE_SET_SHA256}).mappings().one_or_none()
        if existing and all(check.values()):
            run_status = 'held' if existing['status'] == 'held' else 'duplicate'
            conn.execute(text(f"INSERT INTO {S}.run (id,release_id,action,status,detail) VALUES (:run,:id,'fetch-stage-validate',:status,jsonb_build_object('same_semantic_content',true,'reused_held_candidate',:reused))"),
                         {'run':run_id,'id':existing['id'],'status':run_status,'reused':run_status=='held'})
            _write_source_files(conn,client,run_id,existing['id'])
            return existing['id'], {'duplicate':run_status=='duplicate','reused_held_candidate':run_status=='held',
                                     'raw_files_retained':len(client.files)}
        previous_tract = conn.execute(text(f'''SELECT semantic_sha256,source_release_id FROM {S}.release
            WHERE dataset_id=:dataset AND source_release_id=:label AND status='published'
            AND parent_county_release_id IS NOT NULL ORDER BY published_at DESC LIMIT 1'''),
            {'dataset':config['dataset_id'],'label':config['source_release_id']}).mappings().one_or_none()
        revision_hold = same_label_revision(previous_tract, config['source_release_id'], semantic)
        # Compare with reviewed tract metadata. During a county-then-tract rollout the active release is
        # the county-only parent, whose metadata describes a different CDC file; use the most recently
        # published tract release in that case.
        active_metadata = conn.execute(text(f'''SELECT r.metadata_sha256 FROM {S}.release r
            LEFT JOIN {S}.active_release a ON a.release_id=r.id AND a.dataset_id=r.dataset_id
            WHERE r.dataset_id=:dataset AND r.status='published' AND r.parent_county_release_id IS NOT NULL
            ORDER BY (a.release_id IS NOT NULL) DESC, r.published_at DESC LIMIT 1'''),
            {'dataset':config['dataset_id']}).scalar_one_or_none()
        check['metadata_matches_active'] = active_metadata is None or active_metadata == metadata
        status = 'ready' if all(check.values()) and not revision_hold else 'held'
        report = {'product_scope':'county_tract','parent_county_release_id':str(parent_id),
                  'checks':check,'tract_count':len(records),'observation_count':len(observations),
                  'unavailable_cell_count':unavailable,'measure_set_sha256':measure_set,
                  'measure_ids':[m['measure_id'] for m in config['measures']],'unmatched_tracts':missing[:50],
                  'page_count':sum(f['role'].startswith('page_') for f in client.files),
                  'hold_reason':'same_label_semantic_revision' if revision_hold else None,
                  'columns':columns,'metadata_payload':metadata_payload,
                  'source_stability_method':'pre/post revision, schema, complete ordered tract keyset; keyset pages; exact retrieved key equality',
                  'source_stability_limitation':'Socrata has no transactional snapshot; an undetected value change and reversion remains possible.',
                  'boundary_vintage':config['boundary_vintage'],
                  'boundary_source_sha256':boundary_provenance['sha256']}
        _insert_candidate(conn,candidate_id,config,parent_id,status,semantic,schema,metadata,keyset,
                          before['revision'],after['revision'],report)
        conn.execute(text(f"INSERT INTO {S}.run (id,release_id,action,status,detail) VALUES (:run,:id,'fetch-stage-validate',:status,CAST(:detail AS jsonb))"),
                     {'run':run_id,'id':candidate_id,'status':status,'detail':json.dumps({'files':len(client.files)})})
        _write_source_files(conn,client,run_id,candidate_id)
        conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
            VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
            [{'id':candidate_id,'name':name,'passed':passed,'detail':json.dumps({'value':passed})}
             for name,passed in check.items()])
        conn.execute(text(f'''INSERT INTO {S}.stage_county (release_id,county_fips,record)
            SELECT :new,county_fips,record FROM {S}.stage_county WHERE release_id=:parent'''),
            {'new':candidate_id,'parent':parent_id})
        conn.execute(text(f'''INSERT INTO {S}.observation
            (release_id,county_fips,measure_id,observation_period,population,value_type,value,ci_low,ci_high,status)
            SELECT :new,county_fips,measure_id,observation_period,population,value_type,value,ci_low,ci_high,status
            FROM {S}.observation WHERE release_id=:parent'''),{'new':candidate_id,'parent':parent_id})
        conn.execute(text(f'''INSERT INTO {S}.stage_tract (release_id,tract_fips,record)
            VALUES (:id,:key,CAST(:record AS jsonb))'''),
            [{'id':candidate_id,'key':r['tractfips'],'record':json.dumps(r,separators=(',',':'))} for r in records])
        conn.execute(text(f'''INSERT INTO {S}.observation_tract
            (release_id,tract_fips,measure_id,observation_period,population,value_type,value,ci_low,ci_high,status)
            VALUES (:id,:key,:measure,:period,:population,:type,:value,:low,:high,:status)'''),
            [{'id':candidate_id,**row} for row in observations])
    return candidate_id, report


def publish_tract(engine, config, args):
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'),{'dataset':config['dataset_id']})
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'),
                           {'id':args.candidate_id}).mappings().one()
        if row['dataset_id'] != config['dataset_id'] or row['status'] != 'ready' or not row['parent_county_release_id']:
            raise ValueError('Tract candidate is not ready')
        if (row['semantic_sha256'],row['schema_sha256'],row['metadata_sha256']) != (
                args.semantic_sha256,args.schema_sha256,args.metadata_sha256):
            raise ValueError('Candidate checksums differ from reviewed values')
        check_measure_set(row, config, args)
        active = conn.execute(text(f'SELECT release_id FROM {S}.active_release WHERE dataset_id=:dataset'),
                              {'dataset':config['dataset_id']}).scalar_one_or_none()
        if active != row['parent_county_release_id']:
            raise ValueError('Active county parent changed after tract validation')
        report = row['report']
        if digest(report['columns']) != row['schema_sha256'] or digest(report['metadata_payload']) != row['metadata_sha256']:
            raise ValueError('Candidate schema or metadata changed')
        staged = conn.execute(text(f'SELECT tract_fips,record FROM {S}.stage_tract WHERE release_id=:id ORDER BY tract_fips'),
                              {'id':args.candidate_id}).mappings().all()
        if len(staged) != config['expected_tract_count'] or semantic_digest(
                [item['record'] for item in staged],report['columns'],'tractfips') != row['semantic_sha256']:
            raise ValueError('Candidate staged tract content changed')
        if digest([item['tract_fips'] for item in staged]) != row['keyset_sha256']:
            raise ValueError('Candidate tract keyset changed')
        observed = conn.execute(text(f'''SELECT tract_fips,measure_id,observation_period,population,value_type,
            value,ci_low,ci_high,status FROM {S}.observation_tract WHERE release_id=:id
            ORDER BY tract_fips,measure_id'''),{'id':args.candidate_id}).mappings().all()
        expected = []
        for item in staged:
            for measure in config['measures']:
                value,low,high,status = parse_observation(item['record'],measure)
                expected.append((item['tract_fips'],measure['measure_id'],measure['observation_period'],
                                 measure['population'],config['value_type'],value,low,high,status))
        expected.sort(key=lambda item:(item[0],item[1]))
        if [tuple(item.values()) for item in observed] != expected:
            raise ValueError('Candidate tract observations changed')
        county_diff = conn.execute(text(f'''SELECT count(*) FROM (
            (SELECT county_fips,measure_id,observation_period,population,value_type,value,ci_low,ci_high,status
             FROM {S}.observation WHERE release_id=:new
             EXCEPT SELECT county_fips,measure_id,observation_period,population,value_type,value,ci_low,ci_high,status
             FROM {S}.observation WHERE release_id=:parent)
            UNION ALL
            (SELECT county_fips,measure_id,observation_period,population,value_type,value,ci_low,ci_high,status
             FROM {S}.observation WHERE release_id=:parent
             EXCEPT SELECT county_fips,measure_id,observation_period,population,value_type,value,ci_low,ci_high,status
             FROM {S}.observation WHERE release_id=:new)
        ) d'''),{'new':args.candidate_id,'parent':active}).scalar_one()
        county_stage_diff = conn.execute(text(f'''SELECT count(*) FROM (
            (SELECT county_fips,record FROM {S}.stage_county WHERE release_id=:new
             EXCEPT SELECT county_fips,record FROM {S}.stage_county WHERE release_id=:parent)
            UNION ALL
            (SELECT county_fips,record FROM {S}.stage_county WHERE release_id=:parent
             EXCEPT SELECT county_fips,record FROM {S}.stage_county WHERE release_id=:new)
        ) d'''),{'new':args.candidate_id,'parent':active}).scalar_one()
        county_count = conn.execute(text(f'SELECT count(*) FROM {S}.observation WHERE release_id=:id'),
                                    {'id':args.candidate_id}).scalar_one()
        validations = dict(conn.execute(text(f'SELECT check_name,passed FROM {S}.validation WHERE release_id=:id'),
                                        {'id':args.candidate_id}).all())
        if county_diff or county_stage_diff or county_count != 3143 * len(config['measures']) or not validations.get('source_db_sample_parity') or not all(validations.values()):
            raise ValueError('County copy, source sample, or validation checks failed')
        conn.execute(text(f"UPDATE {S}.release SET status='published',published_at=now() WHERE id=:id"),
                     {'id':args.candidate_id})
        conn.execute(text(f'''UPDATE {S}.active_release SET release_id=:id,updated_at=now()
            WHERE dataset_id=:dataset'''),{'id':args.candidate_id,'dataset':config['dataset_id']})
        conn.execute(text(f"INSERT INTO {S}.run (id,release_id,action,status,detail) VALUES (:run,:id,'publish','complete',jsonb_build_object('reason','checksum_bound_operator_approval'))"),
                     {'run':uuid.uuid4(),'id':args.candidate_id})


def review_source_db_sample(engine, candidate_id, config):
    """Verify retained source bytes against staged rows and observations before approval."""
    with engine.begin() as conn:
        release = conn.execute(text(f'SELECT status,report FROM {S}.release WHERE id=:id FOR UPDATE'),
                               {'id':candidate_id}).mappings().one()
        if release['status'] not in ('ready','held') or release['report'].get('product_scope') != 'county_tract':
            return {'skipped': True, 'reason': 'Candidate is not a staged tract release'}
        files = conn.execute(text(f'''SELECT role,path,sha256,byte_count FROM {S}.source_file
            WHERE release_id=:id AND run_id=(SELECT id FROM {S}.run WHERE release_id=:id
                AND action='fetch-stage-validate' AND status IN ('ready','held') ORDER BY created_at LIMIT 1)
                AND role LIKE 'page_%' ORDER BY role'''),
            {'id':candidate_id}).mappings().all()
        sampled = {}
        byte_count = 0
        error = None
        try:
            if len(files) != release['report']['page_count']:
                raise ValueError('Source page archive count differs from candidate report')
            for file in files:
                content = Path(file['path']).read_bytes()
                byte_count += len(content)
                if len(content) != file['byte_count'] or hashlib.sha256(content).hexdigest() != file['sha256']:
                    raise ValueError(f"Original source bytes changed for {file['role']}")
                rows = json.loads(content)
                for item in (rows[0], rows[len(rows)//2], rows[-1]):
                    sampled[item['tractfips']] = item
            for tract_id, source_row in sampled.items():
                staged = conn.execute(text(f'SELECT record FROM {S}.stage_tract WHERE release_id=:id AND tract_fips=:key'),
                                      {'id':candidate_id,'key':tract_id}).scalar_one_or_none()
                if staged != source_row:
                    raise ValueError(f'Source/stage sample mismatch at {tract_id}')
                actual = conn.execute(text(f'''SELECT measure_id,observation_period,population,value_type,
                    value,ci_low,ci_high,status FROM {S}.observation_tract
                    WHERE release_id=:id AND tract_fips=:key'''),
                    {'id':candidate_id,'key':tract_id}).mappings().all()
                expected = {}
                for measure in config['measures']:
                    value,low,high,status = parse_observation(source_row,measure)
                    expected[measure['measure_id']] = (measure['observation_period'],measure['population'],
                                                         config['value_type'],value,low,high,status)
                if len(actual) != len(expected) or any(
                    (item['observation_period'],item['population'],item['value_type'],item['value'],
                     item['ci_low'],item['ci_high'],item['status']) != expected.get(item['measure_id'])
                    for item in actual
                ):
                    raise ValueError(f'Source/observation sample mismatch at {tract_id}')
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            error = str(exc)
        detail = {'sampled_tracts':len(sampled),'source_pages':len(files),
                  'source_page_bytes_verified':byte_count,'error':error}
        conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
            VALUES (:id,'source_db_sample_parity',:passed,CAST(:detail AS jsonb))
            ON CONFLICT (release_id,check_name) DO UPDATE SET passed=excluded.passed,detail=excluded.detail'''),
            {'id':candidate_id,'passed':error is None,'detail':json.dumps(detail)})
        if error:
            conn.execute(text(f"UPDATE {S}.release SET status='held' WHERE id=:id"),{'id':candidate_id})
        return {'passed':error is None,**detail}
