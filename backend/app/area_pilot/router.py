"""Release-pinned county and tract read API; public URL is /api/area via nginx."""
from __future__ import annotations
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import get_db
from app.area_pilot.registry import load_registry
from app.area_pilot import acs_api, acs_profile_api, ahrf_api, brfss_api, clh_api, cms_gv_api, epa_aqi_api, usda_fea_api

router = APIRouter(prefix='/area', tags=['area-pilot'])
CAP = 5000
TRACT_CAP = 5000
COMMON = '''FROM area_pilot.observation o JOIN dim_county_boundary b ON b.location_id=o.county_fips
WHERE o.release_id=:release AND o.measure_id=:measure AND o.observation_period=:period
AND o.population=:population AND o.value_type=:value_type AND b.geom IS NOT NULL
AND b.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
AND ST_Intersects(b.geom, ST_MakeEnvelope(:west,:south,:east,:north,4326))'''
TRACT_COMMON = '''FROM area_pilot.observation_tract o JOIN (
    SELECT geoid11 AS location_id,name,geom FROM tract_shapes WHERE statefp <> '09'
    UNION ALL
    SELECT tract_fips AS location_id,name,geom FROM area_pilot.tract_boundary_ct_2023
) b ON b.location_id=o.tract_fips
WHERE o.release_id=:release AND o.measure_id=:measure AND o.observation_period=:period
AND o.population=:population AND o.value_type=:value_type AND b.geom IS NOT NULL
AND b.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
AND ST_Intersects(b.geom, ST_MakeEnvelope(:west,:south,:east,:north,4326))'''


def common_sql(geography):
    return TRACT_COMMON if geography == 'tract' else COMMON


def selection(db, release_id, measure_id, period, population, value_type, geography, dataset_id):
    config = load_registry()
    if dataset_id != config['dataset_id']:
        raise HTTPException(404, 'Dataset not found')
    if geography not in ('county','tract') or value_type != config['value_type']:
        raise HTTPException(400, 'Only county or tract crude prevalence is available')
    measure = next((m for m in config['measures'] if m['measure_id'] == measure_id), None)
    if not measure or period != measure['observation_period'] or population != measure['population']:
        raise HTTPException(400, 'Measure, period, or population is unavailable')
    release = db.execute(text('SELECT status,parent_county_release_id FROM area_pilot.release WHERE id=:release AND dataset_id=:dataset'),
                         {'release':release_id,'dataset':config['dataset_id']}).mappings().one_or_none()
    if not release or release['status'] != 'published':
        raise HTTPException(404, 'Published release not found')
    if geography == 'tract' and release['parent_county_release_id'] is None:
        raise HTTPException(400, 'No tract estimate is published for this release; county estimates remain available')
    return config, measure


def bounds(bbox):
    try: west,south,east,north = map(float,bbox.split(','))
    except (ValueError, TypeError): raise HTTPException(400, 'bbox must be west,south,east,north')
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise HTTPException(400, 'Invalid bbox bounds')
    return dict(west=west,south=south,east=east,north=north)


def params(release_id, measure_id, period, population, value_type, bbox):
    return dict(release=release_id,measure=measure_id,period=period,population=population,value_type=value_type,**bounds(bbox))


def ensure_cap(db, query_params, geography='county'):
    cap = TRACT_CAP if geography == 'tract' else CAP
    if geography == 'tract':
        count = db.execute(text('SELECT count(*) FROM (SELECT 1 ' + common_sql(geography)
                                + ' LIMIT :cap_limit) bounded'), query_params | {'cap_limit': cap + 1}).scalar_one()
    else:
        count = db.execute(text('SELECT count(*) ' + common_sql(geography)), query_params).scalar_one()
    if count > cap:
        raise HTTPException(413, f'Viewport contains more than {cap} {geography} areas. Zoom in or narrow the viewport.')
    return count


