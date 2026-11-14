"""Release-pinned, read-only HRSA health center site overlay API; public URL /api/area/sites via nginx.

Map, table, and detail requests share one WHERE clause (``site_where``): an explicit published
release, eligible site status, mapped location, the selected classification codes, and a required
bounding box. The map returns individual points only when the viewport holds at most
``point_cap`` eligible sites at zoom >= ``point_min_zoom``; otherwise it returns grid clusters
whose counts sum exactly to the same total the table reports. Nothing is truncated silently: a
request that would exceed a cap returns 413.
"""
from __future__ import annotations

import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.area_pilot.hrsa_sites import load_registry
from app.area_pilot.router import bounds
from app.db import get_db

router = APIRouter(prefix='/area/sites', tags=['area-sites'])
S = 'area_pilot'
FILTERS = ('program', 'site_type', 'location_type', 'setting')
EARTH_CIRCUMFERENCE_M = 2 * math.pi * 6378137
SITE_WHERE = f'''FROM {S}.site_hrsa s
WHERE s.release_id=:release AND s.location_status='mapped' AND s.eligible
 AND s.program_code = ANY(:program) AND s.site_type_code = ANY(:site_type)
 AND s.location_type_code = ANY(:location_type) AND s.setting_code = ANY(:setting)
 AND s.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)'''
SUMMARY = '''s.site_id,s.site_name,s.organization_name,s.health_center_number,s.program_code,s.site_type_code,
 s.location_type_code,s.setting_code,s.city,s.state_abbr,s.source_x,s.source_y,ST_X(s.geom) AS lon,ST_Y(s.geom) AS lat'''


def labels(config):
    return {name: {v['code']: v['label'] for v in block['values']} for name, block in config['classifications'].items()}


def parse_filters(config, raw):
    """``None`` selects the registry defaults; an explicit empty selection is rejected."""
    result = {}
    for name in FILTERS:
        block = config['classifications'][name]
        allowed = {v['code'] for v in block['values'] if not v.get('location_suppressed')}
        value = raw.get(name)
        if value is None:
            codes = sorted(v['code'] for v in block['values'] if v['default'] and not v.get('location_suppressed'))
        else:
            codes = sorted({part.strip() for part in value.split(',') if part.strip()})
            if not codes:
                raise HTTPException(400, f'Select at least one {block["label"].lower()} value')
            unknown = sorted(set(codes) - allowed)
            if unknown:
                raise HTTPException(400, f'Unknown or unmappable {name} value(s): {", ".join(unknown)}')
        result[name] = codes
    return result


def published_release(db, config, release_id):
    row = db.execute(text(f'''SELECT status,source_release_id,source_after->>'snapshot_date' AS snapshot_date
        FROM {S}.release WHERE id=:release AND dataset_id=:dataset'''),
        {'release': release_id, 'dataset': config['dataset_id']}).mappings().one_or_none()
    if not row or row['status'] != 'published':
        raise HTTPException(404, 'Published HRSA site release not found')
    return row


def query_params(release_id, bbox, filters):
    return {'release': release_id, **bounds(bbox), **filters}


def base(config, release, release_id, bbox, filters):
    return {'dataset_id': config['dataset_id'], 'release_id': str(release_id),
            'source_release_id': release['source_release_id'], 'snapshot_date': release['snapshot_date'],
            'bbox': bbox, 'filters': filters, 'crs': config['location_policy']['crs']}


def count_sites(db, p):
    return db.execute(text('SELECT count(*) ' + SITE_WHERE), p).scalar_one()


def summary_row(r, names):
    return {'site_id': r['site_id'], 'site_name': r['site_name'], 'organization_name': r['organization_name'],
            'health_center_number': r['health_center_number'],
            'program': r['program_code'], 'program_label': names['program'][r['program_code']],
            'site_type': r['site_type_code'], 'site_type_label': names['site_type'][r['site_type_code']],
            'location_type': r['location_type_code'], 'location_type_label': names['location_type'][r['location_type_code']],
            'setting': r['setting_code'], 'setting_label': names['setting'][r['setting_code']],
            'city': r['city'], 'state': r['state_abbr'], 'lon': r['lon'], 'lat': r['lat'],
            'location_key': f"{r['source_x']},{r['source_y']}"}


def cluster_cell_m(zoom, cell_px):
    return EARTH_CIRCUMFERENCE_M / (256 * 2 ** zoom) * cell_px


