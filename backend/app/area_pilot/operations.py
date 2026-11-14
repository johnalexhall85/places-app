"""Pinned metadata checks, full-content verification, and operator reporting."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import resource
import shutil
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import requests
from sqlalchemy import create_engine, text

from app.area_pilot.acs import load_registry as acs_registry
from app.area_pilot.registry import load_registry as places_registry
from app.area_pilot.source import digest, revision, schema_columns
from app.db import DATABASE_URL

ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest'
MIN_FREE_BYTES = int(os.getenv('AREA_INGEST_MIN_FREE_GIB', '5')) * 1024**3
PRODUCTS = ('places', 'acs')


def log(event, **fields):
    print(json.dumps({'event': event, 'at': datetime.now(timezone.utc).isoformat(), **fields},
                     default=str, sort_keys=True), flush=True)


def safe_failure_reason(exc):
    if isinstance(exc, RuntimeError) and str(exc).startswith('Insufficient disk headroom:'):
        return 'disk_pressure_refused'
    return type(exc).__name__


def disk_guard(path=ROOT, needed_bytes=0):
    path.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(path).free
    required = MIN_FREE_BYTES + needed_bytes
    if free < required:
        raise RuntimeError(f'Insufficient disk headroom: available={free}, required={required} bytes')
    return {'available_bytes': free, 'required_bytes': required}


@contextmanager
def product_lock(product):
    path = ROOT / ('acs5_2024_b19013/ingest.lock' if product == 'acs' else 'places_ingest.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def classify_metadata(expected_schema, current_schema, expected_revision, current_revision):
    if current_schema != expected_schema:
        return 'held', 'schema_or_definition_changed'
    if current_revision != expected_revision:
        return 'held', 'same_label_source_revision_changed'
    return 'checked', 'source_metadata_unchanged_no_bulk_download'


def get_json(url):
    try:
        response = requests.get(url, timeout=(10, 30))
        response.raise_for_status()
        return response.json(), hashlib.sha256(response.content).hexdigest()
    except (requests.RequestException, ValueError) as exc:
        # Never print request URLs or exception strings: they can contain API keys.
        raise RuntimeError(f'Source metadata request failed ({type(exc).__name__})') from None


def check_places(conn):
    config = places_registry('tract')
    dataset = config['dataset_id']
    active = conn.execute(text('''SELECT r.id,r.source_before,r.report,r.parent_county_release_id
        FROM area_pilot.active_release a JOIN area_pilot.release r ON r.id=a.release_id
        WHERE a.dataset_id=:dataset'''), {'dataset': dataset}).mappings().one_or_none()
    if not active or not active['parent_county_release_id']:
        return 'held', 'combined_published_release_required', {}
    parent = conn.execute(text('SELECT id,source_before,report FROM area_pilot.release WHERE id=:id'),
                          {'id': active['parent_county_release_id']}).mappings().one()
    results = {}
    for level, saved in (('county', parent), ('tract', active)):
        cfg = places_registry(level)
        metadata, raw_sha = get_json(cfg['source_metadata_api'])
        current_schema = digest(schema_columns(metadata))
        saved_revision = saved['source_before']
        status, reason = classify_metadata(cfg['expected_schema_sha256'], current_schema,
                                           saved_revision, revision(metadata))
        payload = {'revision': revision(metadata), 'name': metadata.get('name'),
                   'description': metadata.get('description'), 'columns': schema_columns(metadata)}
        if status == 'checked' and payload != saved['report'].get('metadata_payload'):
            status, reason = 'held', 'same_label_metadata_changed'
        old_raw_sha = conn.execute(text('''SELECT sha256 FROM area_pilot.source_file
            WHERE release_id=:id AND role='before_metadata'
            ORDER BY retrieved_at LIMIT 1'''), {'id': saved['id']}).scalar_one_or_none()
        if status == 'checked' and old_raw_sha and old_raw_sha != raw_sha:
            reason = 'metadata_serialization_only_changed'
        results[level] = {'status': status, 'reason': reason, 'metadata_sha256': raw_sha,
                          'revision': revision(metadata), 'source_release_id': cfg['source_release_id']}
    holds = [f'{level}:{item["reason"]}' for level, item in results.items() if item['status'] == 'held']
    return ('held', ','.join(holds), results) if holds else ('checked', 'pinned_sources_unchanged', results)


def check_acs(conn):
    config = acs_registry()
    active = conn.execute(text('''SELECT r.source_before FROM area_pilot.active_release a
        JOIN area_pilot.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
        {'dataset': config['dataset_id']}).mappings().one_or_none()
    if not active:
        return 'held', 'published_release_required', {}
    newer_url = 'https://api.census.gov/data/2025/acs/acs5.json'
    try:
        newer = requests.get(newer_url, timeout=(10, 30))
    except requests.RequestException as exc:
        raise RuntimeError(f'ACS release discovery failed ({type(exc).__name__})') from None
    if newer.status_code == 200:
        return 'held', 'unrecognized_2025_acs5_release', {'discovered_url': newer_url}
    if newer.status_code != 404:
        raise RuntimeError(f'ACS release discovery returned HTTP {newer.status_code}')
    base = config['source_api']
    group, group_sha = get_json(base + '/groups/B19013.json')
    geography, geography_sha = get_json(base + '/geography.json')
    selected = set(config['source_variable_ids'])
    variables = group.get('variables', {})
    if not selected <= set(variables):
        return 'held', 'measure_definitions_missing', {'group_sha256': group_sha}
    levels = sorted([item.get('geoLevelDisplay'), item.get('referenceDate')]
                    for item in geography.get('fips', []))
    current = {'variables': {key: variables[key] for key in sorted(selected)},
               'geography': levels, 'raw_group_sha256': group_sha,
               'raw_geography_sha256': geography_sha}
    previous = active['source_before']
    if current['variables'] != previous['variables'] or current['geography'] != previous['geography']:
        return 'held', 'same_label_measure_or_geography_changed', current
    if group_sha != previous['raw_group_sha256'] or geography_sha != previous['raw_geography_sha256']:
        return 'checked', 'metadata_serialization_only_changed', current
    return 'checked', 'pinned_source_metadata_unchanged_no_bulk_download', current


def run_check(engine, product):
    config = places_registry('tract') if product == 'places' else acs_registry()
    dataset = config['dataset_id']
    run_id = uuid.uuid4()
    with product_lock(product):
        with engine.connect() as lock_conn:
            locked = lock_conn.execute(text('SELECT pg_try_advisory_lock(hashtext(:dataset))'),
                                       {'dataset': dataset}).scalar_one()
            if not locked:
                raise RuntimeError(f'{product} database ingestion lock is busy')
            try:
                with engine.begin() as conn:
                    conn.execute(text('''UPDATE area_pilot.source_check SET status='interrupted',
                        reason='previous_process_ended_without_result',finished_at=now()
                        WHERE dataset_id=:dataset AND status='running' '''), {'dataset': dataset})
                    conn.execute(text('''INSERT INTO area_pilot.source_check
                        (id,dataset_id,mode,status,reason,detail)
                        VALUES (:id,:dataset,'metadata','running','started','{}'::jsonb)'''),
                        {'id': run_id, 'dataset': dataset})
                log('source_check_started', product=product, run_id=run_id)
                try:
                    with engine.connect() as conn:
                        status, reason, detail = (check_places(conn) if product == 'places'
                                                  else check_acs(conn))
                except Exception as exc:
                    reason = safe_failure_reason(exc)
                    status, detail = 'failed', {}
                with engine.begin() as conn:
                    conn.execute(text('''UPDATE area_pilot.source_check SET status=:status,reason=:reason,
                        detail=CAST(:detail AS jsonb),finished_at=now() WHERE id=:id'''),
                        {'status': status, 'reason': reason, 'detail': json.dumps(detail), 'id': run_id})
                log('source_check_finished', product=product, run_id=run_id, status=status, reason=reason)
                return status
            finally:
                lock_conn.execute(text('SELECT pg_advisory_unlock(hashtext(:dataset))'),
                                  {'dataset': dataset})


def record_unstarted_failure(engine, product, reason, mode='metadata'):
    config = places_registry('tract') if product == 'places' else acs_registry()
    with engine.begin() as conn:
        conn.execute(text('''INSERT INTO area_pilot.source_check
            (id,dataset_id,mode,status,reason,detail,finished_at)
            VALUES (:id,:dataset,:mode,'failed',:reason,'{}'::jsonb,now())'''),
            {'id': uuid.uuid4(), 'dataset': config['dataset_id'], 'mode': mode,
             'reason': reason})


def ingest_evidence(conn, release_id, started):
    run = conn.execute(text('''SELECT id,status FROM area_pilot.run
        WHERE release_id=:release AND action='fetch-stage-validate' AND created_at>=:started
        ORDER BY created_at DESC LIMIT 1'''),
        {'release': release_id, 'started': started}).mappings().one_or_none()
    if not run:
        raise RuntimeError('Ingestion adapter returned without a current run record')
    files = conn.execute(text('''SELECT role,byte_count FROM area_pilot.source_file
        WHERE run_id=:run'''), {'run': run['id']}).all()
    responses = [(role, size) for role, size in files
                 if not role.startswith('tiger2024_') and role != 'ct_boundary_2023']
    return {'run_id': str(run['id']), 'run_status': run['status'],
            'archived_response_count': len(responses),
            'archived_response_bytes': sum(size for _, size in responses),
            'provenance_file_count': len(files)}


def ensure_candidate_held(engine, release_id, reason):
    with engine.begin() as conn:
        row = conn.execute(text('SELECT status FROM area_pilot.release WHERE id=:id FOR UPDATE'),
                           {'id': release_id}).scalar_one()
        if row == 'ready':
            conn.execute(text('''UPDATE area_pilot.release SET status='held',
                report=jsonb_set(report,'{hold_reason}',to_jsonb(CAST(:reason AS text)))
                WHERE id=:id'''), {'id': release_id, 'reason': reason})


def full_product(engine, product, started):
    """Use the pinned adapters; never call their publication functions."""
    from app.area_pilot.cli import fetch_stage as fetch_county
    from app.area_pilot.tract import fetch_stage_tract
    from app.area_pilot.acs_cli import fetch_stage as fetch_acs, ROOT as ACS_ROOT
    disk_guard(ROOT, 2 * 1024**3)
    config = places_registry('tract') if product == 'places' else acs_registry()
    with engine.connect() as conn:
        active = conn.execute(text('''SELECT a.release_id,r.parent_county_release_id
            FROM area_pilot.active_release a JOIN area_pilot.release r ON r.id=a.release_id
            WHERE a.dataset_id=:dataset'''),
            {'dataset': config['dataset_id']}).mappings().one_or_none()
    if not active:
        return 'held', 'published_release_required', {}
    evidence = []
    if product == 'places':
        if not active['parent_county_release_id']:
            return 'held', 'combined_published_release_required', {}
        county_root = ROOT / 'places_county_2025'
        county_id, _ = fetch_county(engine, places_registry('county'), county_root)
        with engine.connect() as conn:
            county = conn.execute(text('SELECT status,report FROM area_pilot.release WHERE id=:id'),
                                  {'id': county_id}).mappings().one()
            evidence.append({'level': 'county', 'release_id': str(county_id),
                             **ingest_evidence(conn, county_id, started)})
        if county['status'] != 'published' or county_id != active['parent_county_release_id']:
            reason = county['report'].get('hold_reason') or 'county_content_differs_from_active_parent'
            ensure_candidate_held(engine, county_id, reason)
            return 'held', reason, {
                'ingest_evidence': evidence, 'candidate_id': str(county_id)}
        tract_id, _ = fetch_stage_tract(engine, config, ROOT / 'places_tract_2025')
        with engine.connect() as conn:
            tract = conn.execute(text('SELECT status,report FROM area_pilot.release WHERE id=:id'),
                                 {'id': tract_id}).mappings().one()
            evidence.append({'level': 'tract', 'release_id': str(tract_id),
                             **ingest_evidence(conn, tract_id, started)})
        if tract['status'] != 'published' or tract_id != active['release_id']:
            reason = tract['report'].get('hold_reason') or 'tract_content_differs_from_active_release'
            ensure_candidate_held(engine, tract_id, reason)
            return 'held', reason, {
                'ingest_evidence': evidence, 'candidate_id': str(tract_id)}
    else:
        candidate_id, _ = fetch_acs(engine, config, ACS_ROOT)
        with engine.connect() as conn:
            candidate = conn.execute(text('SELECT status,report FROM area_pilot.release WHERE id=:id'),
                                     {'id': candidate_id}).mappings().one()
            evidence.append({'release_id': str(candidate_id),
                             **ingest_evidence(conn, candidate_id, started)})
        if candidate['status'] != 'published' or candidate_id != active['release_id']:
            reason = candidate['report'].get('hold_reason') or 'acs_content_differs_from_active_release'
            ensure_candidate_held(engine, candidate_id, reason)
            return 'held', reason, {
                'ingest_evidence': evidence, 'candidate_id': str(candidate_id)}
    with engine.connect() as conn:
        current = conn.execute(text('SELECT release_id FROM area_pilot.active_release WHERE dataset_id=:dataset'),
                               {'dataset': config['dataset_id']}).scalar_one_or_none()
    if current != active['release_id']:
        return 'failed', 'active_pointer_changed_during_verification', {'ingest_evidence': evidence}
    return 'checked', 'identical_semantic_content_verified', {'ingest_evidence': evidence,
        'archived_response_count': sum(e['archived_response_count'] for e in evidence),
        'archived_response_bytes': sum(e['archived_response_bytes'] for e in evidence)}


def run_content_check(engine, product):
    config = places_registry('tract') if product == 'places' else acs_registry()
    dataset, run_id = config['dataset_id'], uuid.uuid4()
    with product_lock(product):
        started = datetime.now(timezone.utc)
        before_bytes = disk_usage()['archive_bytes']
        clock = time.monotonic()
        with engine.begin() as conn:
            conn.execute(text('''UPDATE area_pilot.source_check SET status='interrupted',
                reason='previous_process_ended_without_result',finished_at=now()
                WHERE dataset_id=:dataset AND status='running' '''), {'dataset': dataset})
            conn.execute(text('''INSERT INTO area_pilot.source_check
                (id,dataset_id,mode,status,reason,detail)
                VALUES (:id,:dataset,'content','running','started','{}'::jsonb)'''),
                {'id': run_id, 'dataset': dataset})
        log('content_check_started', product=product, run_id=run_id)
        try:
            status, reason, detail = full_product(engine, product, started)
        except Exception as exc:
            status = 'failed'
            reason = safe_failure_reason(exc)
            detail = {}
        detail |= {'duration_seconds': round(time.monotonic() - clock, 2),
                   'archive_growth_bytes': disk_usage()['archive_bytes'] - before_bytes,
                   'peak_process_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
        with engine.begin() as conn:
            conn.execute(text('''UPDATE area_pilot.source_check SET status=:status,reason=:reason,
                detail=CAST(:detail AS jsonb),finished_at=now() WHERE id=:id'''),
                {'id': run_id, 'status': status, 'reason': reason,
                 'detail': json.dumps(detail)})
        log('content_check_finished', product=product, run_id=run_id,
            status=status, reason=reason, duration_seconds=detail['duration_seconds'],
            archive_growth_bytes=detail['archive_growth_bytes'])
        return status


def release_reviewed_hold(engine, product, candidate_id, semantic, schema, metadata, note):
    """Operator acknowledges only a validated same-label statistical revision."""
    if not note.strip():
        raise ValueError('An operator review note is required')
    config = places_registry('tract') if product == 'places' else acs_registry()
    with product_lock(product):
        if product == 'acs':
            from app.area_pilot.acs_cli import review
            review(engine, candidate_id, config)
        else:
            from app.area_pilot.tract import review_source_db_sample
            with engine.connect() as conn:
                tract = conn.execute(text('''SELECT parent_county_release_id IS NOT NULL
                    FROM area_pilot.release WHERE id=:id'''), {'id': candidate_id}).scalar_one()
            if tract and not review_source_db_sample(engine, candidate_id, config).get('passed'):
                raise ValueError('Tract source and staging review failed')
        with engine.begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'),
                         {'dataset': config['dataset_id']})
            row = conn.execute(text('SELECT * FROM area_pilot.release WHERE id=:id FOR UPDATE'),
                               {'id': candidate_id}).mappings().one()
            if (row['dataset_id'] != config['dataset_id'] or row['status'] != 'held'
                    or row['report'].get('hold_reason') != 'same_label_semantic_revision'):
                raise ValueError('Only a same-label semantic revision hold can be released')
            if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (
                    semantic, schema, metadata):
                raise ValueError('Candidate checksums differ from reviewed values')
            checks = row['report'].get('checks', {})
            if not checks or not all(checks.values()):
                raise ValueError('Candidate has failed source checks')
            failed = conn.execute(text('''SELECT count(*) FROM area_pilot.validation
                WHERE release_id=:id AND NOT passed'''), {'id': candidate_id}).scalar_one()
            if failed:
                raise ValueError('Candidate has failed validation')
            conn.execute(text("UPDATE area_pilot.release SET status='ready' WHERE id=:id"),
                         {'id': candidate_id})
            conn.execute(text('''INSERT INTO area_pilot.run (id,release_id,action,status,detail)
                VALUES (:run,:id,'release-reviewed-hold','complete',CAST(:detail AS jsonb))'''),
                {'run': uuid.uuid4(), 'id': candidate_id,
                 'detail': json.dumps({'reason': 'same_label_semantic_revision', 'operator_note': note})})


def status_report(engine):
    report = {'generated_at': datetime.now(timezone.utc).isoformat(),
              'disk': disk_usage(), 'products': {}}
    with engine.connect() as conn:
        for product in PRODUCTS:
            config = places_registry('tract') if product == 'places' else acs_registry()
            dataset = config['dataset_id']
            active = conn.execute(text('''SELECT r.id,r.source_release_id,r.published_at
                FROM area_pilot.active_release a JOIN area_pilot.release r ON r.id=a.release_id
                WHERE a.dataset_id=:dataset'''), {'dataset': dataset}).mappings().one_or_none()
            latest = conn.execute(text('''SELECT id,mode,status,reason,started_at,finished_at,detail
                FROM area_pilot.source_check WHERE dataset_id=:dataset
                ORDER BY started_at DESC LIMIT 1'''), {'dataset': dataset}).mappings().one_or_none()
            success = conn.execute(text('''SELECT started_at,finished_at,reason FROM area_pilot.source_check
                WHERE dataset_id=:dataset AND mode='metadata' AND status='checked'
                ORDER BY started_at DESC LIMIT 1'''),
                {'dataset': dataset}).mappings().one_or_none()
            content_success = conn.execute(text('''SELECT started_at,finished_at,reason,detail
                FROM area_pilot.source_check WHERE dataset_id=:dataset AND mode='content'
                AND status='checked' ORDER BY started_at DESC LIMIT 1'''),
                {'dataset': dataset}).mappings().one_or_none()
            holds = conn.execute(text('''SELECT id,source_release_id,created_at,report FROM area_pilot.release
                WHERE dataset_id=:dataset AND status='held' ORDER BY created_at DESC LIMIT 10'''),
                {'dataset': dataset}).mappings().all()
            failures = conn.execute(text('''SELECT id,mode,status,reason,started_at FROM area_pilot.source_check
                WHERE dataset_id=:dataset AND status IN ('failed','interrupted')
                ORDER BY started_at DESC LIMIT 10'''), {'dataset': dataset}).mappings().all()
            ingest_holds = conn.execute(text('''SELECT run.id,run.release_id,run.status,run.created_at,
                r.report->>'hold_reason' AS reason FROM area_pilot.run run
                JOIN area_pilot.release r ON r.id=run.release_id
                WHERE r.dataset_id=:dataset AND run.action='fetch-stage-validate'
                AND run.status IN ('held','failed','interrupted')
                ORDER BY run.created_at DESC LIMIT 10'''), {'dataset': dataset}).mappings().all()
            publications = conn.execute(text('''SELECT r.id,r.published_at FROM area_pilot.release r
                WHERE r.dataset_id=:dataset AND r.status='published'
                ORDER BY r.published_at DESC LIMIT 1'''), {'dataset': dataset}).mappings().one_or_none()
            last_metadata_at = success['finished_at'] if success else None
            metadata_age_hours = ((datetime.now(timezone.utc) - last_metadata_at).total_seconds() / 3600
                                  if last_metadata_at else None)
            content_age_hours = ((datetime.now(timezone.utc) - content_success['finished_at']).total_seconds() / 3600
                                 if content_success else None)
            successful_times = [value for value in
                                (last_metadata_at, content_success['finished_at'] if content_success else None)
                                if value is not None]
            source_age_hours = ((datetime.now(timezone.utc) - max(successful_times)).total_seconds() / 3600
                                if successful_times else None)
            report['products'][product] = {
                'dataset_id': dataset, 'active_release': dict(active) if active else None,
                'refresh_policy': config['refresh_policy'],
                'observation_periods': sorted({m['observation_period'] for m in config['measures']}),
                'last_attempted_check': ({key: latest[key] for key in
                    ('id','mode','status','reason','started_at','finished_at')} if latest else None),
                'last_successful_metadata_check': dict(success) if success else None,
                'last_successful_source_check': dict(success) if success else None,
                'last_successful_full_content_verification': dict(content_success) if content_success else None,
                'content_verification_age_hours': round(content_age_hours, 1) if content_age_hours is not None else None,
                'metadata_check_age_hours': round(metadata_age_hours, 1) if metadata_age_hours is not None else None,
                'source_check_age_hours': round(source_age_hours, 1) if source_age_hours is not None else None,
                'refresh_health': 'never_verified' if content_age_hours is None else
                    ('verification_overdue' if content_age_hours > 14 * 24 else 'verification_current'),
                'last_successful_publication': dict(publications) if publications else None,
                'candidate_holds': [{'id': h['id'], 'source_release_id': h['source_release_id'],
                                     'created_at': h['created_at'],
                                     'reasons': h['report'].get('hold_reason') or
                                     [k for k, v in h['report'].get('checks', {}).items() if not v]}
                                    for h in holds],
                'failed_or_interrupted_checks': [dict(row) for row in failures]}
            report['products'][product]['held_or_failed_ingest_runs'] = [dict(row) for row in ingest_holds]
        report['staging_bytes'] = conn.execute(text('''SELECT sum(pg_total_relation_size(oid))
            FROM pg_class WHERE oid IN ('area_pilot.stage_county'::regclass,
            'area_pilot.stage_tract'::regclass,'area_pilot.stage_acs'::regclass)''')).scalar_one()
    return report


def disk_usage():
    ROOT.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(ROOT)
    archive = sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file())
    return {'archive_bytes': archive, 'available_bytes': usage.free,
            'total_bytes': usage.total, 'minimum_free_bytes': MIN_FREE_BYTES,
            'max_memory_bytes': 3 * 1024**3, 'max_runtime_seconds': 1800}


def retention_report(engine):
    with engine.connect() as conn:
        referenced = {Path(p).resolve() for p in conn.execute(text('SELECT path FROM area_pilot.source_file')).scalars()}
        dependencies = [dict(row) for row in conn.execute(text('''SELECT r.id,r.dataset_id,r.status,
            r.parent_county_release_id,a.release_id IS NOT NULL AS active
            FROM area_pilot.release r LEFT JOIN area_pilot.active_release a ON a.release_id=r.id
            ORDER BY r.created_at''')).mappings()]
    files = [{'path': str(p), 'bytes': p.stat().st_size} for p in ROOT.rglob('*') if p.is_file()
             and p.resolve() not in referenced and p.name not in ('ingest.lock','places_ingest.lock')]
    return {'dry_run': True, 'unreferenced_files_review_required': files,
            'unreferenced_bytes': sum(f['bytes'] for f in files),
            'protected_release_dependencies': dependencies,
            'note': 'No file is deleted. An unreferenced file may belong to an interrupted run.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('check', 'status', 'retention-report', 'release-reviewed-hold'))
    parser.add_argument('--product', choices=PRODUCTS)
    parser.add_argument('--mode', choices=('metadata','content'), default='metadata',
                        help='check mode; content retrieves all configured observations')
    parser.add_argument('--candidate-id', type=uuid.UUID)
    parser.add_argument('--semantic-sha256')
    parser.add_argument('--schema-sha256')
    parser.add_argument('--metadata-sha256')
    parser.add_argument('--operator-note')
    args = parser.parse_args()
    engine = create_engine(os.getenv('DATABASE_URL', DATABASE_URL), pool_pre_ping=True)
    if args.action == 'check':
        ROOT.mkdir(parents=True, exist_ok=True)
        with (ROOT / 'scheduler.lock').open('a') as scheduler_lock:
            fcntl.flock(scheduler_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            products = (args.product,) if args.product else PRODUCTS
            failed = False
            for product in products:
                try:
                    state = (run_check(engine, product) if args.mode == 'metadata'
                             else run_content_check(engine, product))
                    failed |= state != 'checked'
                except Exception as exc:
                    reason = 'product_lock_busy' if isinstance(exc, BlockingIOError) else type(exc).__name__
                    try:
                        record_unstarted_failure(engine, product, reason, args.mode)
                    except Exception:
                        log('source_check_unrecorded_failure', product=product, reason=reason)
                    else:
                        log('source_check_failed', product=product, reason=reason)
                    failed = True
            return 1 if failed else 0
    if args.action == 'release-reviewed-hold':
        if not all((args.product, args.candidate_id, args.semantic_sha256,
                    args.schema_sha256, args.metadata_sha256, args.operator_note)):
            parser.error('release-reviewed-hold requires product, candidate ID, three digests, and operator note')
        release_reviewed_hold(engine, args.product, args.candidate_id, args.semantic_sha256,
                              args.schema_sha256, args.metadata_sha256, args.operator_note)
        log('candidate_hold_released', product=args.product, candidate_id=args.candidate_id)
        return 0
    result = status_report(engine) if args.action == 'status' else retention_report(engine)
    print(json.dumps(result, default=str, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