@router.get('/catalog')
def catalog(dataset_id: str | None = None, db: Session = Depends(get_db)):
    if dataset_id == brfss_api.load_registry()['dataset_id']:
        return brfss_api.catalog(db)
    if dataset_id == acs_profile_api.load_registry()['dataset_id']:
        return acs_profile_api.catalog(db)
    if dataset_id == usda_fea_api.load_registry()['dataset_id']:
        return usda_fea_api.catalog(db)
    if dataset_id == cms_gv_api.load_registry()['dataset_id']:
        return cms_gv_api.catalog(db)
    if dataset_id == epa_aqi_api.load_registry()['dataset_id']:
        return epa_aqi_api.catalog(db)
    if dataset_id == clh_api.load_registry()['dataset_id']:
        return clh_api.catalog(db)
    if dataset_id == acs_api.load_registry()['dataset_id']:
        return acs_api.catalog(db)
    if dataset_id == ahrf_api.load_registry()['dataset_id']:
        return ahrf_api.catalog(db)
    config = load_registry()
    active = db.execute(text('''SELECT a.release_id,r.parent_county_release_id FROM area_pilot.active_release a
        JOIN area_pilot.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset'''),
        {'dataset':config['dataset_id']}).mappings().one_or_none()
    releases = db.execute(text("SELECT id,source_release_id,semantic_sha256,schema_sha256,metadata_sha256,published_at,parent_county_release_id FROM area_pilot.release WHERE dataset_id=:dataset AND status='published' ORDER BY published_at DESC"), {'dataset':config['dataset_id']}).mappings().all()
    return {'dataset_id':config['dataset_id'],'name':config['name'],'publisher':config['publisher'],
            'source_url':config['landing_page'],'geographies':['county','tract'] if active and active['parent_county_release_id'] else ['county'],
            'aggregation_method':config['aggregation_method'],
            'boundary_vintage':{'county':config['boundary_vintage'],'tract':'TIGER/Line 2020 except Connecticut TIGER/Line 2023 planning-region tracts'},
            'unit':config['unit'],'value_type':config['value_type'],'missing_semantics':config['missing_semantics'],
            'measures':config['measures'],
            'active_release_id':str(active['release_id']) if active else None,
            'published_releases':[{**dict(row),'id':str(row['id']),
                                   'parent_county_release_id':str(row['parent_county_release_id']) if row['parent_county_release_id'] else None,
                                   'geographies':['county','tract'] if row['parent_county_release_id'] else ['county']}
                                  for row in releases]}


@router.get('/map')
def map_data(dataset_id: str, release_id: UUID, measure_id: str, period: str, population: str, value_type: str,
             geography: str, bbox: str, simplify: float = Query(0.04, ge=0, le=0.5), db: Session = Depends(get_db)):
    if dataset_id == brfss_api.load_registry()['dataset_id']:
        config, measure = brfss_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox)
        base = brfss_api.metadata(config,measure,release_id,bbox)
        return brfss_api.map_data(db,p,base,simplify)
    if dataset_id == acs_profile_api.load_registry()['dataset_id']:
        config, measure = acs_profile_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox) | {'level':geography}
        base = acs_profile_api.metadata(config,measure,release_id,geography,bbox)
        return acs_profile_api.map_data(db,p,acs_profile_api.ensure_cap(db,p),base,simplify)
    if dataset_id == usda_fea_api.load_registry()['dataset_id']:
        config, measure = usda_fea_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox)
        count = usda_fea_api.ensure_cap(db,p)
        return usda_fea_api.map_data(db,p,count,usda_fea_api.metadata(config,measure,release_id,bbox),simplify)
    if dataset_id == cms_gv_api.load_registry()['dataset_id']:
        config, measure = cms_gv_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox) | {'level':geography}
        count = cms_gv_api.ensure_cap(db,p)
        return cms_gv_api.map_data(db,p,count,cms_gv_api.metadata(config,measure,release_id,geography,bbox),simplify)
    if dataset_id == epa_aqi_api.load_registry()['dataset_id']:
        config, measure = epa_aqi_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox)
        count = epa_aqi_api.ensure_cap(db,p)
        return epa_aqi_api.map_data(db,p,count,epa_aqi_api.metadata(config,measure,release_id,bbox),simplify)
    if dataset_id == clh_api.load_registry()['dataset_id']:
        config, measure = clh_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox) | {'level':geography}
        count = clh_api.ensure_cap(db,p)
        return clh_api.map_data(db,p,count,clh_api.metadata(config,measure,release_id,geography,bbox),simplify)
    if dataset_id == ahrf_api.load_registry()['dataset_id']:
        config, measure = ahrf_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox)
        count = ahrf_api.ensure_cap(db,p)
        return ahrf_api.map_data(db,p,count,ahrf_api.metadata(config,measure,release_id,bbox),simplify)
    if dataset_id == acs_api.load_registry()['dataset_id']:
        config = acs_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox) | {'level':geography}
        count = acs_api.ensure_cap(db,p)
        base = acs_api.metadata(config,release_id,measure_id,period,population,value_type,geography,bbox)
        return acs_api.map_data(db,config,p,count,base,simplify)
    config, measure = selection(db,release_id,measure_id,period,population,value_type,geography,dataset_id)
    query_params = params(release_id,measure_id,period,population,value_type,bbox) | {'simplify':simplify}
    count = ensure_cap(db,query_params,geography)
    key = 'tract_fips' if geography == 'tract' else 'county_fips'
    rows = db.execute(text(f'''SELECT o.{key} AS geography_id,b.name,
        ST_AsGeoJSON(ST_SimplifyPreserveTopology(b.geom,:simplify))::json AS geometry,
        o.value,o.ci_low,o.ci_high,o.status ''' + common_sql(geography) + f' ORDER BY o.{key}'), query_params).mappings().all()
    features = [{'type':'Feature','geometry':r['geometry'],'properties':{
        key:r['geography_id'],'geography_id':r['geography_id'],'name':r['name'],'value':float(r['value']) if r['value'] is not None else None,
        'ci_low':float(r['ci_low']) if r['ci_low'] is not None else None,
        'ci_high':float(r['ci_high']) if r['ci_high'] is not None else None,'status':r['status'],
        'observation_period':period,'measure_id':measure_id}} for r in rows]
    if len(features) != count:
        raise HTTPException(409, 'Viewport changed during map retrieval; retry the request')
    return {'type':'FeatureCollection','features':features,'count':count,'complete':True,
            'dataset_id':config['dataset_id'],'release_id':str(release_id),'measure_id':measure_id,
            'period':period,'population':population,'value_type':value_type,'geography':geography,
            'unit':config['unit'],'boundary_vintage':config['boundary_vintage'] if geography == 'county' else 'TIGER/Line 2020 except CT 2023',
            'simplify':simplify,'bbox':bbox}