def catalog_payload(db, config):
    active = db.execute(text(f'''SELECT a.release_id FROM {S}.active_release a JOIN {S}.release r ON r.id=a.release_id
        WHERE a.dataset_id=:dataset AND r.status='published' '''), {'dataset': config['dataset_id']}).scalar_one_or_none()
    releases = db.execute(text(f'''SELECT id,source_release_id,source_after->>'snapshot_date' AS snapshot_date,
            report->>'retrieved_at' AS retrieved_at,semantic_sha256,schema_sha256,metadata_sha256,published_at
        FROM {S}.release WHERE dataset_id=:dataset AND status='published' ORDER BY published_at DESC'''),
        {'dataset': config['dataset_id']}).mappings().all()
    names = labels(config)
    payload = {key: config[key] for key in ('dataset_id', 'name', 'publisher', 'landing_page', 'download_page',
                                            'product_kind', 'usage_terms', 'limitations')}
    payload |= {'source_url': config['download_page'], 'boundary_vintage': config['boundary']['vintage'],
                'coordinate_reference': {k: config['location_policy'][k] for k in ('crs', 'crs_basis', 'source_quality_fields')},
                'location_rules': config['location_policy']['rules'], 'location_never': config['location_policy']['never'],
                'clustering': config['clustering'], 'observation_period': None,
                'period_note': 'Current directory snapshot; no annual observation period applies.',
                'active_release_id': str(active) if active else None,
                'published_releases': [{**dict(r), 'id': str(r['id'])} for r in releases]}
    counts = {}
    if active:
        status_rows = db.execute(text(f'''SELECT location_status,eligible,count(*) AS n FROM {S}.site_hrsa
            WHERE release_id=:release GROUP BY 1,2 ORDER BY 1,2'''), {'release': active}).mappings().all()
        option_rows = {name: dict(db.execute(text(f'''SELECT {name}_code,count(*) FROM {S}.site_hrsa
            WHERE release_id=:release AND location_status='mapped' AND eligible GROUP BY 1'''), {'release': active}).all())
            for name in FILTERS}
        last_confirmed = db.execute(text(f'''SELECT max(detail->>'confirmed_snapshot_date') FROM {S}.run
            WHERE release_id=:release AND action='fetch-stage-validate' AND status='duplicate' '''),
            {'release': active}).scalar_one_or_none()
        default_filters = parse_filters(config, {})
        default_mapped = count_sites(db, query_params(active, '-180,-90,180,90', default_filters))
        by_status = {}
        for r in status_rows:
            by_status[r['location_status']] = by_status.get(r['location_status'], 0) + r['n']
        counts = {'source_sites': sum(r['n'] for r in status_rows),
                  'eligible_status_sites': sum(r['n'] for r in status_rows if r['eligible']),
                  'mapped_eligible_sites': sum(r['n'] for r in status_rows if r['eligible'] and r['location_status'] == 'mapped'),
                  'default_filter_mapped_sites': default_mapped,
                  'not_mapped_by_reason': {k: v for k, v in sorted(by_status.items()) if k != 'mapped'},
                  'last_confirmed_snapshot_date': last_confirmed}
        payload['filters'] = [{'name': name, 'label': config['classifications'][name]['label'], 'values': [
            {'code': v['code'], 'label': v['label'], 'default': v['default'], 'mapped_sites': option_rows[name].get(v['code'], 0)}
            for v in config['classifications'][name]['values'] if not v.get('location_suppressed')]} for name in FILTERS]
        active_release = next((r for r in releases if str(r['id']) == str(active)), None)
        payload['snapshot_date'] = active_release['snapshot_date'] if active_release else None
        payload['retrieved_at'] = active_release['retrieved_at'] if active_release else None
    payload['counts'] = counts
    payload['labels'] = names
    return payload


@router.get('/catalog')
def catalog(db: Session = Depends(get_db)):
    return catalog_payload(db, load_registry())


def map_payload(db, config, release_id, bbox, zoom, filters):
    release = published_release(db, config, release_id)
    p = query_params(release_id, bbox, filters)
    clustering = config['clustering']
    total = count_sites(db, p)
    result = base(config, release, release_id, bbox, filters) | {
        'zoom': zoom, 'total': total, 'complete': True, 'point_cap': clustering['point_cap'],
        'point_min_zoom': clustering['point_min_zoom'], 'cluster_note': clustering['note']}
    names = labels(config)
    if zoom >= clustering['point_min_zoom'] and total <= clustering['point_cap']:
        rows = db.execute(text(f'SELECT {SUMMARY} {SITE_WHERE} ORDER BY s.site_id LIMIT :cap'),
                          p | {'cap': clustering['point_cap'] + 1}).mappings().all()
        if len(rows) != total:
            raise HTTPException(409, 'Site count changed during retrieval; retry the request')
        return result | {'mode': 'points', 'points': [summary_row(r, names) for r in rows], 'clusters': [],
                         'message': None}
    cell = cluster_cell_m(zoom, clustering['cluster_cell_px'])
    rows = db.execute(text(f'''SELECT floor(ST_X(t.m)/:cell)::bigint AS gx, floor(ST_Y(t.m)/:cell)::bigint AS gy,
            count(*) AS n, avg(t.lon) AS lon, avg(t.lat) AS lat, min(t.lon) AS west, min(t.lat) AS south,
            max(t.lon) AS east, max(t.lat) AS north, count(DISTINCT t.location_key) AS locations
        FROM (SELECT ST_Transform(s.geom,3857) AS m, ST_X(s.geom) AS lon, ST_Y(s.geom) AS lat,
                     s.source_x || ',' || s.source_y AS location_key {SITE_WHERE}) t
        GROUP BY 1,2 ORDER BY 1,2 LIMIT :cap'''), p | {'cell': cell, 'cap': clustering['cluster_cap'] + 1}).mappings().all()
    if len(rows) > clustering['cluster_cap']:
        raise HTTPException(413, f'Viewport would need more than {clustering["cluster_cap"]} clusters at this zoom. '
                                 'Zoom in or narrow the viewport.')
    clusters = [{'id': f'{zoom}:{r["gx"]}:{r["gy"]}', 'count': r['n'], 'lon': float(r['lon']), 'lat': float(r['lat']),
                 'bounds': [float(r['west']), float(r['south']), float(r['east']), float(r['north'])],
                 'distinct_locations': r['locations']} for r in rows]
    if sum(c['count'] for c in clusters) != total:
        raise HTTPException(409, 'Cluster counts differ from the site total; retry the request')
    message = (f'More than {clustering["point_cap"]:,} sites are in view; zoom in to see individual sites.'
               if zoom >= clustering['point_min_zoom'] else
               f'Sites are grouped at this zoom. Zoom to level {clustering["point_min_zoom"]} or closer to see individual sites.')
    return result | {'mode': 'clusters', 'points': [], 'clusters': clusters, 'cluster_cell_m': round(cell, 3),
                     'message': message}


