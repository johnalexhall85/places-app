"""AHRF read model using the shared area release pointer and 2024 county shapes."""
from fastapi import HTTPException
from sqlalchemy import text

from app.area_pilot import legend_breaks

from app.area_pilot.ahrf import load_registry

S = 'area_pilot'
CAP = 5000
COMMON = f'''FROM {S}.observation_ahrf o JOIN {S}.acs_boundary_2024 b
 ON b.level='county' AND b.geoid=o.geoid
 WHERE o.release_id=:release AND o.measure_id=:measure AND o.observation_period=:period
 AND o.population=:population AND o.value_type=:value_type
 AND b.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
 AND ST_Intersects(b.geom,ST_MakeEnvelope(:west,:south,:east,:north,4326))'''


def catalog(db):
    config = load_registry()
    active = db.execute(text(f'''SELECT a.release_id FROM {S}.active_release a JOIN {S}.release r
        ON r.id=a.release_id WHERE a.dataset_id=:dataset AND r.status='published' '''),
        {'dataset':config['dataset_id']}).scalar_one_or_none()
    releases = db.execute(text(f'''SELECT id,source_release_id,semantic_sha256,schema_sha256,metadata_sha256,published_at
        FROM {S}.release WHERE dataset_id=:dataset AND status='published' ORDER BY published_at DESC'''),
        {'dataset':config['dataset_id']}).mappings().all()
    return {key:config[key] for key in ('dataset_id','name','publisher','landing_page','source_release_id',
            'boundary_vintage','geographies','aggregation_method','value_type','unit','measures')} | {
        'source_url':config['landing_page'], 'missing_semantics': 'Blank source cell is missing; zero is reported zero',
        'uncertainty':'not supplied', 'active_release_id':str(active) if active else None,
        'published_releases':[{**dict(r),'id':str(r['id'])} for r in releases]}


def selection(db,dataset_id,release_id,measure_id,period,population,value_type,geography):
    config = load_registry()
    measure = next((m for m in config['measures'] if m['measure_id']==measure_id),None)
    if dataset_id != config['dataset_id'] or measure is None:
        raise HTTPException(404,'AHRF selection not found')
    if (period,population,value_type,geography) != (measure['observation_period'],measure['population'],config['value_type'],'county'):
        raise HTTPException(400,'AHRF county measure, period, or universe unavailable')
    status = db.execute(text(f'SELECT status FROM {S}.release WHERE id=:release AND dataset_id=:dataset'),
                        {'release':release_id,'dataset':dataset_id}).scalar_one_or_none()
    if status != 'published':
        raise HTTPException(404,'Published AHRF release not found')
    return config,measure


def ensure_cap(db,p):
    count=db.execute(text('SELECT count(*) FROM (SELECT 1 '+COMMON+' LIMIT :cap_limit) bounded'),
                     p|{'cap_limit':CAP+1}).scalar_one()
    if count>CAP:
        raise HTTPException(413,'Viewport contains more than 5,000 counties. Narrow the viewport.')
    return count


def metadata(config,measure,release_id,bbox):
    return {'dataset_id':config['dataset_id'],'release_id':str(release_id),'measure_id':measure['measure_id'],
            'period':measure['observation_period'],'population':measure['population'],
            'value_type':config['value_type'],'geography':'county','unit':measure['unit'],
            'uncertainty':'not supplied','boundary_vintage':config['boundary_vintage'],'bbox':bbox}


def value_fields(row,period,measure_id):
    return {'value':int(row['value']) if row['value'] is not None else None,'status':row['status'],
            'source_code':row['source_code'],'observation_period':period,'measure_id':measure_id,
            'uncertainty':'not supplied'}


def map_data(db,p,count,base,simplify):
    rows=db.execute(text(f'''SELECT o.geoid AS geography_id,b.name,
        ST_AsGeoJSON(ST_SimplifyPreserveTopology(b.geom,:simplify))::json AS geometry,
        o.value,o.status,o.source_code {COMMON} ORDER BY o.geoid'''),p|{'simplify':simplify}).mappings().all()
    if len(rows)!=count:
        raise HTTPException(409,'Viewport changed during AHRF map retrieval; retry')
    return base|{'type':'FeatureCollection','features':[
        {'type':'Feature','geometry':r['geometry'],'properties':{'geography_id':r['geography_id'],
            'name':r['name'],**value_fields(r,base['period'],base['measure_id'])}} for r in rows],
        'count':count,'complete':True,'simplify':simplify}


def legend(db,p,base):
    rows=db.execute(text(f'''SELECT status,count(*) AS n,min(value) AS low,max(value) AS high
        {COMMON} GROUP BY status ORDER BY status'''),p).mappings().all()
    return base|{'statuses':[{**dict(r),'low':int(r['low']) if r['low'] is not None else None,
                              'high':int(r['high']) if r['high'] is not None else None} for r in rows],
                   **legend_breaks.legend_fields(db, f'{S}.observation_ahrf', p, False)}


def table(db,p,base,count,limit,offset):
    rows=db.execute(text(f'''SELECT o.geoid AS geography_id,b.name,o.value,o.status,o.source_code
        {COMMON} ORDER BY o.geoid LIMIT :limit OFFSET :offset'''),
        p|{'limit':limit,'offset':offset}).mappings().all()
    return base|{'total':count,'limit':limit,'offset':offset,'rows':[
        {'geography_id':r['geography_id'],'name':r['name'],
         **value_fields(r,base['period'],base['measure_id'])} for r in rows]}
