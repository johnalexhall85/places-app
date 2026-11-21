"""Manual NCHS drug poisoning mortality candidate, review, publication, and recovery."""
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
from app.area_pilot.drug_poisoning import (
    ROOT, boundary_without_source, classify, file_evidence, load_registry,
    observation_values, range_problems, required_roles, retrieve, semantic_sha,
)
from app.area_pilot.hds_mortality_cli import _files_on_failure, _hold, keyset_sha
from app.area_pilot.source import digest, same_label_revision
from app.db import DATABASE_URL

S = 'area_pilot'


def schema_payload(config, header_shas):
    return {
        'header_sha256': header_shas,
        'observation_year': config['observation_year'],
        'observation_period': config['observation_period'],
        'staged_years': config['staged_years'],
        'value_type': config['value_type'],
        'measures': [
            {k: m[k] for k in (
                'measure_id', 'source_file', 'source_field', 'source_ci_low_field',
                'source_ci_high_field', 'kind', 'unit', 'storage_scale',
                'observation_period', 'population', 'denominator', 'official_definition',
            )}
            for m in config['measures']
        ],
    }


def metadata_payload(config, classified, uncovered, header_shas):
    mapping = [
        [i['source_file'], i['source_level'], i['source_code'], i['source_period'],
         i['geoid'], i['boundary_status'], i['exclusion_reason']]
        for _, i in sorted(classified.items())
    ]
    return {
        'source_release_id': config['source_release_id'],
        'observation_year': config['observation_year'],
        'observation_period': config['observation_period'],
        'staged_years': config['staged_years'],
        'source_files': [
            {k: spec[k] for k in ('measure_id', 'dataset_id', 'filename', 'url')}
            for spec in config['source_files']
        ],
        'boundary': config['boundary'],
        'geography_rules': config['geography_rules'],
        'mapping_sha256': digest(mapping),
        'boundary_without_source_sha256': digest(sorted(uncovered.items())),
        'limitations': config['limitations'],
        'measures_interpretation': {m['measure_id']: m['interpretation'] for m in config['measures']},
        'schema': schema_payload(config, header_shas),
    }


def expected_observations(records, classified, config):
    """Exactly what observation_nchs_drug_poisoning must hold (2021 matched counties only)."""
    publish_period = str(config['observation_period'])
    result = {}
    for key, item in classified.items():
        if item['boundary_status'] != 'matched' or item['source_period'] != publish_period:
            continue
        for value in observation_values(records[key], item['source_file'], config):
            measure = value['measure']
            obs_key = (item['level'], item['geoid'], measure['measure_id'], measure['observation_period'])
            result[obs_key] = (
                value['value'], value['ci_low'], value['ci_high'],
                value['source_value'], value['status'],
                measure['population'], value['value_type'],
            )
    return result


def summarize(records, classified, config):
    publish_period = str(config['observation_period'])
    counts, problems, ranges = {}, [], {}
    for key, item in classified.items():
        if item['boundary_status'] != 'matched' or item['source_period'] != publish_period:
            continue
        for value in observation_values(records[key], item['source_file'], config):
            mid = value['measure']['measure_id']
            bucket = counts.setdefault(item['level'], {}).setdefault(mid, {})
            bucket[value['status']] = bucket.get(value['status'], 0) + 1
            if value['value'] is not None:
                issues = range_problems(value['value'], value['measure'])
                if issues:
                    problems.append({
                        'geoid': item['geoid'], 'level': item['level'], 'measure_id': mid,
                        'value': value['source_value'], 'problems': issues,
                    })
                low, high = ranges.get((item['level'], mid), (value['value'], value['value']))
                ranges[(item['level'], mid)] = (min(low, value['value']), max(high, value['value']))
    return counts, problems, {f'{k[0]}|{k[1]}': [str(v[0]), str(v[1])] for k, v in sorted(ranges.items())}


