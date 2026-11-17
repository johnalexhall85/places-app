"""History candidate staging, review, checksum-bound publication, and pointer recovery.

One history release per product holds every earlier period. Its pointer is
'<current dataset_id>:history', so current pointers, tables, and profiles are never touched.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import Counter, defaultdict
from contextlib import nullcontext
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.area_pilot.acs_cli import file_rows
from app.area_pilot.history.fetch import HISTORY_ROOT, retrieve, sha256_file
from app.area_pilot.history.parsers import load_parser
from app.area_pilot.history.registry import public_config
from app.area_pilot.history.rows import HistoryRow, row_line, row_problems
from app.area_pilot.source import digest, same_label_revision

S = 'area_pilot'
BATCH = 5000
ROW_FIELDS = ['level', 'geoid', 'measure_id', 'period', 'population', 'value_type', 'value', 'status',
              'uncertainty_kind', 'low', 'high', 'moe', 'source_value', 'boundary_vintage']
INSERT = text(f'''INSERT INTO {S}.observation_history
    (release_id,part,level,geoid,measure_id,observation_period,population,value_type,value,status,
     uncertainty_kind,low,high,moe,source_value,boundary_vintage)
    VALUES (:release,:part,:level,:geoid,:measure,:period,:population,:type,:value,:status,
            :kind,:low,:high,:moe,:source,:vintage)''')


def schema_digest(schema_payload: dict) -> str:
    return digest(json.loads(json.dumps(schema_payload, default=str)))


class _Duplicate(Exception):
    def __init__(self, release_id, status):
        super().__init__(str(release_id))
        self.release_id, self.status = release_id, status


def boundary_keys(conn, level: str, vintage: str) -> set[str]:
    if level == 'state' or vintage == '2024':
        rows = conn.execute(text(f'SELECT geoid FROM {S}.acs_boundary_2024 WHERE level=:level'), {'level': level})
    else:
        rows = conn.execute(text(f'SELECT geoid FROM {S}.history_boundary WHERE vintage=:vintage AND level=:level'),
                            {'vintage': vintage, 'level': level})
    return {r[0] for r in rows}


def drop_unbounded_placeholders(conn, config, part, rows, boundaries, evidence_out) -> list[HistoryRow]:
    """Opt-in (registry ``drop_unbounded_blank_areas``): drop an area-period whose rows carry no value and
    whose GEOID has no boundary in its own vintage. Some publisher files keep blank placeholder rows for
    retired GEOIDs (old tract numbers, the other Connecticut geography). Areas with any value are kept."""
    if not config.get('drop_unbounded_blank_areas'):
        return rows
    has_value, keys = set(), {}
    for row in rows:
        area = (row.level, row.geoid, row.period)
        keys[area] = row.boundary_vintage
        if row.value is not None:
            has_value.add(area)
    drop = set()
    for (level, geoid, period), vintage in keys.items():
        if (level, geoid, period) in has_value:
            continue
        if (level, vintage) not in boundaries:
            boundaries[(level, vintage)] = boundary_keys(conn, level, vintage)
        if geoid not in boundaries[(level, vintage)]:
            drop.add((level, geoid, period))
    if drop:
        tally = evidence_out.setdefault('dropped_unbounded_blank_areas', {})
        for level, _, period in drop:
            name = f'{part}|{level}|{period}'
            tally[name] = tally.get(name, 0) + 1
    return [r for r in rows if (r.level, r.geoid, r.period) not in drop]


def summarize_part(rows: list[HistoryRow]) -> dict:
    """Digest and counts for one part. Rows are sorted once by key (C collation order)."""
    ordered = sorted(rows, key=lambda r: r.key)
    content, keys = hashlib.sha256(), hashlib.sha256()
    for row in ordered:
        content.update(row_line(row).encode('utf-8') + b'\n')
        keys.update('|'.join(row.key).encode('utf-8') + b'\n')
    return {'rows': len(ordered), 'sha256': content.hexdigest(), 'keyset_sha256': keys.hexdigest()}


def _db_part_digest(conn, release_id, part: str) -> tuple[int, str]:
    sha, count = hashlib.sha256(), 0
    result = conn.execute(text(f'''SELECT level,geoid,measure_id,
        observation_period,population,value_type,value,status,uncertainty_kind,low,high,moe,source_value,
        boundary_vintage FROM {S}.observation_history WHERE release_id=:id AND part=:part
        ORDER BY level COLLATE "C",geoid COLLATE "C",measure_id COLLATE "C",observation_period COLLATE "C"'''),
        {'id': release_id, 'part': part}, execution_options={'stream_results': True, 'yield_per': 5000})
    for record in result:
        sha.update(row_line(HistoryRow(*record)).encode('utf-8') + b'\n')
        count += 1
    return count, sha.hexdigest()


def _params(release_id, part, row: HistoryRow) -> dict:
    return {'release': release_id, 'part': part, 'level': row.level, 'geoid': row.geoid,
            'measure': row.measure_id, 'period': row.period, 'population': row.population,
            'type': row.value_type, 'value': row.value, 'status': row.status, 'kind': row.uncertainty_kind,
            'low': row.low, 'high': row.high, 'moe': row.moe, 'source': row.source_value,
            'vintage': row.boundary_vintage}


def declared(config: dict) -> set[tuple[str, str]]:
    return {(m['measure_id'], p['period']) for m in config['measures'] for p in m['periods']
            if p.get('available', True)}


def _hold(engine, config, run_id, candidate_id, reason, files):
    with engine.begin() as conn:
        conn.execute(text(f'''INSERT INTO {S}.release
            (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
             keyset_sha256,source_before,source_after,report)
            VALUES (:id,:dataset,:source,'held',:empty,:empty,:empty,:empty,'{{}}'::jsonb,'{{}}'::jsonb,
                    CAST(:report AS jsonb))'''),
            {'id': candidate_id, 'dataset': config['dataset_id'], 'source': config['source_release_id'],
             'empty': digest([]), 'report': json.dumps({'hold_reason': reason, 'files_retained': len(files)})})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'fetch-stage-validate','held',CAST(:detail AS jsonb))'''),
            {'run': run_id, 'id': candidate_id, 'detail': json.dumps({'error': reason})})
        conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
            VALUES (:id,'source_retrieval_and_parse',false,CAST(:detail AS jsonb))'''),
            {'id': candidate_id, 'detail': json.dumps({'error': reason})})
        file_rows(conn, run_id, candidate_id, files)
    return candidate_id, {'status': 'held', 'hold_reason': reason}


def _files_on_failure(run_dir: Path) -> list[dict]:
    from app.area_pilot.history.fetch import evidence
    if not run_dir.is_dir():
        return []
    return [evidence(p, f'partial:{p.name}', 'retained-on-failure') for p in sorted(run_dir.iterdir())
            if p.is_file() and not p.name.endswith('.part')]


def fetch_stage(engine, config, *, directory: Path | None = None, retrieved=None, census_key=None):
    """Retrieve, parse, validate, and stage one history candidate. ``retrieved`` is a test seam."""
    run_id, candidate_id = uuid.uuid4(), uuid.uuid4()
    run_dir = (directory or HISTORY_ROOT / config['product']) / str(run_id)
    started = time.monotonic()
    try:
        paths, files = retrieved(run_dir) if retrieved else retrieve(config, run_dir, census_key)
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        return _hold(engine, config, run_id, candidate_id, f'retrieval: {reason}', _files_on_failure(run_dir))
    parser = load_parser(config['parser'])
    try:
        with engine.begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
            conn.execute(text(f'''INSERT INTO {S}.release
                (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,metadata_sha256,
                 keyset_sha256,source_before,source_after,report)
                VALUES (:id,:dataset,:source,'held',:empty,:empty,:empty,:empty,'{{}}'::jsonb,'{{}}'::jsonb,'{{}}'::jsonb)'''),
                {'id': candidate_id, 'dataset': config['dataset_id'], 'source': config['source_release_id'],
                 'empty': digest([])})
            boundaries, evidence_out, parts = {}, {}, {}
            problems, coverage, statuses = Counter(), Counter(), Counter()
            unmatched, measure_levels = defaultdict(list), {m['measure_id']: set(m.get('levels', config['levels']))
                                                            for m in config['measures']}
            level_problems = []
            for part, rows in parser.parse(config, paths, evidence_out):
                if part in parts:
                    raise ValueError(f'Parser yielded part {part} twice')
                rows = drop_unbounded_placeholders(conn, config, part, rows, boundaries, evidence_out)
                for row in rows:
                    for issue in row_problems(row, config):
                        problems[issue] += 1
                    if row.level not in measure_levels.get(row.measure_id, set()):
                        level_problems.append([row.measure_id, row.level])
                    coverage[(row.measure_id, row.period, row.level)] += 1
                    statuses[(row.measure_id, row.period, row.status)] += 1
                    vintage_key = (row.level, row.boundary_vintage)
                    if vintage_key not in boundaries:
                        boundaries[vintage_key] = boundary_keys(conn, *vintage_key)
                    if row.geoid not in boundaries[vintage_key]:
                        unmatched[(row.level, row.boundary_vintage)].append(row.geoid)
                parts[part] = summarize_part(rows)
                for start in range(0, len(rows), BATCH):
                    conn.execute(INSERT, [_params(candidate_id, part, r) for r in rows[start:start + BATCH]])
                del rows
            seen_pairs = {(m, p) for m, p, _ in coverage}
            unmatched_counts = {f'{lvl}|{vin}': len(set(g)) for (lvl, vin), g in unmatched.items()}
            tolerance = config['unmatched_tolerance']
            checks = {
                'row_contract': not problems,
                'measure_levels': not level_problems,
                'registry_coverage': seen_pairs == declared(config),
                'boundary_match': all(len(set(g)) <= tolerance.get(lvl, 0) for (lvl, _), g in unmatched.items()),
                'parts_nonempty': bool(parts) and all(p['rows'] for p in parts.values()),
            }
            meta = public_config(config)
            schema_payload = {'parser': config['parser'], 'schema_version': parser.SCHEMA_VERSION,
                              'row_fields': ROW_FIELDS, 'evidence': evidence_out}
            semantic = digest(sorted([name, p['sha256'], p['rows']] for name, p in parts.items()))
            keyset = digest(sorted([name, p['keyset_sha256'], p['rows']] for name, p in parts.items()))
            schema, metadata = schema_digest(schema_payload), digest(meta)
            existing = conn.execute(text(f'''SELECT id,status FROM {S}.release WHERE dataset_id=:dataset
                AND id<>:id AND semantic_sha256=:semantic AND schema_sha256=:schema AND metadata_sha256=:metadata
                AND keyset_sha256=:keyset AND status IN ('ready','published') ORDER BY created_at LIMIT 1'''),
                {'dataset': config['dataset_id'], 'id': candidate_id, 'semantic': semantic, 'schema': schema,
                 'metadata': metadata, 'keyset': keyset}).mappings().one_or_none()
            if existing and all(checks.values()):
                raise _Duplicate(existing['id'], existing['status'])
            prior = conn.execute(text(f'''SELECT r.source_release_id,r.semantic_sha256 FROM {S}.active_release a
                JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
                {'dataset': config['dataset_id']}).mappings().one_or_none()
            revision_hold = same_label_revision(prior, config['source_release_id'], semantic)
            status = 'ready' if all(checks.values()) and not revision_hold else 'held'
            hold_reason = ('validation_failed' if not all(checks.values()) else
                           'same_label_semantic_revision' if revision_hold else None)
            report = {
                'checks': checks, 'hold_reason': hold_reason, 'parts': parts,
                'observation_count': sum(p['rows'] for p in parts.values()),
                'coverage': {f'{m}|{p}|{lvl}': n for (m, p, lvl), n in sorted(coverage.items())},
                'status_counts': {f'{m}|{p}|{s}': n for (m, p, s), n in sorted(statuses.items())},
                'missing_pairs': sorted(map(list, declared(config) - seen_pairs)),
                'undeclared_pairs': sorted(map(list, seen_pairs - declared(config))),
                'row_problems': dict(problems), 'measure_level_problems': level_problems[:50],
                'unmatched_boundary': unmatched_counts,
                'unmatched_boundary_sample': {f'{lvl}|{vin}': sorted(set(g))[:50] for (lvl, vin), g in unmatched.items()},
                'schema_payload': schema_payload, 'metadata_payload': meta,
                'period_rule': 'observation year or ACS window; one value per data year, newest release wins',
            }
            conn.execute(text(f'''UPDATE {S}.release SET status=:status,semantic_sha256=:semantic,
                schema_sha256=:schema,metadata_sha256=:metadata,keyset_sha256=:keyset,
                source_before=CAST(:before AS jsonb),report=CAST(:report AS jsonb) WHERE id=:id'''),
                {'id': candidate_id, 'status': status, 'semantic': semantic, 'schema': schema,
                 'metadata': metadata, 'keyset': keyset, 'before': json.dumps(dict(prior) if prior else {}),
                 'report': json.dumps(report, default=str)})
            conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
                VALUES (:run,:id,'fetch-stage-validate',:status,CAST(:detail AS jsonb))'''),
                {'run': run_id, 'id': candidate_id, 'status': status,
                 'detail': json.dumps({'archive_files': len(files), 'parts': len(parts)})})
            file_rows(conn, run_id, candidate_id, files)
            for name, passed in checks.items():
                conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
                    VALUES (:id,:name,:passed,CAST(:detail AS jsonb))'''),
                    {'id': candidate_id, 'name': name, 'passed': passed, 'detail': json.dumps(
                        {'missing': report['missing_pairs'], 'undeclared': report['undeclared_pairs']}
                        if name == 'registry_coverage' else
                        {'unmatched': unmatched_counts, 'tolerance': tolerance} if name == 'boundary_match' else
                        {'problems': dict(problems)} if name == 'row_contract' else {})})
    except _Duplicate as dup:
        with engine.begin() as conn:
            conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
                VALUES (:run,:id,'fetch-stage-validate','duplicate',CAST(:detail AS jsonb))'''),
                {'run': run_id, 'id': dup.release_id, 'detail': json.dumps({'same_semantic_content': True})})
            file_rows(conn, run_id, dup.release_id, files)
        return dup.release_id, {'status': 'duplicate', 'existing_status': dup.status}
    except IntegrityError:
        return _hold(engine, config, run_id, candidate_id, 'duplicate (level, geoid, measure, period) rows', files)
    except (ValueError, KeyError) as exc:
        return _hold(engine, config, run_id, candidate_id, f'parse: {exc}', files)
    return candidate_id, report | {'status': status, 'semantic_sha256': semantic, 'schema_sha256': schema,
                                   'metadata_sha256': metadata, 'keyset_sha256': keyset,
                                   'duration_seconds': round(time.monotonic() - started, 2)}


def review(engine, candidate_id, config, connection=None, verify_files=True):
    """Re-verify archive checksums, re-parse them, and compare every stored row part by part."""
    with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
        row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                           {'id': candidate_id, 'dataset': config['dataset_id']}).mappings().one()
        if row['status'] not in ('ready', 'published', 'held') or not row['report'].get('parts'):
            raise ValueError('History candidate has no staged content to review')
        report = row['report']
        if digest(public_config(config)) != row['metadata_sha256'] or report['metadata_payload'] != public_config(config):
            raise ValueError('History registry changed since this candidate was staged')
        files = conn.execute(text(f'''SELECT role,path,sha256 FROM {S}.source_file WHERE release_id=:id
            ORDER BY retrieved_at'''), {'id': candidate_id}).mappings().all()
        paths = {}
        for item in files:
            if verify_files and (not Path(item['path']).is_file() or sha256_file(Path(item['path'])) != item['sha256']):
                raise ValueError(f'History archived source checksum mismatch: {item["role"]}')
            paths[item['role']] = Path(item['path'])
        parser = load_parser(config['parser'])
        evidence_out, seen, boundaries = {}, set(), {}
        for part, rows in parser.parse(config, paths, evidence_out):
            rows = drop_unbounded_placeholders(conn, config, part, rows, boundaries, evidence_out)
            expected = report['parts'].get(part)
            summary = summarize_part(rows)
            if expected is None or summary['sha256'] != expected['sha256'] or summary['rows'] != expected['rows']:
                raise ValueError(f'History part {part} differs from the archived source')
            count, stored = _db_part_digest(conn, candidate_id, part)
            if (count, stored) != (expected['rows'], expected['sha256']):
                raise ValueError(f'History part {part} stored rows differ from the reviewed checksum')
            seen.add(part)
        if seen != set(report['parts']):
            raise ValueError('History parts differ from the staged candidate')
        schema_payload = {'parser': config['parser'], 'schema_version': parser.SCHEMA_VERSION,
                          'row_fields': ROW_FIELDS, 'evidence': evidence_out}
        if schema_digest(schema_payload) != row['schema_sha256']:
            raise ValueError('History parser or source schema changed since staging')
        samples = conn.execute(text(f'''SELECT measure_id,observation_period,level,geoid,value,status,source_value
            FROM {S}.observation_history WHERE release_id=:id ORDER BY md5(level||geoid||measure_id||observation_period)
            LIMIT 12'''), {'id': candidate_id}).mappings().all()
        return {'candidate_id': str(candidate_id), 'status': row['status'],
                'semantic_sha256': row['semantic_sha256'], 'schema_sha256': row['schema_sha256'],
                'metadata_sha256': row['metadata_sha256'], 'keyset_sha256': row['keyset_sha256'],
                'archive_files_verified': len(files), 'parts_verified': len(seen),
                'observations_verified': report['observation_count'],
                'representative_cells': [dict(s) for s in samples], 'report': report}


def _bound(conn, config, candidate_id, statuses):
    conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
    row = conn.execute(text(f'SELECT * FROM {S}.release WHERE id=:id FOR UPDATE'), {'id': candidate_id}).mappings().one()
    if row['dataset_id'] != config['dataset_id'] or row['status'] not in statuses:
        raise ValueError('History candidate is not in an eligible state')
    return row


def publish(engine, config, candidate_id, semantic, schema, metadata, verify_files=True):
    with engine.begin() as conn:
        row = _bound(conn, config, candidate_id, ('ready',))
        if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (semantic, schema, metadata):
            raise ValueError('History candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('History candidate has failed checks')
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
        raise ValueError('Operator review note is required')
    with engine.begin() as conn:
        row = _bound(conn, config, candidate_id, ('held',))
        if row['report'].get('hold_reason') != 'same_label_semantic_revision':
            raise ValueError('History candidate is not an eligible same-label revision hold')
        if (row['semantic_sha256'], row['schema_sha256'], row['metadata_sha256']) != (semantic, schema, metadata):
            raise ValueError('History held candidate differs from reviewed checksums')
        if conn.execute(text(f'SELECT count(*) FROM {S}.validation WHERE release_id=:id AND NOT passed'),
                        {'id': candidate_id}).scalar_one():
            raise ValueError('History held candidate has failed checks')
        review(engine, candidate_id, config, connection=conn, verify_files=verify_files)
        conn.execute(text(f'''UPDATE {S}.release SET status='ready',
            report=jsonb_set(report,'{{hold_reason}}','null'::jsonb) WHERE id=:id'''), {'id': candidate_id})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail)
            VALUES (:run,:id,'release-reviewed-hold','complete',CAST(:detail AS jsonb))'''),
            {'run': uuid.uuid4(), 'id': candidate_id, 'detail': json.dumps({'operator_note': note})})


def set_pointer(engine, config, action, release_id=None):
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        if action == 'rollback':
            status = conn.execute(text(f'SELECT status FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                                  {'id': release_id, 'dataset': config['dataset_id']}).scalar_one_or_none()
            if status != 'published':
                raise ValueError('History rollback target must be a retained published release')
            conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:dataset,:id)
                ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
                {'dataset': config['dataset_id'], 'id': release_id})
        elif action == 'deactivate':
            conn.execute(text(f'DELETE FROM {S}.active_release WHERE dataset_id=:dataset'),
                         {'dataset': config['dataset_id']})
        else:
            raise ValueError(f'Unknown pointer action {action}')
