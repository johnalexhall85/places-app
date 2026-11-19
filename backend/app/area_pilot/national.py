"""National reference values that a source itself publishes, for every period CHIP holds.

- ACS 5-year U.S. values (`for=us:1`) for B19013 and the community subject-table measures, one call per
  vintage, with the same variables the current and history registries declare.
- CMS OM GV national rows: the current year from the active CMS release, earlier years from the archived
  history file through `parsers.cms_gv.parse_national`.

Nothing is derived from states or counties. Rows go to `area_pilot.observation_national` under the
dataset pointer `chip_national_reference`, read only through `lookup.national_series`.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import requests
from sqlalchemy import text

from app.area_pilot import acs, acs_profile, cms_gv
from app.area_pilot.history.fetch import INGEST_ROOT, sha256_file
from app.area_pilot.history.registry import load_history_registry
from app.area_pilot.source import digest

S = 'area_pilot'
DATASET_ID = 'chip_national_reference'
SOURCE_RELEASE_ID = 'ACS 5-year U.S. (Census Data API) and CMS OM GV national rows'
ARCHIVE = INGEST_ROOT / 'national'
ACS_URL = {'acs': 'https://api.census.gov/data/{v}/acs/acs5', 'acs_profile': 'https://api.census.gov/data/{v}/acs/acs5/subject'}
NULL_STATUSES = {'missing', 'suppressed', 'not_applicable'}


def _vintage(period: str) -> str:
    return period[-4:]


def acs_plan(product: str) -> dict[str, list[dict]]:
    """{vintage: [{'measure', 'period', 'variable', 'population', 'value_type'}]} for every published period."""
    current = (acs.load_registry() if product == 'acs' else acs_profile.load_registry())
    history = load_history_registry(product)
    hmeasures = {m['measure_id']: m for m in history['measures']}
    plan: dict[str, list[dict]] = {}
    for measure in current['measures']:
        mid = measure['measure_id']
        variable = measure.get('variable', 'B19013_001')
        period = measure.get('observation_period', current.get('observation_period'))
        hm = hmeasures.get(mid, {})
        entries = [{'period': period, 'variable': variable,
                    'population': measure.get('population', hm.get('population')),
                    'value_type': measure.get('value_type', current.get('value_type', hm.get('value_type')))}]
        for p in hm.get('periods', []):
            if not p.get('available', True):
                continue
            if _vintage(p['period']) != p['locator']['vintage']:
                raise ValueError(f'{product}:{mid} {p["period"]} locator vintage {p["locator"]["vintage"]} differs')
            entries.append({'period': p['period'], 'variable': p['locator'].get('variable', variable),
                            'population': p.get('population', hm['population']), 'value_type': hm['value_type']})
        for e in entries:
            plan.setdefault(_vintage(e['period']), []).append(e | {'measure': measure})
    return dict(sorted(plan.items()))


def _fields(entries):
    return ['NAME'] + [e['variable'] + s for e in entries for s in ('E', 'M', 'EA', 'MA')]


def fetch_acs(product: str, run_dir: Path, census_key: str | None, session=None) -> list[dict]:
    """Download one U.S. row per vintage, archive the response, and return file records."""
    session = session or requests.Session()
    files = []
    for vintage, entries in acs_plan(product).items():
        url = ACS_URL[product].format(v=vintage)
        params = {'get': ','.join(_fields(entries)), 'for': 'us:1'}
        response = session.get(url, params=params | ({'key': census_key} if census_key else {}), timeout=60,
                               headers={'User-Agent': 'CHIP-area-pilot/1.0'})
        response.raise_for_status()
        path = run_dir / f'{product}_{vintage}_us.json'
        path.write_bytes(response.content)
        files.append({'role': f'{product}_{vintage}_us', 'path': path, 'vintage': vintage,
                      'url': response.url.replace(census_key, '<key>') if census_key else response.url})
    return files


def parse_acs(product: str, vintage: str, payload: list) -> list[dict]:
    entries = acs_plan(product)[vintage]
    header, *rows = payload
    if len(rows) != 1:
        raise ValueError(f'{product} {vintage}: expected one U.S. row, got {len(rows)}')
    row = dict(zip(header, rows[0]))
    if row.get('us') != '1':
        raise ValueError(f'{product} {vintage}: response is not the U.S. row')
    missing = [f for f in _fields(entries) if f not in row]
    if missing:
        raise ValueError(f'{product} {vintage}: response lacks {missing}')
    out = []
    for e in entries:
        measure, var = e['measure'], e['variable']
        if product == 'acs':
            mapped = {f'B19013_001{s}': row[var + s] for s in ('E', 'M', 'EA', 'MA')}
            parsed = acs.parse_observation(mapped)
        else:
            own = measure['variable']
            mapped = {own + s: row[var + s] for s in ('E', 'M', 'EA', 'MA')}
            parsed = acs_profile.parse_observation(mapped, measure)
        out.append({'product': product, 'measure_id': measure['measure_id'], 'observation_period': e['period'],
                    'population': e['population'], 'value_type': e['value_type'], 'value': parsed['value'],
                    'status': parsed['status'], 'uncertainty_kind': 'moe90', 'low': None, 'high': None,
                    'moe': parsed['moe'], 'source_value': row[var + 'E'] or '',
                    'source_role': f'{product}_{vintage}_us'})
    return out


def cms_rows(conn) -> list[dict]:
    """CMS national rows: current year from the active CMS release, earlier years from the archived file."""
    from app.area_pilot.history.parsers import cms_gv as parser
    current = cms_gv.load_registry()
    history = load_history_registry('cms_gv')
    release = conn.execute(text(f'''SELECT a.release_id FROM {S}.active_release a JOIN {S}.release r ON r.id=a.release_id
        WHERE a.dataset_id=:d AND r.status='published' '''), {'d': current['dataset_id']}).scalar_one()
    out = []
    for r in conn.execute(text(f'''SELECT measure_id,observation_period,population,value_type,value,status,source_value
        FROM {S}.observation_cms_gv WHERE release_id=:r AND geo_level='national' AND geoid='US' '''), {'r': release}).mappings():
        out.append(dict(r) | {'product': 'cms_gv', 'uncertainty_kind': 'none', 'low': None, 'high': None, 'moe': None,
                              'source_value': r['source_value'] or '', 'source_role': 'cms_gv_current_release'})
    source = history['sources'][0]
    path = (INGEST_ROOT / source['archived_path']).resolve()
    if sha256_file(path) != source['sha256']:
        raise ValueError('Archived CMS history file checksum differs from the registry')
    hm = {m['measure_id']: m for m in history['measures']}
    evidence: dict = {}
    for r in parser.parse_national(history, {source['role']: path}, evidence):
        m = hm[r['measure_id']]
        period = next(p for p in m['periods'] if p['period'] == r['period'])
        out.append({'product': 'cms_gv', 'measure_id': r['measure_id'], 'observation_period': r['period'],
                    'population': period.get('population', m['population']), 'value_type': m['value_type'],
                    'value': r['value'], 'status': r['status'], 'uncertainty_kind': 'none', 'low': None, 'high': None,
                    'moe': None, 'source_value': r.get('source_value') or '', 'source_role': 'cms_gv_history_archive'})
    return out


def _line(row: dict) -> str:
    return json.dumps({k: (str(v) if isinstance(v, Decimal) else v) for k, v in sorted(row.items())}, sort_keys=True)


def checks(rows: list[dict]) -> list[tuple[str, bool, dict]]:
    keys = [(r['product'], r['measure_id'], r['observation_period']) for r in rows]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    bad_null = [k for r, k in zip(rows, keys) if r['value'] is None and r['status'] not in NULL_STATUSES]
    bad_pct = [k for r, k in zip(rows, keys) if r['value'] is not None and r['measure_id'].endswith('_pct') and r['value'] > 100]
    expected = {(p, m['measure']['measure_id'], m['period']) for p in ('acs', 'acs_profile')
                for es in acs_plan(p).values() for m in es}
    missing = sorted(expected - {k for k in keys if k[0] != 'cms_gv'})
    return [('unique_keys', not dupes, {'duplicates': dupes}),
            ('null_only_with_status', not bad_null, {'rows': bad_null}),
            ('percent_at_most_100', not bad_pct, {'rows': bad_pct}),
            ('every_acs_period_present', not missing, {'missing': missing}),
            ('cms_years_present', len({k[2] for k in keys if k[0] == 'cms_gv'}) >= 6, {})]


def build(engine, census_key: str | None, session=None) -> dict:
    """Fetch, parse, validate, and stage a release with status 'ready'. Never moves the pointer."""
    release_id, run_id = uuid.uuid4(), uuid.uuid4()
    run_dir = ARCHIVE / str(release_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    files = [f for p in ('acs', 'acs_profile') for f in fetch_acs(p, run_dir, census_key, session)]
    rows = []
    for f in files:
        rows += parse_acs(f['role'].rsplit('_', 2)[0], f['vintage'], json.loads(f['path'].read_text()))
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:d))'), {'d': DATASET_ID})
        rows += cms_rows(conn)
        rows.sort(key=lambda r: (r['product'], r['measure_id'], r['observation_period']))
        results = checks(rows)
        passed = all(ok for _, ok, _ in results)
        semantic = digest([_line(r) for r in rows])
        conn.execute(text(f'''INSERT INTO {S}.release (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,
            metadata_sha256,keyset_sha256,source_before,source_after,report) VALUES (:id,:d,:src,:status,:sem,:schema,:meta,
            :keys,'{{}}'::jsonb,'{{}}'::jsonb,CAST(:report AS jsonb))'''),
            {'id': release_id, 'd': DATASET_ID, 'src': SOURCE_RELEASE_ID, 'status': 'ready' if passed else 'held',
             'sem': semantic, 'schema': digest(['observation_national:1']), 'meta': digest([SOURCE_RELEASE_ID]),
             'keys': digest(sorted(f'{r["product"]}:{r["measure_id"]}:{r["observation_period"]}' for r in rows)),
             'report': json.dumps({'rows': len(rows), 'files': len(files)})})
        conn.execute(text(f'''INSERT INTO {S}.run (id,release_id,action,status,detail) VALUES
            (:run,:id,'national-build',:status,'{{}}'::jsonb)'''),
            {'run': run_id, 'id': release_id, 'status': 'complete' if passed else 'held'})
        now = datetime.now(timezone.utc)
        for f in files:
            conn.execute(text(f'''INSERT INTO {S}.source_file (id,run_id,release_id,role,path,url,sha256,byte_count,retrieved_at)
                VALUES (:id,:run,:rel,:role,:path,:url,:sha,:bytes,:at)'''),
                {'id': uuid.uuid4(), 'run': run_id, 'rel': release_id, 'role': f['role'],
                 'path': str(f['path'].relative_to(INGEST_ROOT)), 'url': f['url'], 'sha': sha256_file(f['path']),
                 'bytes': f['path'].stat().st_size, 'at': now})
        for name, ok, detail in results:
            conn.execute(text(f'''INSERT INTO {S}.validation (release_id,check_name,passed,detail)
                VALUES (:id,:n,:ok,CAST(:d AS jsonb))'''), {'id': release_id, 'n': name, 'ok': ok, 'd': json.dumps(detail)})
        for r in rows:
            conn.execute(text(f'''INSERT INTO {S}.observation_national (release_id,product,measure_id,observation_period,
                geoid,population,value_type,value,status,uncertainty_kind,low,high,moe,source_value,source_role)
                VALUES (:id,:product,:measure_id,:observation_period,'US',:population,:value_type,:value,:status,
                :uncertainty_kind,:low,:high,:moe,:source_value,:source_role)'''), r | {'id': release_id})
    return {'release_id': str(release_id), 'status': 'ready' if passed else 'held', 'rows': len(rows),
            'semantic_sha256': semantic, 'checks': {n: ok for n, ok, _ in results}}


def publish(engine, release_id: str, semantic: str) -> None:
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:d))'), {'d': DATASET_ID})
        row = conn.execute(text(f'SELECT status,semantic_sha256 FROM {S}.release WHERE id=:id AND dataset_id=:d'),
                           {'id': release_id, 'd': DATASET_ID}).mappings().one()
        if row['status'] != 'ready' or row['semantic_sha256'] != semantic:
            raise ValueError('National release is not ready or differs from the reviewed checksum')
        conn.execute(text(f"UPDATE {S}.release SET status='published',published_at=now() WHERE id=:id"), {'id': release_id})
        conn.execute(text(f'''INSERT INTO {S}.active_release (dataset_id,release_id) VALUES (:d,:id)
            ON CONFLICT (dataset_id) DO UPDATE SET release_id=excluded.release_id,updated_at=now()'''),
            {'d': DATASET_ID, 'id': release_id})
