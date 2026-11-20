"""Read-only PostGIS verification for FEMA NRI v1.20 against places_staging.

Writes no database rows and creates no databases. Skips cleanly when places_staging
is unreachable or has no active published ``fema_nri_v120`` release yet.
"""
import pytest
from sqlalchemy import text

from app.area_pilot import fema_nri_area_api, lookup
from app.area_pilot.fema_nri_area import load_registry
from app.db import SessionLocal

CONFIG = load_registry()
CT_BBOX = '-72.9,41.6,-72.5,41.9'


@pytest.fixture(scope='module')
def staging_release():
    db = SessionLocal()
    try:
        release_id = db.execute(text('''SELECT a.release_id FROM area_pilot.active_release a
            JOIN area_pilot.release r ON r.id=a.release_id
            WHERE a.dataset_id=:dataset AND r.status='published' '''),
            {'dataset': CONFIG['dataset_id']}).scalar_one_or_none()
    except Exception as exc:
        db.close()
        pytest.skip(f'places_staging unreachable: {type(exc).__name__}')
    if release_id is None:
        db.close()
        pytest.skip('No active published fema_nri_v120 release in places_staging')
    yield db, release_id
    db.close()


def test_fema_nri_catalog_map_legend_table_and_lookup_on_staging(staging_release):
    db, release_id = staging_release
    cat = fema_nri_area_api.catalog(db)
    assert cat['dataset_id'] == 'fema_nri_v120'
    assert cat['active_release_id'] == str(release_id)
    assert cat['limitations'] == CONFIG['limitations']

    by_id = {m['measure_id']: m for m in CONFIG['measures']}
    eal = by_id['eal_score']
    west, south, east, north = map(float, CT_BBOX.split(','))
    for level in ('state', 'county', 'tract'):
        cfg, m = fema_nri_area_api.selection(
            db, CONFIG['dataset_id'], release_id, eal['measure_id'],
            eal['observation_period'], eal['population'], CONFIG['value_type'], level)
        assert cfg['dataset_id'] == 'fema_nri_v120' and m['measure_id'] == 'eal_score'
        p = {'release': release_id, 'measure': eal['measure_id'],
             'period': eal['observation_period'], 'population': eal['population'],
             'value_type': CONFIG['value_type'], 'level': level,
             'west': west, 'south': south, 'east': east, 'north': north}
        count = fema_nri_area_api.ensure_cap(db, p)
        assert count > 0
        base = fema_nri_area_api.metadata(CONFIG, eal, release_id, level, CT_BBOX)
        mapped = fema_nri_area_api.map_data(db, p, count, base, 0.005)
        table = fema_nri_area_api.table(db, p, base, count, 500, 0)
        legend = fema_nri_area_api.legend(db, p, base)
        assert mapped['count'] == count == table['total']
        assert sum(s['n'] for s in legend['statuses']) == count
        assert all('rating' in f['properties'] for f in mapped['features'])

    state_vals = lookup.area_values(db, 'state', ['09'], products=['fema_nri'])
    assert {r['measure_id'] for r in state_vals['values']} == {'eal_score', 'eal_valt'}
    county_vals = lookup.area_values(db, 'county', ['09110'], products=['fema_nri'], measure_ids=['risk_score'])
    assert county_vals['values'][0]['notes'].get('rating') is not None