def validate_counts_and_checks(stats, config):
    """Check total staged row count, per-year row counts (2003–2021), and Durham (37063) 2021 check."""
    files = stats['files']
    expected_years = list(config['staged_years'])
    counts_ok = True
    years_ok = True
    check_details, checks_ok = {}, True

    for spec in config['source_files']:
        fname = spec['filename']
        fstats = files.get(fname) or {}
        if fstats.get('total_rows') != spec['expected_total_rows']:
            counts_ok = False
        year_counts = fstats.get('year_counts') or {}
        if sorted(year_counts) != expected_years:
            years_ok = False
        if any(year_counts.get(yr) != spec['expected_rows_per_year'] for yr in expected_years):
            counts_ok = False
        observed = fstats.get('check_values') or {}
        expected = spec.get('check_values') or {}
        matches = all(observed.get(k) == v for k, v in expected.items())
        check_details[fname] = {'expected': expected, 'observed': observed, 'passed': matches}
        if not matches:
            checks_ok = False

    return counts_ok, years_ok, checks_ok, check_details


def fetch_stage(engine, config, directory=ROOT, retrieved=None, boundaries=None, skip_fetch=False):
    """Retrieve (or read archived with ``skip_fetch``), validate, and stage one NCHS candidate."""
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    directory = Path(directory)
    run_dir = directory if skip_fetch else directory / str(run_id)
    started = time.monotonic()
    try:
        records, stats, files, provenance = (
            retrieved(run_dir) if retrieved else retrieve(config, run_dir, skip_fetch=skip_fetch)
        )
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        retained = [] if skip_fetch else _files_on_failure(run_dir)
        return _hold(engine, config, run_id, candidate_id, reason, retained)

    semantic = semantic_sha(records)
    publish_period = str(config['observation_period'])
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        if boundaries is None:
            rows = conn.execute(text(
                f"SELECT geoid FROM {S}.acs_boundary_2024 WHERE level='county'"
            )).scalars().all()
            boundaries = {'county': set(rows)}
        county_geoids = boundaries['county'] if isinstance(boundaries, dict) else set(boundaries)
        classified, issues = classify(records, county_geoids, config)
        uncovered, coverage = boundary_without_source(classified, county_geoids, config)
        meta = metadata_payload(config, classified, uncovered, stats['header_sha256'])
        schema, metadata, keyset = digest(meta['schema']), digest(meta), keyset_sha(classified)
        counts, problems, ranges = summarize(records, classified, config)
        expected = expected_observations(records, classified, config)
        published_rows = [
            i for i in classified.values()
            if i['boundary_status'] == 'matched' and i['source_period'] == publish_period
        ]
        counts_ok, years_ok, check_vals_ok, check_details = validate_counts_and_checks(stats, config)
        expected_sha = config.get('expected_header_sha256')
        checks = {
            'schema_and_definitions': (
                not expected_sha or all(v == expected_sha for v in stats['header_sha256'].values())
            ),
            'row_counts': counts_ok,
            'staged_years': years_ok,
            'check_values': check_vals_ok,
            'unique_geography_keys': not issues['duplicate_geoids'],
            'source_geography_accounting': not issues['unexplained'],
            'numeric_ranges': not problems,
            'observation_count': len(expected) == len(published_rows),
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
        hold_reason = (
            'geography_mismatch' if not checks['source_geography_accounting'] else
            'validation_failed' if not all(checks.values()) else
            'same_label_semantic_revision' if revision_hold else None
        )
        exclusions = {
            f"{i['source_file']}|{i['source_code']}": i['exclusion_reason']
            for i in classified.values()
            if i['boundary_status'] == 'source_only' and i['source_period'] == publish_period
        }
        report = {
            'checks': checks,
            'hold_reason': hold_reason,
            'staged_rows': len(records),
            'files': {
                fname: {k: v for k, v in fstats.items() if k != 'header'}
                for fname, fstats in stats['files'].items()
            },
            'matched': {'county': len({i['geoid'] for i in published_rows})},
            'source_only_counts': issues['source_only_counts'],
            'source_rows_without_compatible_boundary': exclusions,
            'boundary_without_source_observation': coverage['counts'],
            'boundary_without_source_detail': uncovered,
            'unexplained': [list(k) for k in issues['unexplained']],
            'check_values': check_details,
            'observation_count': len(expected),
            'status_counts': counts,
            'value_ranges': ranges,
            'range_problems': problems[:50],
            'provenance': provenance,
            'metadata_payload': meta,
            'boundary_rule': (
                'Exact 5-digit FIPS joined to TIGER/Line 2024 county equivalents; '
                '2003–2021 staged, 2021 published; Connecticut legacy counties staged as source_only'
            ),
        }
        conn.execute(text(f'''INSERT INTO {S}.release
            (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
             keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:source,:status,:semantic,:schema,:metadata,:keyset,
                    CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:report AS jsonb))'''),
            {'id': candidate_id, 'dataset': config['dataset_id'], 'source': config['source_release_id'],
             'status': status, 'semantic': semantic, 'schema': schema, 'metadata': metadata, 'keyset': keyset,
             'before': json.dumps(prior and dict(prior) or {}),
             'after': json.dumps({'files': [s['filename'] for s in config['source_files']],
                                  'check_values': check_details}, default=str),
             'report': json.dumps(report, default=str)})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'fetch-stage-validate',:status,CAST(:detail AS jsonb))'''),
            {'run': run_id, 'id': candidate_id, 'status': status,
             'detail': json.dumps({'archive_files': len(files)})})
        file_rows(conn, run_id, candidate_id, files)
        for name, passed in checks.items():
            detail = (
                {'unexplained': report['unexplained']} if name == 'source_geography_accounting' else
                check_details if name == 'check_values' else {}
            )
            conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
                VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
                {'id': candidate_id, 'name': name, 'passed': passed, 'detail': json.dumps(detail)})
        staged_rows = [
            {
                'release': candidate_id, 'source_file': i['source_file'], 'source_level': i['source_level'],
                'source_code': i['source_code'], 'source_period': i['source_period'],
                'record': json.dumps(records[key], separators=(',', ':')), 'geo_level': i['level'],
                'geoid': i['geoid'] if i['boundary_status'] != 'source_only' else None,
                'status': i['boundary_status'], 'reason': i['exclusion_reason'],
            }
            for key, i in sorted(classified.items())
        ]
        for start in range(0, len(staged_rows), 2000):
            conn.execute(text(f'''INSERT INTO {S}.stage_nchs_drug_poisoning
                (release_id,source_file,source_level,source_code,source_period,record,
                 geo_level,geoid,boundary_status,exclusion_reason)
                VALUES (:release,:source_file,:source_level,:source_code,:source_period,
                        CAST(:record AS jsonb),:geo_level,:geoid,:status,:reason)'''),
                staged_rows[start:start + 2000])
        observations = [
            {
                'release': candidate_id, 'level': level, 'geoid': geoid, 'measure': mid,
                'period': period, 'population': v[5], 'type': v[6],
                'value': v[0], 'ci_low': v[1], 'ci_high': v[2],
                'source': v[3], 'status': v[4],
            }
            for (level, geoid, mid, period), v in sorted(expected.items())
        ]
        for start in range(0, len(observations), 2000):
            conn.execute(text(f'''INSERT INTO {S}.observation_nchs_drug_poisoning
                (release_id,geo_level,geoid,measure_id,observation_period,population,value_type,
                 value,ci_low,ci_high,source_value,status)
                VALUES (:release,:level,:geoid,:measure,:period,:population,:type,
                        :value,:ci_low,:ci_high,:source,:status)'''),
                observations[start:start + 2000])
    return candidate_id, report | {
        'status': status, 'semantic_sha256': semantic, 'schema_sha256': schema,
        'metadata_sha256': metadata, 'keyset_sha256': keyset,
        'duration_seconds': round(time.monotonic() - started, 2),
    }


def review(engine, candidate_id, config, connection=None, verify_files=True):
    with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                           {'id': candidate_id, 'dataset': config['dataset_id']}).mappings().one()
        if row['status'] not in ('ready', 'published', 'held'):
            raise ValueError('Invalid NCHS drug poisoning candidate status')
        files = conn.execute(text(f'SELECT role,path,sha256 FROM {S}.source_file WHERE release_id=:id'),
                             {'id': candidate_id}).mappings().all()
        if verify_files:
            if not required_roles(config) <= {item['role'] for item in files}:
                raise ValueError('NCHS drug poisoning archive evidence incomplete')
            for item in files:
                if not Path(item['path']).is_file() or file_evidence(item['path'], '', '')['sha256'] != item['sha256']:
                    raise ValueError(f'NCHS drug poisoning archived source checksum mismatch: {item["role"]}')
        staged = conn.execute(text(f'''SELECT source_file,source_level,source_code,source_period,record,
            geo_level,geoid,boundary_status,exclusion_reason
            FROM {S}.stage_nchs_drug_poisoning WHERE release_id=:id'''),
            {'id': candidate_id}).mappings().all()
        records = {
            (s['source_file'], s['source_level'], s['source_code'], s['source_period']): s['record']
            for s in staged
        }
        classified = {
            (s['source_file'], s['source_level'], s['source_code'], s['source_period']): {
                'source_file': s['source_file'], 'source_level': s['source_level'],
                'source_code': s['source_code'], 'source_period': s['source_period'],
                'level': s['geo_level'], 'geoid': s['geoid'],
                'boundary_status': s['boundary_status'], 'exclusion_reason': s['exclusion_reason'],
            }
            for s in staged
        }
        if semantic_sha(records) != row['semantic_sha256']:
            raise ValueError('NCHS drug poisoning staged content differs from reviewed checksum')
        meta = row['report']['metadata_payload']
        if (keyset_sha(classified) != row['keyset_sha256'] or digest(meta) != row['metadata_sha256'] or
                digest(meta['schema']) != row['schema_sha256']):
            raise ValueError('NCHS drug poisoning candidate metadata or mapping changed')
        uncovered = row['report']['boundary_without_source_detail']
        if metadata_payload(config, classified, uncovered, meta['schema']['header_sha256']) != meta:
            raise ValueError('NCHS drug poisoning registry changed since this candidate was staged')
        expected = expected_observations(records, classified, config)
        observations = conn.execute(text(f'''SELECT geo_level,geoid,measure_id,observation_period,
            value,ci_low,ci_high,source_value,status,population,value_type
            FROM {S}.observation_nchs_drug_poisoning WHERE release_id=:id'''),
            {'id': candidate_id}).all()
        actual = {(o[0], o[1], o[2], o[3]): tuple(o[4:]) for o in observations}
        if len(observations) != row['report']['observation_count'] or actual != expected:
            raise ValueError('NCHS drug poisoning observation differs from archived source')
        keys = sorted(actual)
        samples = [
            {
                'level': key[0], 'geoid': key[1], 'measure_id': key[2],
                'source_value': actual[key][3], 'stored_value': str(actual[key][0]),
                'ci_low': str(actual[key][1]), 'ci_high': str(actual[key][2]),
                'status': actual[key][4],
            }
            for key in keys[::max(1, len(keys) // 3)][:4]
        ]
        return {
            'candidate_id': str(candidate_id), 'status': row['status'],
            'semantic_sha256': row['semantic_sha256'], 'schema_sha256': row['schema_sha256'],
            'metadata_sha256': row['metadata_sha256'], 'keyset_sha256': row['keyset_sha256'],
            'archive_files_verified': len(files), 'staged_rows': len(staged),
            'observations_verified': len(observations), 'representative_cells': samples,
            'report': row['report'],
        }


def _bound_candidate(conn, config, candidate_id, statuses):
    conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
    row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'),
                       {'id': candidate_id}).mappings().one()
    if row['dataset_id'] != config['dataset_id'] or row['status'] not in statuses:
        raise ValueError(
            'NCHS drug poisoning candidate is not ready' if statuses == ('ready',) else
            'NCHS drug poisoning candidate is not an eligible same-label revision hold'
        )
    return row


def publish(engine, config, candidate_id, semantic, schema, metadata, verify_files=True):
    with engine.begin() as conn:
        row = _bound_candidate(conn, config, candidate_id, ('ready',))
        if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (semantic, schema, metadata):
            raise ValueError('NCHS drug poisoning candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('NCHS drug poisoning candidate has failed checks')
        review(engine, candidate_id, config, connection=conn, verify_files=verify_files)
        conn.execute(text(f"UPDATE {S}.release SET status='published',published_at=now() WHERE id=:id"),
                     {'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
            ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
            {'dataset': config['dataset_id'], 'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'publish','complete',
                    jsonb_build_object('reason','checksum_bound_operator_approval'))'''),
            {'run': uuid.uuid4(), 'id': candidate_id})


