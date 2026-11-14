"""Release-pinned CMS nursing home points, bounded clusters, table, and detail."""
from __future__ import annotations

import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.area_pilot.cms_nursing_homes import PRODUCT, load_registry
from app.area_pilot.router import bounds
from app.db import get_db

router = APIRouter(prefix='/area/nursing-homes', tags=['area-nursing-homes'])
S = 'area_pilot'
EARTH_CIRCUMFERENCE_M = 2 * math.pi * 6378137
WHERE = f'''FROM {S}.cms_nursing_home n WHERE n.release_id=:release AND n.location_status='mapped'
 AND n.provider_type=ANY(:provider_type) AND n.ownership_type=ANY(:ownership)
 AND (n.overall_rating=ANY(:rated) OR (:unrated AND n.overall_rating IS NULL))
 AND n.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)'''
SELECT = '''n.ccn,n.provider_name,n.city,n.state_abbr,n.provider_type,n.ownership_type,
 n.certified_beds,n.overall_rating,n.health_inspection_rating,n.staffing_rating,n.quality_measure_rating,
 n.rating_footnotes,n.source_latitude,n.source_longitude,ST_X(n.geom) AS lon,ST_Y(n.geom) AS lat'''


def _release(db, release_id):
    row = db.execute(text(f'''SELECT source_release_id,source_after,report FROM {S}.release
       WHERE id=:release AND dataset_id=:dataset AND status='published' '''),
       {'release':release_id,'dataset':PRODUCT}).mappings().one_or_none()
    if not row: raise HTTPException(404,'Published CMS nursing home release not found')
    return row


def _choices(db, release_id):
    return {name: [r[0] for r in db.execute(text(f'''SELECT DISTINCT {column} FROM {S}.cms_nursing_home
        WHERE release_id=:release AND location_status='mapped' ORDER BY 1'''),{'release':release_id}).all()]
        for name,column in [('provider_type','provider_type'),('ownership','ownership_type')]}


def parse_filters(choices, provider_type=None, ownership=None, overall=None):
    result={}
    for name,raw in [('provider_type',provider_type),('ownership',ownership)]:
        selected=choices[name] if raw is None else sorted({v.strip() for v in raw.split(',') if v.strip()})
        if not selected or set(selected)-set(choices[name]):
            raise HTTPException(400,f'Invalid {name} filter')
        result[name]=selected
    overall_values=['1','2','3','4','5','unrated'] if overall is None else sorted({v.strip() for v in overall.split(',') if v.strip()})
    if not overall_values or set(overall_values)-{'1','2','3','4','5','unrated'}:
        raise HTTPException(400,'Invalid overall rating filter')
    result['overall']=overall_values
    return result


def _params(release_id,bbox,filters):
    return {'release':release_id,**bounds(bbox),'provider_type':filters['provider_type'],
            'ownership':filters['ownership'],'rated':[int(v) for v in filters['overall'] if v!='unrated'],
            'unrated':'unrated' in filters['overall']}


def _base(release_id,release,bbox,filters):
    return {'dataset_id':PRODUCT,'release_id':str(release_id),'source_release_id':release['source_release_id'],
            'processing_date':release['source_after']['modified'],'bbox':bbox,'filters':filters,'crs':'EPSG:4326'}


def _summary(row):
    return {'ccn':row['ccn'],'provider_name':row['provider_name'],'city':row['city'],'state':row['state_abbr'],
            'provider_type':row['provider_type'],'ownership_type':row['ownership_type'],
            'certified_beds':row['certified_beds'],'overall_rating':row['overall_rating'],
            'health_inspection_rating':row['health_inspection_rating'],'staffing_rating':row['staffing_rating'],
            'quality_measure_rating':row['quality_measure_rating'],'rating_footnotes':row['rating_footnotes'],
            'lon':row['lon'],'lat':row['lat'],
            'location_key':f"{row['source_longitude']},{row['source_latitude']}"}


@router.get('/catalog')
def catalog(db:Session=Depends(get_db)):
    try:
        return catalog_payload(db)
    finally:
        db.close()


