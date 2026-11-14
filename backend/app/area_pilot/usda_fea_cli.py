"""Manual USDA Food Environment Atlas candidate, checksum review, publication, and pointer recovery."""
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
from app.area_pilot.source import digest, same_label_revision
from app.area_pilot.usda_fea import (classify, classify_value, file_evidence, load_registry, retrieve,
                                     semantic_sha, value_note)
from app.db import DATABASE_URL

S = 'area_pilot'
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'usda_food_environment_atlas'
REQUIRED_ROLES = {'landing_page', 'downloads_page', 'documentation', 'csv_zip', 'values_csv',
                  'variable_list_csv', 'readme'}


def schema_payload(config):
    return {'values_header': config['expected_values_header'],
            'variable_header': config['expected_variable_header'],
            'sentinels': config['sentinels'],
            'measures': [{k: m[k] for k in ('measure_id', 'variable_code', 'variable_name', 'source_units',
                                             'observation_period', 'unit', 'kind', 'population', 'official_definition',
                                             'plausible_range')}
                         for m in config['measures']],
            'documentation_phrases': config['documentation_phrases']}


def metadata_payload(config, classified):
    mapping = [[i['measure_id'], i['source_key'], i['geoid'], i['boundary_status'], i['exclusion_reason']]
               for _, i in sorted(classified.items())]
    return {'source_release_id': config['source_release_id'], 'release_markers': config['release_markers'],
            'source_urls': config['source_urls'], 'boundary': config['boundary'],
            'expected_source_only': config['expected_source_only'],
            'expected_boundary_only': config['expected_boundary_only'],
            'documented_value_notes': config['documented_value_notes'],
            'mapping_sha256': digest(mapping), 'schema': schema_payload(config)}


def keyset_sha(classified):
    return digest([[i['measure_id'], i['source_key'], i['geoid']] for _, i in sorted(classified.items())])


def observations_for(config, classified, release_id=None):
    """Typed rows for matched counties; raises on any undocumented value or range violation."""
    by_id = {m['measure_id']: m for m in config['measures']}
    rows = []
    for _, item in sorted(classified.items()):
        if item['boundary_status'] != 'matched':
            continue
        measure = by_id[item['measure_id']]
        value, status = classify_value(item['value'], measure, config)
        rows.append({'release': release_id, 'geoid': item['geoid'], 'measure': measure['measure_id'],
                     'code': measure['variable_code'], 'period': measure['observation_period'],
                     'population': measure['population'], 'type': config['value_type'], 'value': value,
                     'source_value': item['value'], 'status': status,
                     'note': value_note(config, measure['measure_id'], item['geoid']),
                     'state': item['state'], 'county': item['county']})
    return rows


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


def summarize(config, classified, observations):
    counts = {m['measure_id']: {} for m in config['measures']}
    for row in observations:
        counts[row['measure']][row['status']] = counts[row['measure']].get(row['status'], 0) + 1
    exceptions = {}
    for _, item in classified.items():
        if item['boundary_status'] == 'source_only':
            exceptions.setdefault(item['measure_id'], []).append(
                {'source_key': item['source_key'], 'county': item['county'], 'state': item['state'],
                 'source_value': item['value'], 'reason': item['exclusion_reason']})
    ranges = {}
    for row in observations:
        if row['value'] is not None:
            low, high = ranges.get(row['measure'], (row['value'], row['value']))
            ranges[row['measure']] = (min(low, row['value']), max(high, row['value']))
    return counts, exceptions, {k: [str(v[0]), str(v[1])] for k, v in ranges.items()}