def release_reviewed_hold(engine, config, candidate_id, semantic, schema, metadata, note, verify_files=True):
    if not note.strip():
        raise ValueError('NCHS drug poisoning operator review note is required')
    with engine.begin() as conn:
        row = _bound_candidate(conn, config, candidate_id, ('held',))
        if row['report'].get('hold_reason') != 'same_label_semantic_revision':
            raise ValueError('NCHS drug poisoning candidate is not an eligible same-label revision hold')
        if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (semantic, schema, metadata):
            raise ValueError('NCHS drug poisoning held candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('NCHS drug poisoning held candidate has failed checks')
        review(engine, candidate_id, config, connection=conn, verify_files=verify_files)
        active = conn.execute(text(f'''SELECT r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
            JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).mappings().one_or_none()
        if not same_label_revision(active, row['source_release_id'], row['semantic_sha256']):
            raise ValueError('NCHS drug poisoning active release changed since the held revision was staged')
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
                raise ValueError('NCHS drug poisoning rollback target must be a retained published release')
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
    stage_cmd = sub.add_parser('fetch-stage-validate')
    stage_cmd.add_argument(
        '--skip-fetch', action='store_true',
        help='Stage from archived CSV in data/ingest/nchs_drug_poisoning_county/ without downloading.',
    )
    review_cmd = sub.add_parser('review')
    review_cmd.add_argument('candidate_id', type=uuid.UUID)
    for name in ('approve-publish', 'release-reviewed-hold'):
        cmd = sub.add_parser(name)
        cmd.add_argument('candidate_id', type=uuid.UUID)
        for field in ('semantic_sha256', 'schema_sha256', 'metadata_sha256'):
            cmd.add_argument('--' + field.replace('_', '-'), required=True)
        if name == 'release-reviewed-hold':
            cmd.add_argument('--operator-note', required=True)
    rollback = sub.add_parser('rollback')
    rollback.add_argument('release_id', type=uuid.UUID)
    sub.add_parser('deactivate')
    args = parser.parse_args()
    config = load_registry()
    engine = create_engine(args.db_url, pool_pre_ping=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'ingest.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'fetch-stage-validate':
            candidate, report = fetch_stage(engine, config, skip_fetch=args.skip_fetch)
            summary = {
                k: v for k, v in report.items()
                if k not in ('metadata_payload', 'boundary_without_source_detail')
            }
            print(json.dumps({'candidate_id': str(candidate), 'report': summary}, indent=2, default=str))
        elif args.action == 'review':
            result = review(engine, args.candidate_id, config)
            result['report'] = {
                k: result['report'][k]
                for k in ('checks', 'hold_reason', 'files', 'matched', 'source_only_counts',
                          'check_values', 'observation_count')
                if k in result['report']
            }
            print(json.dumps(result, indent=2, default=str))
        elif args.action == 'approve-publish':
            publish(engine, config, args.candidate_id, args.semantic_sha256, args.schema_sha256,
                    args.metadata_sha256)
            print(f'Published NCHS drug poisoning release {args.candidate_id}')
        elif args.action == 'release-reviewed-hold':
            release_reviewed_hold(engine, config, args.candidate_id, args.semantic_sha256,
                                  args.schema_sha256, args.metadata_sha256, args.operator_note)
            print(f'Released reviewed NCHS drug poisoning hold {args.candidate_id}')
        else:
            set_pointer(engine, config, args.action, getattr(args, 'release_id', None))
            print('NCHS drug poisoning active pointer updated')


if __name__ == '__main__':
    main()