@router.get('/map')
def map_data(release_id: UUID, bbox: str, zoom: int = Query(..., ge=0, le=22), program: str | None = None,
             site_type: str | None = None, location_type: str | None = None, setting: str | None = None,
             db: Session = Depends(get_db)):
    config = load_registry()
    filters = parse_filters(config, {'program': program, 'site_type': site_type, 'location_type': location_type,
                                     'setting': setting})
    return map_payload(db, config, release_id, bbox, zoom, filters)


def table_payload(db, config, release_id, bbox, filters, limit, offset):
    if limit > config['clustering']['table_page_max']:
        raise HTTPException(400, f'limit may not exceed {config["clustering"]["table_page_max"]}')
    release = published_release(db, config, release_id)
    p = query_params(release_id, bbox, filters)
    total = count_sites(db, p)
    rows = db.execute(text(f'''SELECT {SUMMARY} {SITE_WHERE}
        ORDER BY s.state_abbr NULLS LAST, s.city NULLS LAST, s.site_name, s.site_id LIMIT :limit OFFSET :offset'''),
        p | {'limit': limit, 'offset': offset}).mappings().all()
    names = labels(config)
    return base(config, release, release_id, bbox, filters) | {
        'total': total, 'limit': limit, 'offset': offset, 'rows': [summary_row(r, names) for r in rows]}


@router.get('/table')
def table(release_id: UUID, bbox: str, program: str | None = None, site_type: str | None = None,
          location_type: str | None = None, setting: str | None = None,
          limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0, le=100000), db: Session = Depends(get_db)):
    config = load_registry()
    filters = parse_filters(config, {'program': program, 'site_type': site_type, 'location_type': location_type,
                                     'setting': setting})
    return table_payload(db, config, release_id, bbox, filters, limit, offset)


def detail_payload(db, config, release_id, site_id):
    release = published_release(db, config, release_id)
    row = db.execute(text(f'''SELECT s.*, ST_X(s.geom) AS lon, ST_Y(s.geom) AS lat,
            (SELECT count(*) FROM {S}.site_hrsa o WHERE o.release_id=s.release_id AND o.location_status='mapped'
               AND o.eligible AND o.source_x=s.source_x AND o.source_y=s.source_y) AS sites_at_location
        FROM {S}.site_hrsa s WHERE s.release_id=:release AND s.site_id=:site
        AND s.location_status='mapped' AND s.eligible'''), {'release': release_id, 'site': site_id}).mappings().one_or_none()
    if not row:
        raise HTTPException(404, 'Site is not a mapped, eligible site in this release')
    names = labels(config)
    return {'dataset_id': config['dataset_id'], 'release_id': str(release_id), 'snapshot_date': release['snapshot_date'],
            'source_release_id': release['source_release_id'], 'site_id': row['site_id'],
            'program': row['program_code'], 'program_label': names['program'][row['program_code']],
            'site_type': row['site_type_code'], 'site_type_label': names['site_type'][row['site_type_code']],
            'location_type': row['location_type_code'], 'location_type_label': names['location_type'][row['location_type_code']],
            'setting': row['setting_code'], 'setting_label': names['setting'][row['setting_code']],
            'site_status': row['site_status'], 'attributes': row['attributes'],
            'location': {'lon': row['lon'], 'lat': row['lat'], 'published_x': row['source_x'], 'published_y': row['source_y'],
                         'crs': config['location_policy']['crs'], 'boundary_check': row['boundary_check'],
                         'sites_at_location': row['sites_at_location']},
            'services_note': 'HRSA does not list services offered or new-patient acceptance in this file.'}


@router.get('/detail')
def detail(release_id: UUID, site_id: str = Query(..., min_length=14, max_length=14), db: Session = Depends(get_db)):
    return detail_payload(db, load_registry(), release_id, site_id)