def fetch_stage(engine, config, directory=ROOT, retriever=retrieve, boundary_geoids=None):
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    run_dir = directory / str(run_id)
    started = time.monotonic()
    try:
        selected, variables, stats, files, provenance = retriever(config, run_dir)
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        return _hold(engine, config, run_id, candidate_id, reason, _files_on_failure(run_dir))

    semantic = semantic_sha(selected, variables)
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        boundaries = boundary_geoids if boundary_geoids is not None else set(conn.execute(text(
            f"SELECT geoid FROM {S}.acs_boundary_2024 WHERE level='county'")).scalars())
        classified, issues = classify(selected, boundaries, config)
        meta = metadata_payload(config, classified)
        schema, metadata, keyset = digest(meta['schema']), digest(meta), keyset_sha(classified)
        try:
            observations = observations_for(config, classified, candidate_id)
            value_error = None
        except ValueError as exc:
            observations, value_error = [], str(exc)
        keys = [(r['geoid'], r['measure']) for r in observations]
        per_measure = {m['measure_id']: sum(1 for i in classified.values() if i['measure_id'] == m['measure_id'])
                       for m in config['measures']}
        checks = {
            'source_totals': stats['rows'] == config['expected_source_rows'] and
                stats['variables'] == config['expected_variable_count'],
            'variable_lookup_matches_registry': len(variables) == len(config['measures']),
            'values_and_sentinels_documented': value_error is None,
            'unique_geography_measure_keys': len(keys) == len(set(keys)),
            'boundary_join_explained': not issues['unexplained'] and not issues['unexplained_boundary'] and
                not issues['boundary_rule_count_mismatch'],
            'documented_exceptions_present': not issues['expected_absent'] and not issues['value_mismatch'],
            # Every staged row is either one observation or one documented exception; nothing dropped.
            'row_accounting': len(selected) == len(classified) == sum(per_measure.values()) and
                (value_error is not None or len(observations) == sum(
                    1 for i in classified.values() if i['boundary_status'] == 'matched')),
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
        hold_reason = ('geography_mismatch' if not checks['boundary_join_explained'] or
                       not checks['documented_exceptions_present'] else
                       'validation_failed' if not all(checks.values()) else
                       'same_label_semantic_revision' if revision_hold else None)
        counts, exceptions, ranges = summarize(config, classified, observations)
        report = {'checks': checks, 'hold_reason': hold_reason, 'value_error': value_error,
                  'source_stats': stats, 'selected_source_rows': len(selected), 'selected_rows_per_measure': per_measure,
                  'matched_counties': {m: sum(1 for i in classified.values() if i['measure_id'] == m and
                                              i['boundary_status'] == 'matched') for m in per_measure},
                  'boundary_counties': len(boundaries), 'boundary_without_source_row': issues['boundary_only'],
                  'source_rows_without_compatible_boundary': exceptions, 'status_counts': counts,
                  'numeric_ranges': ranges, 'observation_count': len(observations),
                  'unexplained': issues['unexplained'], 'unexplained_boundary': issues['unexplained_boundary'],
                  'boundary_rule_count_mismatch': issues['boundary_rule_count_mismatch'],
                  'expected_absent': issues['expected_absent'], 'value_mismatch': issues['value_mismatch'],
                  'periods': {m['measure_id']: m['observation_period'] for m in config['measures']},
                  'release_label': config['release_label'], 'provenance': provenance, 'metadata_payload': meta,
                  'variable_lookup': variables,
                  'boundary_rule': config['boundary']['join_rule']}
        conn.execute(text(f'''INSERT INTO {S}.release
            (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
             keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:source,:status,:semantic,:schema,:metadata,:keyset,
                    CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:report AS jsonb))'''),
            {'id': candidate_id, 'dataset': config['dataset_id'], 'source': config['source_release_id'],
             'status': status, 'semantic': semantic, 'schema': schema, 'metadata': metadata, 'keyset': keyset,
             'before': json.dumps({'release_markers': config['release_markers']}),
             'after': json.dumps({'csv_zip_href': provenance.get('csv_zip_href'),
                                  'csv_last_updated': provenance.get('csv_last_updated'),
                                  'raw_values_sha256': provenance.get('raw_values_sha256')}),
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
                 'detail': json.dumps({'unexplained': issues['unexplained'][:50],
                                       'unexplained_boundary': issues['unexplained_boundary'][:50]}
                                      if name == 'boundary_join_explained' else
                                      {'error': value_error} if name == 'values_and_sentinels_documented' else {})})
        stages = [{'release': candidate_id, 'measure': i['measure_id'], 'key': i['source_key'], 'fips': i['fips'],
                   'state': i['state'], 'county': i['county'], 'code': i['variable_code'], 'value': i['value'],
                   'geoid': i['geoid'], 'boundary_status': i['boundary_status'], 'reason': i['exclusion_reason']}
                  for _, i in sorted(classified.items())]
        for start in range(0, len(stages), 2000):
            conn.execute(text(f'''INSERT INTO {S}.stage_usda_fea
                (release_id,measure_id,source_key,source_fips,source_state,source_county,variable_code,source_value,
                 geoid,boundary_status,exclusion_reason)
                VALUES (:release,:measure,:key,:fips,:state,:county,:code,:value,:geoid,:boundary_status,:reason)'''),
                stages[start:start + 2000])
        for start in range(0, len(observations), 2000):
            conn.execute(text(f'''INSERT INTO {S}.observation_usda_fea
                (release_id,geoid,measure_id,variable_code,observation_period,population,value_type,value,
                 source_value,status,value_note,source_state,source_county)
                VALUES (:release,:geoid,:measure,:code,:period,:population,:type,:value,:source_value,:status,
                        :note,:state,:county)'''), observations[start:start + 2000])
    return candidate_id, report | {'status': status, 'semantic_sha256': semantic, 'schema_sha256': schema,
                                   'metadata_sha256': metadata, 'keyset_sha256': keyset,
                                   'duration_seconds': round(time.monotonic() - started, 2)}


def review(engine, candidate_id, config, connection=None, verify_files=True):
    with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                           {'id': candidate_id, 'dataset': config['dataset_id']}).mappings().one()
        if row['status'] not in ('ready', 'published', 'held'):
            raise ValueError('Invalid USDA FEA candidate status')
        files = conn.execute(text(f'SELECT role,path,sha256 FROM {S}.source_file WHERE release_id=:id'),
                             {'id': candidate_id}).mappings().all()
        if not REQUIRED_ROLES <= {item['role'] for item in files}:
            raise ValueError('USDA FEA archive evidence incomplete')
        if verify_files:
            from app.area_pilot.usda_fea import sha256_file
            for item in files:
                if not Path(item['path']).is_file() or sha256_file(item['path']) != item['sha256']:
                    raise ValueError(f'USDA FEA archived source checksum mismatch: {item["role"]}')
        staged = conn.execute(text(f'''SELECT measure_id,source_key,source_fips,source_state,source_county,
            variable_code,source_value,geoid,boundary_status,exclusion_reason FROM {S}.stage_usda_fea
            WHERE release_id=:id'''), {'id': candidate_id}).mappings().all()
        report = row['report']
        variables = report['variable_lookup']
        selected, classified = {}, {}
        for s in staged:
            key = (s['source_key'], s['variable_code'])
            selected[key] = {'fips': s['source_fips'], 'state': s['source_state'], 'county': s['source_county'],
                             'variable_code': s['variable_code'], 'value': s['source_value']}
            classified[key] = {'measure_id': s['measure_id'], 'source_key': s['source_key'], **selected[key],
                               'geoid': s['geoid'], 'boundary_status': s['boundary_status'],
                               'exclusion_reason': s['exclusion_reason']}
        if len(selected) != report['selected_source_rows'] or semantic_sha(selected, variables) != row['semantic_sha256']:
            raise ValueError('USDA FEA staged content differs from reviewed checksum')
        meta = report['metadata_payload']
        if (keyset_sha(classified) != row['keyset_sha256'] or digest(meta) != row['metadata_sha256'] or
                digest(meta['schema']) != row['schema_sha256'] or metadata_payload(config, classified) != meta):
            raise ValueError('USDA FEA candidate metadata, mapping, or registry changed')
        expected = {(r['geoid'], r['measure']): (r['value'], r['source_value'], r['status'], r['note'], r['period'],
                                                  r['population'], r['type'], r['code'], r['state'], r['county'])
                    for r in observations_for(config, classified)}
        stored = conn.execute(text(f'''SELECT geoid,measure_id,value,source_value,status,value_note,observation_period,
            population,value_type,variable_code,source_state,source_county
            FROM {S}.observation_usda_fea WHERE release_id=:id'''), {'id': candidate_id}).all()
        actual = {(o[0], o[1]): tuple(o[2:]) for o in stored}
        if len(stored) != report['observation_count'] or actual != expected:
            raise ValueError('USDA FEA observation differs from archived source')
        samples = [{'geoid': g, 'measure_id': m, 'source_value': actual[(g, m)][1], 'stored': str(actual[(g, m)][0]),
                    'status': actual[(g, m)][2]} for g, m in sorted(actual)[::1777][:10]]
        return {'candidate_id': str(candidate_id), 'status': row['status'],
                'semantic_sha256': row['semantic_sha256'], 'schema_sha256': row['schema_sha256'],
                'metadata_sha256': row['metadata_sha256'], 'keyset_sha256': row['keyset_sha256'],
                'archive_files_verified': len(files) if verify_files else 0, 'staged_rows': len(staged),
                'observations_verified': len(stored), 'representative_cells': samples,
                'report': {k: v for k, v in report.items() if k not in ('metadata_payload', 'variable_lookup')}}