def catalog_payload(db):
    config=load_registry()
    active=db.execute(text(f'''SELECT a.release_id FROM {S}.active_release a JOIN {S}.release r ON r.id=a.release_id
      WHERE a.dataset_id=:dataset AND r.status='published' '''),{'dataset':PRODUCT}).scalar_one_or_none()
    releases=db.execute(text(f'''SELECT id,source_release_id,source_after,report,report->>'retrieved_at' AS retrieved_at,
       semantic_sha256,schema_sha256,metadata_sha256,published_at FROM {S}.release
       WHERE dataset_id=:dataset AND status='published' ORDER BY published_at DESC'''),
       {'dataset':PRODUCT}).mappings().all()
    result={'dataset_id':PRODUCT,'name':config['name'],'publisher':config['publisher'],
            'source_url':config['landing_page'],'dictionary_url':config['dictionary_url'],
            'active_release_id':str(active) if active else None,'published_releases':[
              {**dict(r),'id':str(r['id'])} for r in releases],
            'clustering':config['clustering'],'footnotes':config['footnotes'],
            'rating_fields':config['rating_fields'],'limitations':config['limitations'],
            'coordinate_reference':config['location_policy'],'observation_period':None}
    if active:
        release=next(r for r in releases if r['id']==active)
        result['processing_date']=release['source_after']['modified']
        result['released_date']=release['source_after']['released']
        result['retrieved_at']=release['retrieved_at']
        result['counts']=release['report']['summary']
        options=_choices(db,active)
        result['filters']=[{'name':name,'label':label,'values':[{'code':v,'label':v,'default':True}
            for v in options[name]]} for name,label in [('provider_type','Provider type'),('ownership','Ownership type')]]
        result['filters'].append({'name':'overall','label':'Overall rating','values':[
            {'code':str(n),'label':f'{n} star'+('s' if n!=1 else ''),'default':True} for n in range(1,6)] +
            [{'code':'unrated','label':'Unrated','default':True}]})
    else:
        result['counts']={};result['filters']=[]
    return result


def map_payload(db,config,release_id,bbox,zoom,filters):
    release=_release(db,release_id);p=_params(release_id,bbox,filters)
    total=db.execute(text('SELECT count(*) '+WHERE),p).scalar_one()
    clustering=config['clustering'];base=_base(release_id,release,bbox,filters)|{
        'zoom':zoom,'total':total,'complete':True,'point_cap':clustering['point_cap']}
    if zoom>=clustering['point_min_zoom'] and total<=clustering['point_cap']:
        rows=db.execute(text(f'SELECT {SELECT} {WHERE} ORDER BY n.ccn LIMIT :cap'),
                        p|{'cap':clustering['point_cap']+1}).mappings().all()
        if len(rows)!=total: raise HTTPException(409,'Facility count changed during retrieval')
        return base|{'mode':'points','points':[_summary(r) for r in rows],'clusters':[]}
    cell=EARTH_CIRCUMFERENCE_M/(256*2**zoom)*clustering['cluster_cell_px']
    rows=db.execute(text(f'''SELECT floor(ST_X(t.m)/:cell)::bigint AS gx,floor(ST_Y(t.m)/:cell)::bigint AS gy,
      count(*) AS n,avg(t.lon) AS lon,avg(t.lat) AS lat,min(t.lon) AS west,min(t.lat) AS south,
      max(t.lon) AS east,max(t.lat) AS north FROM
      (SELECT ST_Transform(n.geom,3857) AS m,ST_X(n.geom) AS lon,ST_Y(n.geom) AS lat {WHERE}) t
      GROUP BY 1,2 ORDER BY 1,2 LIMIT :cap'''),p|{'cell':cell,'cap':clustering['cluster_cap']+1}).mappings().all()
    if len(rows)>clustering['cluster_cap']:
        raise HTTPException(413,'Viewport has too many clusters; zoom in')
    clusters=[{'id':f'{zoom}:{r["gx"]}:{r["gy"]}','count':r['n'],'lon':float(r['lon']),'lat':float(r['lat']),
               'bounds':[float(r['west']),float(r['south']),float(r['east']),float(r['north'])]} for r in rows]
    if sum(item['count'] for item in clusters)!=total:
        raise HTTPException(409,'Cluster counts differ from facility total')
    return base|{'mode':'clusters','points':[],'clusters':clusters,'cluster_cell_m':round(cell,3)}


