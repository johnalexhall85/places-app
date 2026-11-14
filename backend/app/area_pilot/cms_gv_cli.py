"""Manual CMS Original Medicare Geographic Variation candidate, review, publication, and pointer recovery."""
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
from app.area_pilot.cms_gv import (boundary_without_source, classify, file_evidence, load_registry,
                                   observation_values, range_problems, retrieve, scale_evidence, semantic_sha)
from app.area_pilot.source import digest, same_label_revision
from app.db import DATABASE_URL

S = 'area_pilot'
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'cms_om_gv'
REQUIRED_ROLES = {'catalog', 'resources', 'dictionary_pdf', 'methods_pdf', 'gv_csv',
                  'api_stats_total', 'api_stats_selected'}


def schema_payload(config, header_sha):
    return {'header_sha256': header_sha, 'dimensions': config['source_dimensions'],
            'age_level': config['age_level'], 'suppression_token': config['suppression_token'],
            'measures': [{k: m[k] for k in ('measure_id', 'source_field', 'kind', 'unit', 'storage_scale',
                                              'denominator', 'official_definition')} for m in config['measures']],
            'documentation_phrases': config['documentation_phrases']}


def metadata_payload(config, classified, uncovered, header_sha):
    mapping = [[i['source_level'], i['source_code'], i['source_desc'], i['geoid'], i['boundary_status'],
                i['exclusion_reason']] for _, i in sorted(classified.items())]
    return {'source_release_id': config['source_release_id'], 'observation_year': config['observation_year'],
            'catalog': config['catalog'], 'boundary': config['boundary'], 'geography_rules': config['geography_rules'],
            'mapping_sha256': digest(mapping), 'boundary_without_source_sha256': digest(sorted(uncovered.items())),
            'documentation_conflicts': config['documentation_conflicts'],
            'measures_interpretation': {m['measure_id']: m['interpretation'] for m in config['measures']},
            'schema': schema_payload(config, header_sha)}


def keyset_sha(classified):
    return digest([[i['source_level'], i['source_code'], i['source_desc'], i['geoid']]
                   for _, i in sorted(classified.items())])


def expected_observations(records, classified, config):
    """Exactly what the observation table must hold for a candidate, derived from staged source rows."""
    result = {}
    for key, item in classified.items():
        if item['boundary_status'] not in ('matched', 'national_reference'):
            continue
        for value in observation_values(records[key], config):
            measure = value['measure']
            result[(item['level'], item['geoid'], measure['measure_id'])] = (
                value['value'], value['source_value'], value['status'], measure['observation_period'],
                measure['population'], config['value_type'], item['source_desc'])
    return result


def summarize(records, classified, config):
    counts, problems, ranges = {}, [], {}
    for key, item in classified.items():
        if item['boundary_status'] not in ('matched', 'national_reference'):
            continue
        for value in observation_values(records[key], config):
            mid = value['measure']['measure_id']
            bucket = counts.setdefault(item['level'], {}).setdefault(mid, {})
            bucket[value['status']] = bucket.get(value['status'], 0) + 1
            if value['value'] is not None:
                issues = range_problems(value['value'], value['measure'])
                if issues:
                    problems.append({'geoid': item['geoid'], 'level': item['level'], 'measure_id': mid,
                                     'value': value['source_value'], 'problems': issues})
                low, high = ranges.get((item['level'], mid), (value['value'], value['value']))
                ranges[(item['level'], mid)] = (min(low, value['value']), max(high, value['value']))
    return counts, problems, {f'{k[0]}|{k[1]}': [str(v[0]), str(v[1])] for k, v in sorted(ranges.items())}


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