@router.get('/legend')
def legend(dataset_id: str, release_id: UUID, measure_id: str, period: str, population: str, value_type: str,
           geography: str, bbox: str, db: Session = Depends(get_db)):
    if dataset_id == brfss_api.load_registry()['dataset_id']:
        config, measure = brfss_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox)
        base = brfss_api.metadata(config,measure,release_id,bbox)
        return brfss_api.legend(db,p,base)
    if dataset_id == acs_profile_api.load_registry()['dataset_id']:
        config, measure = acs_profile_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox) | {'level':geography}
        base = acs_profile_api.metadata(config,measure,release_id,geography,bbox)
        return acs_profile_api.legend(db,p,base)
    if dataset_id == usda_fea_api.load_registry()['dataset_id']:
        config, measure = usda_fea_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox)
        usda_fea_api.ensure_cap(db,p)
        return usda_fea_api.legend(db,p,usda_fea_api.metadata(config,measure,release_id,bbox))
    if dataset_id == cms_gv_api.load_registry()['dataset_id']:
        config, measure = cms_gv_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox) | {'level':geography}
        cms_gv_api.ensure_cap(db,p)
        return cms_gv_api.legend(db,p,cms_gv_api.metadata(config,measure,release_id,geography,bbox))
    if dataset_id == epa_aqi_api.load_registry()['dataset_id']:
        config, measure = epa_aqi_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox)
        epa_aqi_api.ensure_cap(db,p)
        return epa_aqi_api.legend(db,p,epa_aqi_api.metadata(config,measure,release_id,bbox))
    if dataset_id == clh_api.load_registry()['dataset_id']:
        config, measure = clh_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox) | {'level':geography}
        clh_api.ensure_cap(db,p)
        return clh_api.legend(db,p,clh_api.metadata(config,measure,release_id,geography,bbox))
    if dataset_id == ahrf_api.load_registry()['dataset_id']:
        config, measure = ahrf_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox)
        ahrf_api.ensure_cap(db,p)
        return ahrf_api.legend(db,p,ahrf_api.metadata(config,measure,release_id,bbox))
    if dataset_id == acs_api.load_registry()['dataset_id']:
        config = acs_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox) | {'level':geography}
        acs_api.ensure_cap(db,p)
        base = acs_api.metadata(config,release_id,measure_id,period,population,value_type,geography,bbox)
        return acs_api.legend(db,p,base)
    config, measure = selection(db,release_id,measure_id,period,population,value_type,geography,dataset_id)
    p = params(release_id,measure_id,period,population,value_type,bbox)
    ensure_cap(db,p,geography)
    stats = db.execute(text('''SELECT status,count(*) AS n,min(value) AS low,max(value) AS high ''' + common_sql(geography) + ' GROUP BY status ORDER BY status'),p).mappings().all()
    return {'dataset_id':config['dataset_id'],'release_id':str(release_id),'measure_id':measure_id,
            'period':period,'population':population,'value_type':value_type,'geography':geography,'unit':config['unit'],
            'bbox':bbox,'statuses':[{**dict(r),'low':float(r['low']) if r['low'] is not None else None,
                                    'high':float(r['high']) if r['high'] is not None else None} for r in stats]}