def _bound_candidate(conn, config, candidate_id, statuses):
    conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
    row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'),
                       {'id': candidate_id}).mappings().one()
    if row['dataset_id'] != config['dataset_id'] or row['status'] not in statuses:
        raise ValueError('USDA FEA candidate is not ready' if statuses == ('ready',) else
                         'USDA FEA candidate is not an eligible same-label revision hold')
    return row


def publish(engine, config, candidate_id, semantic, schema, metadata, verify_files=True):
    with engine.begin() as conn:
        row = _bound_candidate(conn, config, candidate_id, ('ready',))
        if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (semantic, schema, metadata):
            raise ValueError('USDA FEA candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('USDA FEA candidate has failed checks')
        review(engine, candidate_id, config, connection=conn, verify_files=verify_files)
        conn.execute(text(f"UPDATE {S}.release SET status='published',published_at=now() WHERE id=:id"),
                     {'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
            ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
            {'dataset': config['dataset_id'], 'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'publish','complete',jsonb_build_object('reason','checksum_bound_operator_approval'))'''),
            {'run': uuid.uuid4(), 'id': candidate_id})


def release_reviewed_hold(engine, config, candidate_id, semantic, schema, metadata, note, verify_files=True):
    if not note.strip():
        raise ValueError('USDA FEA operator review note is required')
    with engine.begin() as conn:
        row = _bound_candidate(conn, config, candidate_id, ('held',))
        if row['report'].get('hold_reason') != 'same_label_semantic_revision':
            raise ValueError('USDA FEA candidate is not an eligible same-label revision hold')
        if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (semantic, schema, metadata):
            raise ValueError('USDA FEA held candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('USDA FEA held candidate has failed checks')
        review(engine, candidate_id, config, connection=conn, verify_files=verify_files)
        active = conn.execute(text(f'''SELECT r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).mappings().one_or_none()
        if not same_label_revision(active, row['source_release_id'], row['semantic_sha256']):
            raise ValueError('USDA FEA active release changed since the held revision was staged')
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
                raise ValueError('USDA FEA rollback target must be a retained published release')
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
            report = {k: v for k, v in report.items() if k not in ('metadata_payload', 'variable_lookup')}
            print(json.dumps({'candidate_id': str(candidate), 'report': report}, indent=2, default=str))
        elif args.action == 'review':
            print(json.dumps(review(engine, args.candidate_id, config), indent=2, default=str))
        elif args.action == 'approve-publish':
            publish(engine, config, args.candidate_id, args.semantic_sha256, args.schema_sha256, args.metadata_sha256)
            print(f'Published USDA FEA release {args.candidate_id}')
        elif args.action == 'release-reviewed-hold':
            release_reviewed_hold(engine, config, args.candidate_id, args.semantic_sha256, args.schema_sha256,
                                  args.metadata_sha256, args.operator_note)
            print(f'Released reviewed USDA FEA hold {args.candidate_id}')
        else:
            set_pointer(engine, config, args.action, getattr(args, 'release_id', None))
            print('USDA FEA active pointer updated')


if __name__ == '__main__':
    main()