def fetch_stage(engine, config, directory=ROOT, retrieved=None, boundaries=None):
    """Retrieve, validate, and stage one candidate. ``retrieved``/``boundaries`` are test seams."""
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    run_dir = directory / str(run_id)
    started = time.monotonic()
    try:
        records, stats, files, provenance = retrieved(run_dir) if retrieved else retrieve(config, run_dir)
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        return _hold(engine, config, run_id, candidate_id, reason, _files_on_failure(run_dir))

    semantic = semantic_sha(records)
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        if boundaries is None:
            rows = conn.execute(text(f"SELECT level,geoid FROM {S}.acs_boundary_2024 WHERE level IN ('state','county')")).all()
            boundaries = {'state': {g for lvl, g in rows if lvl == 'state'}, 'county': {g for lvl, g in rows if lvl == 'county'}}
        classified, issues = classify(records, boundaries['state'], boundaries['county'], config)
        uncovered, coverage = boundary_without_source(classified, boundaries['state'], boundaries['county'], config)
        meta = metadata_payload(config, classified, uncovered, stats['header_sha256'])
        schema, metadata, keyset = digest(meta['schema']), digest(meta), keyset_sha(classified)
        counts, problems, ranges = summarize(records, classified, config)
        scale = scale_evidence(records, config)
        level_counts = {}
        for level, _, _ in records:
            level_counts[level] = level_counts.get(level, 0) + 1
        missing_cells = sum(n for lvl in counts.values() for m in lvl.values() for s, n in m.items() if s == 'missing')
        matched = [i for i in classified.values() if i['boundary_status'] == 'matched']
        expected = expected_observations(records, classified, config)
        checks = {
            'schema_and_definitions': stats['header_sha256'] == config['expected_header_sha256'],
            'latest_year_selected': stats['latest_year'] == str(config['observation_year']),
            # Only documented age codes appear, and exactly the 'All' rows were selected at every level.
            'age_level_filter': all(k.split('|', 1)[1] in config['expected_age_levels']
                                    for k in stats['selected_year_age_counts']) and
                all(stats['selected_year_age_counts'].get(f'{lvl}|{config["age_level"]}') == n
                    for lvl, n in level_counts.items()) and
                all(r['BENE_AGE_LVL'] == config['age_level'] and r['YEAR'] == str(config['observation_year'])
                    for r in records.values()),
            'row_counts_by_level': level_counts == config['expected_levels'],
            'unique_geography_keys': not issues['duplicate_geoids'],
            'suppression_and_missing_codes': missing_cells == 0,
            'numeric_ranges': not problems,
            'percentage_scale_0_1': scale['passed'],
            'source_geography_accounting': not issues['unexplained'] and not issues['exclusion_count_mismatch'],
            'boundary_coverage_explained': not coverage['unexplained'] and not coverage['count_mismatch'],
            'api_cross_check': provenance['api_cross_check']['passed'],
            'observation_count': len(expected) == (len(matched) + 1) * len(config['measures']),
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
        hold_reason = ('geography_mismatch' if not checks['source_geography_accounting'] or
                       not checks['boundary_coverage_explained'] else
                       'validation_failed' if not all(checks.values()) else
                       'same_label_semantic_revision' if revision_hold else None)
        exclusions = {f"{i['source_level']}|{i['source_code']}|{i['source_desc']}": i['exclusion_reason']
                      for i in classified.values() if i['boundary_status'] == 'source_only'}
        report = {'checks': checks, 'hold_reason': hold_reason, 'selected_rows': len(records),
                  'level_counts': level_counts, 'matched': {lvl: sum(1 for i in matched if i['level'] == lvl)
                                                            for lvl in ('state', 'county')},
                  'source_rows_without_compatible_boundary': exclusions,
                  'boundary_without_source_observation': coverage['counts'],
                  'boundary_without_source_detail': uncovered,
                  'unexplained': [list(k) for k in issues['unexplained']] + coverage['unexplained'],
                  'exclusion_count_mismatch': issues['exclusion_count_mismatch'] + coverage['count_mismatch'],
                  'observation_count': len(expected), 'status_counts': counts, 'value_ranges': ranges,
                  'range_problems': problems[:50], 'scale_evidence': scale, 'provenance': provenance,
                  'metadata_payload': meta,
                  'year_rule': 'latest YEAR present in the CMS CSV; must equal the registry and catalog temporal end year',
                  'age_rule': "BENE_AGE_LVL == 'All' (dictionary: 'All Beneficiaries'); age-stratified rows are counted, never combined",
                  'boundary_rule': 'Exact CMS state/county FIPS joined to TIGER/Line 2024; national row kept as reference only'}
        conn.execute(text(f'''INSERT INTO {S}.release
            (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
             keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:source,:status,:semantic,:schema,:metadata,:keyset,
                    CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:report AS jsonb))'''),
            {'id': candidate_id, 'dataset': config['dataset_id'], 'source': config['source_release_id'],
             'status': status, 'semantic': semantic, 'schema': schema, 'metadata': metadata, 'keyset': keyset,
             'before': json.dumps(prior and dict(prior) or {}),
             'after': json.dumps(provenance['catalog_entry'], default=str),
             'report': json.dumps(report, default=str)})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'fetch-stage-validate',:status,CAST(:detail AS jsonb))'''),
            {'run': run_id, 'id': candidate_id, 'status': status, 'detail': json.dumps({'archive_files': len(files)})})
        file_rows(conn, run_id, candidate_id, files)
        for name, passed in checks.items():
            conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
                VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
                {'id': candidate_id, 'name': name, 'passed': passed, 'detail': json.dumps(
                    {'unexplained': report['unexplained'], 'mismatch': report['exclusion_count_mismatch']}
                    if name in ('source_geography_accounting', 'boundary_coverage_explained') else {})})
        conn.execute(text(f'''INSERT INTO {S}.stage_cms_gv
            (release_id,source_level,source_code,source_desc,record,geo_level,geoid,boundary_status,exclusion_reason)
            VALUES (:release,:level,:code,:desc,CAST(:record AS jsonb),:geo_level,:geoid,:status,:reason)'''),
            [{'release': candidate_id, 'level': i['source_level'], 'code': i['source_code'], 'desc': i['source_desc'],
              'record': json.dumps(records[key], separators=(',', ':')), 'geo_level': i['level'],
              'geoid': i['geoid'] if i['boundary_status'] != 'source_only' else None,
              'status': i['boundary_status'], 'reason': i['exclusion_reason']} for key, i in sorted(classified.items())])
        observations = [{'release': candidate_id, 'level': level, 'geoid': geoid, 'measure': mid, 'value': v[0],
                         'source': v[1], 'status': v[2], 'period': v[3], 'population': v[4], 'type': v[5], 'desc': v[6]}
                        for (level, geoid, mid), v in sorted(expected.items())]
        for start in range(0, len(observations), 2000):
            conn.execute(text(f'''INSERT INTO {S}.observation_cms_gv
                (release_id,geo_level,geoid,measure_id,observation_period,population,value_type,value,
                 source_value,status,source_desc)
                VALUES (:release,:level,:geoid,:measure,:period,:population,:type,:value,:source,:status,:desc)'''),
                observations[start:start + 2000])
    return candidate_id, report | {'status': status, 'semantic_sha256': semantic, 'schema_sha256': schema,
                                   'metadata_sha256': metadata, 'keyset_sha256': keyset,
                                   'duration_seconds': round(time.monotonic() - started, 2)}


def review(engine, candidate_id, config, connection=None, verify_files=True):
    with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                           {'id': candidate_id, 'dataset': config['dataset_id']}).mappings().one()
        if row['status'] not in ('ready', 'published', 'held'):
            raise ValueError('Invalid CMS OM GV candidate status')
        files = conn.execute(text(f'SELECT role,path,sha256 FROM {S}.source_file WHERE release_id=:id'),
                             {'id': candidate_id}).mappings().all()
        if verify_files:
            if not REQUIRED_ROLES <= {item['role'] for item in files}:
                raise ValueError('CMS OM GV archive evidence incomplete')
            for item in files:
                if not Path(item['path']).is_file() or file_evidence(item['path'], '', '')['sha256'] != item['sha256']:
                    raise ValueError(f'CMS OM GV archived source checksum mismatch: {item["role"]}')
        staged = conn.execute(text(f'''SELECT source_level,source_code,source_desc,record,geo_level,geoid,
            boundary_status,exclusion_reason FROM {S}.stage_cms_gv WHERE release_id=:id'''),
            {'id': candidate_id}).mappings().all()
        records = {(s['source_level'], s['source_code'], s['source_desc']): s['record'] for s in staged}
        classified = {(s['source_level'], s['source_code'], s['source_desc']): {
            'source_level': s['source_level'], 'source_code': s['source_code'], 'source_desc': s['source_desc'],
            'level': s['geo_level'], 'geoid': s['geoid'], 'boundary_status': s['boundary_status'],
            'exclusion_reason': s['exclusion_reason']} for s in staged}
        if semantic_sha(records) != row['semantic_sha256']:
            raise ValueError('CMS OM GV staged content differs from reviewed checksum')
        meta = row['report']['metadata_payload']
        if (keyset_sha(classified) != row['keyset_sha256'] or digest(meta) != row['metadata_sha256'] or
                digest(meta['schema']) != row['schema_sha256']):
            raise ValueError('CMS OM GV candidate metadata or mapping changed')
        uncovered = row['report']['boundary_without_source_detail']
        if metadata_payload(config, classified, uncovered, meta['schema']['header_sha256']) != meta:
            raise ValueError('CMS OM GV registry changed since this candidate was staged')
        expected = expected_observations(records, classified, config)
        observations = conn.execute(text(f'''SELECT geo_level,geoid,measure_id,value,source_value,status,
            observation_period,population,value_type,source_desc FROM {S}.observation_cms_gv WHERE release_id=:id'''),
            {'id': candidate_id}).all()
        actual = {(o[0], o[1], o[2]): tuple(o[3:]) for o in observations}
        if len(observations) != row['report']['observation_count'] or actual != expected:
            raise ValueError('CMS OM GV observation differs from archived source')
        samples = []
        for level in ('national', 'state', 'county'):
            keys = sorted(k for k in actual if k[0] == level)
            for key in keys[::max(1, len(keys) // 3)][:4]:
                samples.append({'level': key[0], 'geoid': key[1], 'measure_id': key[2],
                                'source_value': actual[key][1], 'stored_value': str(actual[key][0]),
                                'status': actual[key][2]})
        return {'candidate_id': str(candidate_id), 'status': row['status'],
                'semantic_sha256': row['semantic_sha256'], 'schema_sha256': row['schema_sha256'],
                'metadata_sha256': row['metadata_sha256'], 'keyset_sha256': row['keyset_sha256'],
                'archive_files_verified': len(files), 'staged_rows': len(staged),
                'observations_verified': len(observations), 'representative_cells': samples,
                'report': row['report']}


def _bound_candidate(conn, config, candidate_id, statuses):
    conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
    row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'),
                       {'id': candidate_id}).mappings().one()
    if row['dataset_id'] != config['dataset_id'] or row['status'] not in statuses:
        raise ValueError('CMS OM GV candidate is not ready' if statuses == ('ready',) else
                         'CMS OM GV candidate is not an eligible same-label revision hold')
    return row


def publish(engine, config, candidate_id, semantic, schema, metadata, verify_files=True):
    with engine.begin() as conn:
        row = _bound_candidate(conn, config, candidate_id, ('ready',))
        if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (semantic, schema, metadata):
            raise ValueError('CMS OM GV candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('CMS OM GV candidate has failed checks')
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
        raise ValueError('CMS OM GV operator review note is required')
    with engine.begin() as conn:
        row = _bound_candidate(conn, config, candidate_id, ('held',))
        if row['report'].get('hold_reason') != 'same_label_semantic_revision':
            raise ValueError('CMS OM GV candidate is not an eligible same-label revision hold')
        if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (semantic, schema, metadata):
            raise ValueError('CMS OM GV held candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('CMS OM GV held candidate has failed checks')
        review(engine, candidate_id, config, connection=conn, verify_files=verify_files)
        active = conn.execute(text(f'''SELECT r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).mappings().one_or_none()
        if not same_label_revision(active, row['source_release_id'], row['semantic_sha256']):
            raise ValueError('CMS OM GV active release changed since the held revision was staged')
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
                raise ValueError('CMS OM GV rollback target must be a retained published release')
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
            summary = {k: v for k, v in report.items() if k not in ('metadata_payload', 'boundary_without_source_detail')}
            print(json.dumps({'candidate_id': str(candidate), 'report': summary}, indent=2, default=str))
        elif args.action == 'review':
            result = review(engine, args.candidate_id, config)
            result['report'] = {k: result['report'][k] for k in ('checks', 'hold_reason', 'level_counts', 'matched',
                                                                  'observation_count') if k in result['report']}
            print(json.dumps(result, indent=2, default=str))
        elif args.action == 'approve-publish':
            publish(engine, config, args.candidate_id, args.semantic_sha256, args.schema_sha256, args.metadata_sha256)
            print(f'Published CMS OM GV release {args.candidate_id}')
        elif args.action == 'release-reviewed-hold':
            release_reviewed_hold(engine, config, args.candidate_id, args.semantic_sha256, args.schema_sha256,
                                  args.metadata_sha256, args.operator_note)
            print(f'Released reviewed CMS OM GV hold {args.candidate_id}')
        else:
            set_pointer(engine, config, args.action, getattr(args, 'release_id', None))
            print('CMS OM GV active pointer updated')


if __name__ == '__main__':
    main()