@router.get('/table')
def table(dataset_id: str, release_id: UUID, measure_id: str, period: str, population: str, value_type: str,
          geography: str, bbox: str, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    if dataset_id == brfss_api.load_registry()['dataset_id']:
        config, measure = brfss_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox)
        base = brfss_api.metadata(config,measure,release_id,bbox)
        return brfss_api.table(db,p,base,limit,offset,config)
    if dataset_id == acs_profile_api.load_registry()['dataset_id']:
        config, measure = acs_profile_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox) | {'level':geography}
        base = acs_profile_api.metadata(config,measure,release_id,geography,bbox)
        return acs_profile_api.table(db,p,base,acs_profile_api.ensure_cap(db,p),limit,offset)
    if dataset_id == usda_fea_api.load_registry()['dataset_id']:
        config, measure = usda_fea_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox)
        count = usda_fea_api.ensure_cap(db,p)
        return usda_fea_api.table(db,p,usda_fea_api.metadata(config,measure,release_id,bbox),count,limit,offset)
    if dataset_id == cms_gv_api.load_registry()['dataset_id']:
        config, measure = cms_gv_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox) | {'level':geography}
        count = cms_gv_api.ensure_cap(db,p)
        return cms_gv_api.table(db,p,cms_gv_api.metadata(config,measure,release_id,geography,bbox),count,limit,offset)
    if dataset_id == epa_aqi_api.load_registry()['dataset_id']:
        config, measure = epa_aqi_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox)
        count = epa_aqi_api.ensure_cap(db,p)
        return epa_aqi_api.table(db,p,epa_aqi_api.metadata(config,measure,release_id,bbox),count,limit,offset)
    if dataset_id == clh_api.load_registry()['dataset_id']:
        config, measure = clh_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox) | {'level':geography}
        count = clh_api.ensure_cap(db,p)
        return clh_api.table(db,p,clh_api.metadata(config,measure,release_id,geography,bbox),count,limit,offset)
    if dataset_id == ahrf_api.load_registry()['dataset_id']:
        config, measure = ahrf_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox)
        count = ahrf_api.ensure_cap(db,p)
        return ahrf_api.table(db,p,ahrf_api.metadata(config,measure,release_id,bbox),count,limit,offset)
    if dataset_id == acs_api.load_registry()['dataset_id']:
        config = acs_api.selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography)
        p = params(release_id,measure_id,period,population,value_type,bbox) | {'level':geography}
        count = acs_api.ensure_cap(db,p)
        base = acs_api.metadata(config,release_id,measure_id,period,population,value_type,geography,bbox)
        return acs_api.table(db,p,base,count,limit,offset)
    config, measure = selection(db,release_id,measure_id,period,population,value_type,geography,dataset_id)
    p = params(release_id,measure_id,period,population,value_type,bbox) | {'limit':limit,'offset':offset}
    count = ensure_cap(db,p,geography)
    key = 'tract_fips' if geography == 'tract' else 'county_fips'
    rows = db.execute(text(f'SELECT o.{key} AS geography_id,b.name,o.value,o.ci_low,o.ci_high,o.status '
                           +common_sql(geography)+f' ORDER BY o.{key} LIMIT :limit OFFSET :offset'),p).mappings().all()
    return {'dataset_id':config['dataset_id'],'release_id':str(release_id),'measure_id':measure_id,
            'period':period,'population':population,'value_type':value_type,'geography':geography,'unit':config['unit'],
            'bbox':bbox,'total':count,'limit':limit,'offset':offset,'rows':[
                {key:r['geography_id'],'geography_id':r['geography_id'],'name':r['name'],'value':float(r['value']) if r['value'] is not None else None,
                 'ci_low':float(r['ci_low']) if r['ci_low'] is not None else None,
                 'ci_high':float(r['ci_high']) if r['ci_high'] is not None else None,'status':r['status'],
                 'observation_period':period,'measure_id':measure_id} for r in rows]}