@router.get('/map')
def map_data(release_id:UUID,bbox:str,zoom:int=Query(...,ge=0,le=22),provider_type:str|None=None,
             ownership:str|None=None,overall:str|None=None,db:Session=Depends(get_db)):
    try:
        _release(db,release_id)
        filters=parse_filters(_choices(db,release_id),provider_type,ownership,overall)
        return map_payload(db,load_registry(),release_id,bbox,zoom,filters)
    finally:
        db.close()


def table_payload(db,config,release_id,bbox,filters,limit,offset):
    if limit>config['clustering']['table_page_max']:
        raise HTTPException(400,'Table page limit exceeded')
    release=_release(db,release_id);p=_params(release_id,bbox,filters)
    total=db.execute(text('SELECT count(*) '+WHERE),p).scalar_one()
    rows=db.execute(text(f'''SELECT {SELECT} {WHERE} ORDER BY n.state_abbr,n.city,n.provider_name,n.ccn
      LIMIT :limit OFFSET :offset'''),p|{'limit':limit,'offset':offset}).mappings().all()
    return _base(release_id,release,bbox,filters)|{'total':total,'limit':limit,'offset':offset,
            'rows':[_summary(r) for r in rows]}


@router.get('/table')
def table(release_id:UUID,bbox:str,provider_type:str|None=None,ownership:str|None=None,
          overall:str|None=None,limit:int=Query(50,ge=1,le=500),offset:int=Query(0,ge=0,le=100000),
          db:Session=Depends(get_db)):
    try:
        _release(db,release_id)
        filters=parse_filters(_choices(db,release_id),provider_type,ownership,overall)
        return table_payload(db,load_registry(),release_id,bbox,filters,limit,offset)
    finally:
        db.close()


@router.get('/detail')
def detail(release_id:UUID,ccn:str=Query(...,min_length=6,max_length=6),bbox:str|None=None,
           provider_type:str|None=None,ownership:str|None=None,overall:str|None=None,
           db:Session=Depends(get_db)):
    try:
        return detail_payload(db,release_id,ccn,bbox,provider_type,ownership,overall)
    finally:
        db.close()


def detail_payload(db,release_id,ccn,bbox=None,provider_type=None,ownership=None,overall=None):
    release=_release(db,release_id);config=load_registry()
    filters=parse_filters(_choices(db,release_id),provider_type,ownership,overall)
    # Reuse the exact viewport and filter predicate when detail is opened from map or table.
    p=_params(release_id,bbox or '-180,-90,180,90',filters)|{'ccn':ccn}
    row=db.execute(text(f'''SELECT n.* ,ST_X(n.geom) AS lon,ST_Y(n.geom) AS lat,
       (SELECT count(*) FROM {S}.cms_nursing_home o WHERE o.release_id=n.release_id
        AND o.location_status='mapped' AND o.source_latitude=n.source_latitude
        AND o.source_longitude=n.source_longitude) AS facilities_at_location
       {WHERE} AND n.ccn=:ccn'''),p).mappings().one_or_none()
    if not row: raise HTTPException(404,'Facility is not mapped in this release and filter selection')
    return _base(release_id,release,bbox,filters)|{'ccn':row['ccn'],'provider_name':row['provider_name'],
       'address':row['provider_address'],'city':row['city'],'state':row['state_abbr'],'zip_code':row['zip_code'],
       'county_name':row['county_name'],'provider_type':row['provider_type'],'ownership_type':row['ownership_type'],
       'certified_beds':row['certified_beds'],'overall_rating':row['overall_rating'],
       'health_inspection_rating':row['health_inspection_rating'],'staffing_rating':row['staffing_rating'],
       'quality_measure_rating':row['quality_measure_rating'],'rating_footnotes':row['rating_footnotes'],
       'processing_date':str(row['processing_date']), 'location':{'lat':row['lat'],'lon':row['lon'],
         'source_latitude':row['source_latitude'],'source_longitude':row['source_longitude'],
         'geocoding_footnote':row['geocoding_footnote'],'facilities_at_location':row['facilities_at_location']},
       'care_compare_url':config['care_compare_pattern'].format(ccn=row['ccn']),
       'period_note':'Processing date is not a common observation period for the ratings.'}
