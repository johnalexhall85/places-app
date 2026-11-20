"""Read-only PostGIS verification for CDC/ATSDR SVI 2022 against places_staging.

Writes no database rows and creates no databases. Skips cleanly when places_staging
is unreachable or has no active published ``cdc_svi_2022`` release yet.
"""
import pytest
from sqlalchemy import text

from app.area_pilot import lookup, svi_api
from app.area_pilot.svi import load_registry
from app.db import SessionLocal

CONFIG = load_registry()
# Small viewport around Hartford / Capitol Planning Region, CT (09110).
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
        pytest.skip('No active published cdc_svi_2022 release in places_staging')
    yield db, release_id
    db.close()


def test_svi_catalog_map_legend_table_and_lookup_on_staging(staging_release):
    db, release_id = staging_release
    cat = svi_api.catalog(db)
    assert cat['dataset_id'] == 'cdc_svi_2022'
    assert cat['active_release_id'] == str(release_id)
    assert cat['limitations'] == CONFIG['limitations']

    measure = CONFIG['measures'][0]
    west, south, east, north = map(float, CT_BBOX.split(','))
    for level in ('county', 'tract'):
        cfg, m = svi_api.selection(db, CONFIG['dataset_id'], release_id, measure['measure_id'],
                                   measure['observation_period'], measure['population'],
                                   CONFIG['value_type'], level)
        assert cfg['dataset_id'] == 'cdc_svi_2022' and m['measure_id'] == 'rpl_themes'
        p = {'release': release_id, 'measure': measure['measure_id'],
             'period': measure['observation_period'], 'population': measure['population'],
             'value_type': CONFIG['value_type'], 'level': level,
             'west': west, 'south': south, 'east': east, 'north': north}
        count = svi_api.ensure_cap(db, p)
        assert count > 0
        base = svi_api.metadata(CONFIG, measure, release_id, level, CT_BBOX)
        mapped = svi_api.map_data(db, p, count, base, 0.005)
        table = svi_api.table(db, p, base, count, 500, 0)
        legend = svi_api.legend(db, p, base)
        assert mapped['count'] == count == table['total']
        assert sum(s['n'] for s in legend['statuses']) == count
        assert base['legend_breaks'] == [0.25, 0.5, 0.75]

    # Single-place lookup reads published county and tract ranks and marks Puerto Rico not_in_release.
    county_vals = lookup.area_values(db, 'county', ['09110', '72001'], products=['cdc_svi'], measure_ids=['rpl_themes'])
    by_geoid = {r['geoid']: r for r in county_vals['values']}
    assert by_geoid['09110']['status'] in ('available', 'true_zero')
    assert 0 <= by_geoid['09110']['value'] <= 1
    assert by_geoid['09110']['uncertainty']['kind'] == 'none'
    assert by_geoid['72001']['status'] == lookup.NOT_IN_RELEASE and by_geoid['72001']['value'] is None

    tracts = lookup.county_tract_values(db, '09110', 'cdc_svi', 'rpl_themes')
    assert len(tracts['values']) > 0
    for row in tracts['values']:
        if row['status'] == 'not_available':
            assert row['value'] is None
            assert row['status_text'] == 'Not ranked by CDC (−999 in the source file)'
        else:
            assert 0 <= row['value'] <= 1
