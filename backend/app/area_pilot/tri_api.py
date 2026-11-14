"""Release-pinned, read-only EPA TRI reporting-facility overlay API; public URL /api/area/tri via nginx.

Map, table, and detail requests share one WHERE clause (``FACILITY_WHERE``): an explicit published
release, a mapped location, the selected TRI industry sectors, an optional TRI chemical ID, and a
required bounding box. The chemical filter is an EXISTS test on the facility-chemical relationship,
so a facility with several forms for one chemical is still one facility. The map returns individual
points only when the viewport holds at most ``point_cap`` facilities at zoom >= ``point_min_zoom``;
otherwise it returns grid clusters whose counts sum exactly to the table total. A request that would
exceed a cap returns 413; nothing is truncated silently. No release quantity is read or returned.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.area_pilot.hrsa_sites_api import cluster_cell_m
from app.area_pilot.router import bounds
from app.area_pilot.tri import load_registry
from app.db import get_db

router = APIRouter(prefix='/area/tri', tags=['area-tri'])
S = 'area_pilot'
FACILITY_WHERE = f'''FROM {S}.tri_facility f
WHERE f.release_id=:release AND f.location_status='mapped'
 AND f.sector_codes && CAST(:sector AS text[])
 AND (CAST(:chemical AS text) IS NULL OR EXISTS (SELECT 1 FROM {S}.tri_facility_chemical c
      WHERE c.release_id=f.release_id AND c.facility_id=f.facility_id AND c.chemical_id=CAST(:chemical AS text)))
 AND f.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)'''
SUMMARY = '''f.facility_id,f.facility_name,f.city,f.state_abbr,f.sector_codes,f.chemical_count,f.report_count,
 f.source_latitude,f.source_longitude,ST_X(f.geom) AS lon,ST_Y(f.geom) AS lat'''


def sector_labels(config):
    return {s['code']: s['label'] for s in config['industry_sectors']}


def parse_filters(config, sector=None, chemical=None):
    """``sector=None`` selects every reviewed sector; an explicit empty selection is rejected."""
    allowed = sector_labels(config)
    if sector is None:
        sectors = sorted(allowed)
    else:
        sectors = sorted({part.strip() for part in sector.split(',') if part.strip()})
        if not sectors:
            raise HTTPException(400, 'Select at least one industry sector')
        unknown = sorted(set(sectors) - set(allowed))
        if unknown:
            raise HTTPException(400, f'Unknown industry sector code(s): {", ".join(unknown)}')
    chemical = (chemical or '').strip() or None
    if chemical is not None and len(chemical) > 12:
        raise HTTPException(400, 'Invalid TRI chemical ID')
    return {'sector': sectors, 'chemical': chemical}


def published_release(db, config, release_id):
    row = db.execute(text(f'''SELECT status,source_release_id,source_after->>'processed_as_of' AS processed_as_of,
            (source_after->>'reporting_year')::int AS reporting_year
        FROM {S}.release WHERE id=:release AND dataset_id=:dataset'''),
        {'release': release_id, 'dataset': config['dataset_id']}).mappings().one_or_none()
    if not row or row['status'] != 'published':
        raise HTTPException(404, 'Published TRI facility release not found')
    return row


def chemical_row(db, release_id, chemical_id):
    return db.execute(text(f'''SELECT chemical_id,names,cas_number FROM {S}.tri_chemical
        WHERE release_id=:release AND chemical_id=:chemical'''), {'release': release_id, 'chemical': chemical_id}).mappings().one_or_none()


def checked_filters(db, release_id, filters):
    if filters['chemical'] is not None and not chemical_row(db, release_id, filters['chemical']):
        raise HTTPException(400, 'TRI chemical ID is not reported in this release')
    return filters


def query_params(release_id, bbox, filters):
    return {'release': release_id, **bounds(bbox), **filters}


def base(config, release, release_id, bbox, filters):
    return {'dataset_id': config['dataset_id'], 'release_id': str(release_id),
            'source_release_id': release['source_release_id'], 'reporting_year': release['reporting_year'],
            'processed_as_of': release['processed_as_of'], 'bbox': bbox,
            'filters': {'sector': filters['sector'], 'chemical': filters['chemical']},
            'crs': config['location_policy']['crs']}


def count_facilities(db, p):
    return db.execute(text('SELECT count(*) ' + FACILITY_WHERE), p).scalar_one()


def summary_row(r, labels):
    return {'facility_id': r['facility_id'], 'facility_name': r['facility_name'], 'city': r['city'],
            'state': r['state_abbr'], 'sectors': [{'code': c, 'label': labels.get(c, c)} for c in r['sector_codes']],
            'chemical_count': r['chemical_count'], 'form_count': r['report_count'],
            'lon': r['lon'], 'lat': r['lat'], 'location_key': f"{r['source_longitude']},{r['source_latitude']}"}


def catalog_payload(db, config):
    active = db.execute(text(f'''SELECT a.release_id FROM {S}.active_release a JOIN {S}.release r ON r.id=a.release_id
        WHERE a.dataset_id=:dataset AND r.status='published' '''), {'dataset': config['dataset_id']}).scalar_one_or_none()
    releases = db.execute(text(f'''SELECT id,source_release_id,source_after->>'processed_as_of' AS processed_as_of,
            (source_after->>'reporting_year')::int AS reporting_year, report->>'retrieved_at' AS retrieved_at,
            semantic_sha256,schema_sha256,metadata_sha256,published_at
        FROM {S}.release WHERE dataset_id=:dataset AND status='published' ORDER BY published_at DESC'''),
        {'dataset': config['dataset_id']}).mappings().all()
    payload = {key: config[key] for key in ('dataset_id', 'name', 'short_label', 'publisher', 'landing_page',
                                            'product_kind', 'usage_terms', 'limitations', 'interpretation')}
    payload |= {'source_url': config['download_page'], 'reporting_year': config['reporting_year'],
                'boundary_vintage': config['boundary']['vintage'],
                'coordinate_reference': {k: config['location_policy'][k] for k in ('crs', 'crs_basis', 'source_quality_fields')},
                'location_rules': config['location_policy']['rules'], 'boundary_checks': config['location_policy']['boundary_checks'],
                'location_never': config['location_policy']['never'], 'clustering': config['clustering'],
                'detail_link': {'label': config['detail_link']['label'], 'template': config['detail_link']['template']},
                'form_types': config['form_types'], 'generic_chemical_ids': config['generic_chemical_ids'],
                'active_release_id': str(active) if active else None,
                'published_releases': [{**dict(r), 'id': str(r['id'])} for r in releases]}
    counts = {}
    if active:
        status_rows = dict(db.execute(text(f'''SELECT location_status,count(*) FROM {S}.tri_facility
            WHERE release_id=:release GROUP BY 1'''), {'release': active}).all())
        boundary_rows = dict(db.execute(text(f'''SELECT boundary_check,count(*) FROM {S}.tri_facility
            WHERE release_id=:release AND location_status='mapped' GROUP BY 1'''), {'release': active}).all())
        sector_rows = dict(db.execute(text(f'''SELECT s,count(*) FROM {S}.tri_facility f, unnest(f.sector_codes) s
            WHERE f.release_id=:release AND f.location_status='mapped' GROUP BY 1'''), {'release': active}).all())
        totals = db.execute(text(f'''SELECT (SELECT count(*) FROM {S}.tri_report WHERE release_id=:release) AS reports,
            (SELECT count(*) FROM {S}.tri_report WHERE release_id=:release AND form_type='A') AS form_a,
            (SELECT count(*) FROM {S}.tri_chemical WHERE release_id=:release) AS chemicals,
            (SELECT count(*) FROM {S}.tri_facility_chemical WHERE release_id=:release) AS pairs'''),
            {'release': active}).mappings().one()
        last_confirmed = db.execute(text(f'''SELECT max(detail->>'confirmed_processed_as_of') FROM {S}.run
            WHERE release_id=:release AND action='fetch-stage-validate' AND status='duplicate' '''),
            {'release': active}).scalar_one_or_none()
        counts = {'source_reports': totals['reports'], 'form_a_reports': totals['form_a'],
                  'facilities': sum(status_rows.values()), 'mapped_facilities': status_rows.get('mapped', 0),
                  'not_mapped_by_reason': {k: v for k, v in sorted(status_rows.items()) if k != 'mapped'},
                  'mapped_by_boundary_check': dict(sorted(boundary_rows.items())),
                  'chemical_ids': totals['chemicals'], 'facility_chemical_relationships': totals['pairs'],
                  'last_confirmed_processed_as_of': last_confirmed}
        payload['sectors'] = [{'code': s['code'], 'label': s['label'], 'mapped_facilities': sector_rows.get(s['code'], 0)}
                              for s in config['industry_sectors']]
        active_release = next((r for r in releases if str(r['id']) == str(active)), None)
        payload['processed_as_of'] = active_release['processed_as_of'] if active_release else None
        payload['retrieved_at'] = active_release['retrieved_at'] if active_release else None
    payload['counts'] = counts
    return payload


@router.get('/catalog')
def catalog(db: Session = Depends(get_db)):
    return catalog_payload(db, load_registry())


def chemicals_payload(db, config, release_id, q, limit, offset):
    if limit > config['clustering']['chemical_page_max']:
        raise HTTPException(400, f'limit may not exceed {config["clustering"]["chemical_page_max"]}')
    release = published_release(db, config, release_id)
    pattern = None
    if q and q.strip():
        escaped = q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        pattern = f'%{escaped}%'
    where = f'''FROM {S}.tri_chemical c WHERE c.release_id=:release AND (CAST(:pattern AS text) IS NULL
        OR c.chemical_id ILIKE :pattern OR c.cas_number ILIKE :pattern
        OR EXISTS (SELECT 1 FROM unnest(c.names) n WHERE n ILIKE :pattern))'''
    p = {'release': release_id, 'pattern': pattern}
    total = db.execute(text('SELECT count(*) ' + where), p).scalar_one()
    rows = db.execute(text(f'''SELECT c.chemical_id,c.names,c.cas_number,c.facility_count,
            (SELECT count(*) FROM {S}.tri_facility_chemical fc JOIN {S}.tri_facility f
               ON f.release_id=fc.release_id AND f.facility_id=fc.facility_id
             WHERE fc.release_id=c.release_id AND fc.chemical_id=c.chemical_id AND f.location_status='mapped') AS mapped
        {where} ORDER BY lower(c.names[1]), c.chemical_id LIMIT :limit OFFSET :offset'''),
        p | {'limit': limit, 'offset': offset}).mappings().all()
    return {'dataset_id': config['dataset_id'], 'release_id': str(release_id), 'reporting_year': release['reporting_year'],
            'q': q or '', 'total': total, 'limit': limit, 'offset': offset,
            'rows': [{'chemical_id': r['chemical_id'], 'names': list(r['names']), 'cas_number': r['cas_number'],
                      'facilities': r['facility_count'], 'mapped_facilities': r['mapped'],
                      'generic_identity_note': config['generic_chemical_ids'].get(r['chemical_id'])} for r in rows]}


@router.get('/chemicals')
def chemicals(release_id: UUID, q: str | None = Query(None, max_length=80), limit: int = Query(50, ge=1, le=500),
              offset: int = Query(0, ge=0, le=100000), db: Session = Depends(get_db)):
    return chemicals_payload(db, load_registry(), release_id, q, limit, offset)


def map_payload(db, config, release_id, bbox, zoom, filters):
    release = published_release(db, config, release_id)
    checked_filters(db, release_id, filters)
    p = query_params(release_id, bbox, filters)
    clustering = config['clustering']
    total = count_facilities(db, p)
    result = base(config, release, release_id, bbox, filters) | {
        'zoom': zoom, 'total': total, 'complete': True, 'point_cap': clustering['point_cap'],
        'point_min_zoom': clustering['point_min_zoom'], 'cluster_note': clustering['note']}
    labels = sector_labels(config)
    if zoom >= clustering['point_min_zoom'] and total <= clustering['point_cap']:
        rows = db.execute(text(f'SELECT {SUMMARY} {FACILITY_WHERE} ORDER BY f.facility_id LIMIT :cap'),
                          p | {'cap': clustering['point_cap'] + 1}).mappings().all()
        if len(rows) != total:
            raise HTTPException(409, 'Facility count changed during retrieval; retry the request')
        return result | {'mode': 'points', 'points': [summary_row(r, labels) for r in rows], 'clusters': [], 'message': None}
    cell = cluster_cell_m(zoom, clustering['cluster_cell_px'])
    rows = db.execute(text(f'''SELECT floor(ST_X(t.m)/:cell)::bigint AS gx, floor(ST_Y(t.m)/:cell)::bigint AS gy,
            count(*) AS n, avg(t.lon) AS lon, avg(t.lat) AS lat, min(t.lon) AS west, min(t.lat) AS south,
            max(t.lon) AS east, max(t.lat) AS north, count(DISTINCT t.location_key) AS locations
        FROM (SELECT ST_Transform(f.geom,3857) AS m, ST_X(f.geom) AS lon, ST_Y(f.geom) AS lat,
                     f.source_longitude || ',' || f.source_latitude AS location_key {FACILITY_WHERE}) t
        GROUP BY 1,2 ORDER BY 1,2 LIMIT :cap'''), p | {'cell': cell, 'cap': clustering['cluster_cap'] + 1}).mappings().all()
    if len(rows) > clustering['cluster_cap']:
        raise HTTPException(413, f'Viewport would need more than {clustering["cluster_cap"]} clusters at this zoom. '
                                 'Zoom in or narrow the viewport.')
    clusters = [{'id': f'{zoom}:{r["gx"]}:{r["gy"]}', 'count': r['n'], 'lon': float(r['lon']), 'lat': float(r['lat']),
                 'bounds': [float(r['west']), float(r['south']), float(r['east']), float(r['north'])],
                 'distinct_locations': r['locations']} for r in rows]
    if sum(c['count'] for c in clusters) != total:
        raise HTTPException(409, 'Cluster counts differ from the facility total; retry the request')
    message = (f'More than {clustering["point_cap"]:,} facilities are in view; zoom in to see individual facilities.'
               if zoom >= clustering['point_min_zoom'] else
               f'Facilities are grouped at this zoom. Zoom to level {clustering["point_min_zoom"]} or closer to see individual facilities.')
    return result | {'mode': 'clusters', 'points': [], 'clusters': clusters, 'cluster_cell_m': round(cell, 3), 'message': message}


@router.get('/map')
def map_data(release_id: UUID, bbox: str, zoom: int = Query(..., ge=0, le=22), sector: str | None = None,
             chemical: str | None = None, db: Session = Depends(get_db)):
    config = load_registry()
    return map_payload(db, config, release_id, bbox, zoom, parse_filters(config, sector, chemical))


def table_payload(db, config, release_id, bbox, filters, limit, offset):
    if limit > config['clustering']['table_page_max']:
        raise HTTPException(400, f'limit may not exceed {config["clustering"]["table_page_max"]}')
    release = published_release(db, config, release_id)
    checked_filters(db, release_id, filters)
    p = query_params(release_id, bbox, filters)
    total = count_facilities(db, p)
    rows = db.execute(text(f'''SELECT {SUMMARY} {FACILITY_WHERE}
        ORDER BY f.state_abbr NULLS LAST, f.city NULLS LAST, f.facility_name, f.facility_id LIMIT :limit OFFSET :offset'''),
        p | {'limit': limit, 'offset': offset}).mappings().all()
    labels = sector_labels(config)
    return base(config, release, release_id, bbox, filters) | {
        'total': total, 'limit': limit, 'offset': offset, 'rows': [summary_row(r, labels) for r in rows]}


@router.get('/table')
def table(release_id: UUID, bbox: str, sector: str | None = None, chemical: str | None = None,
          limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0, le=100000), db: Session = Depends(get_db)):
    config = load_registry()
    return table_payload(db, config, release_id, bbox, parse_filters(config, sector, chemical), limit, offset)


def detail_payload(db, config, release_id, facility_id, chemical_limit, chemical_offset):
    if chemical_limit > config['clustering']['detail_chemical_page_max']:
        raise HTTPException(400, f'chemical_limit may not exceed {config["clustering"]["detail_chemical_page_max"]}')
    release = published_release(db, config, release_id)
    row = db.execute(text(f'''SELECT f.*, ST_X(f.geom) AS lon, ST_Y(f.geom) AS lat, b.name AS derived_county_name,
            (SELECT count(*) FROM {S}.tri_facility o WHERE o.release_id=f.release_id AND o.location_status='mapped'
               AND o.source_latitude=f.source_latitude AND o.source_longitude=f.source_longitude) AS facilities_at_location
        FROM {S}.tri_facility f LEFT JOIN {S}.acs_boundary_2024 b ON b.level='county' AND b.geoid=f.derived_county_geoid
        WHERE f.release_id=:release AND f.facility_id=:facility AND f.location_status='mapped' '''),
        {'release': release_id, 'facility': facility_id}).mappings().one_or_none()
    if not row:
        raise HTTPException(404, 'Facility is not a mapped TRI reporting facility in this release')
    chemicals = db.execute(text(f'''SELECT fc.chemical_id,fc.names,fc.form_types,fc.report_count,c.cas_number
        FROM {S}.tri_facility_chemical fc JOIN {S}.tri_chemical c ON c.release_id=fc.release_id AND c.chemical_id=fc.chemical_id
        WHERE fc.release_id=:release AND fc.facility_id=:facility
        ORDER BY lower(fc.names[1]), fc.chemical_id LIMIT :limit OFFSET :offset'''),
        {'release': release_id, 'facility': facility_id, 'limit': chemical_limit, 'offset': chemical_offset}).mappings().all()
    labels = sector_labels(config)
    a = row['attributes']
    return {'dataset_id': config['dataset_id'], 'release_id': str(release_id), 'source_release_id': release['source_release_id'],
            'reporting_year': release['reporting_year'], 'processed_as_of': release['processed_as_of'],
            'facility_id': row['facility_id'], 'facility_name': row['facility_name'],
            'address': {k: a.get(k) for k in ('street_address', 'city', 'county', 'state', 'zip')},
            'frs_id': row['frs_id'], 'federal_facility': a.get('federal_facility'),
            'tribe': a.get('tribe'), 'bia_code': a.get('bia_code'),
            'parent_company': a.get('parent_company'), 'standard_parent_company': a.get('standard_parent_company'),
            'foreign_parent_company': a.get('foreign_parent_company'),
            'sectors': [{'code': c, 'label': labels.get(c, c)} for c in row['sector_codes']],
            'naics_codes': list(row['naics_codes']),
            'forms': {'total': row['report_count'], 'form_r': row['form_r_count'], 'form_a': row['form_a_count']},
            'chemical_total': row['chemical_count'], 'chemical_limit': chemical_limit, 'chemical_offset': chemical_offset,
            'chemicals': [{'chemical_id': c['chemical_id'], 'names': list(c['names']), 'cas_number': c['cas_number'],
                           'form_types': list(c['form_types']), 'forms': c['report_count'],
                           'generic_identity_note': config['generic_chemical_ids'].get(c['chemical_id'])} for c in chemicals],
            'location': {'lat': row['lat'], 'lon': row['lon'], 'published_latitude': row['source_latitude'],
                         'published_longitude': row['source_longitude'], 'published_datum': a.get('horizontal_datum'),
                         'crs': config['location_policy']['crs'], 'boundary_check': row['boundary_check'],
                         'derived_county_geoid': row['derived_county_geoid'], 'derived_county_name': row['derived_county_name'],
                         'facilities_at_location': row['facilities_at_location']},
            'epa_link': {'label': config['detail_link']['label'],
                         'url': config['detail_link']['template'].format(facility_id=row['facility_id'])},
            'quantities_note': 'Release and waste quantities are not shown in this phase. Form A certifications carry no quantities.',
            'reporting_note': f'Filed TRI forms for reporting year {release["reporting_year"]}. This does not show current operation, '
                              'a violation, exposure, or health risk.'}


@router.get('/detail')
def detail(release_id: UUID, facility_id: str = Query(..., min_length=15, max_length=15),
           chemical_limit: int = Query(100, ge=1, le=500), chemical_offset: int = Query(0, ge=0, le=10000),
           db: Session = Depends(get_db)):
    return detail_payload(db, load_registry(), release_id, facility_id, chemical_limit, chemical_offset)
