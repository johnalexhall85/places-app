"""Read-only PostGIS verification for CDC heart disease and stroke mortality on places_staging.

Writes no database rows and creates no databases. Skips cleanly when places_staging
is unreachable or has no active published ``cdc_hds_mortality_2022_2024`` release yet.
"""
import pytest
from sqlalchemy import text

from app.area_pilot import hds_mortality_api, lookup
from app.area_pilot.hds_mortality import load_registry
from app.db import SessionLocal

CONFIG = load_registry()
# Small viewport around Durham County, NC (37063).
NC_BBOX = '-79.2,35.8,-78.6,36.3'


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
        pytest.skip('No active published cdc_hds_mortality_2022_2024 release in places_staging')
    yield db, release_id
    db.close()


def test_hds_mortality_catalog_map_legend_table_and_lookup_on_staging(staging_release):
    db, release_id = staging_release
    cat = hds_mortality_api.catalog(db)
    assert cat['dataset_id'] == 'cdc_hds_mortality_2022_2024'
    assert cat['active_release_id'] == str(release_id)
    assert cat['limitations'] == CONFIG['limitations']

    measure = CONFIG['measures'][0]
    west, south, east, north = map(float, NC_BBOX.split(','))
    for level in ('state', 'county'):
        vt = CONFIG['value_type_by_level'][level]
        cfg, m = hds_mortality_api.selection(
            db, CONFIG['dataset_id'], release_id, measure['measure_id'],
            measure['observation_period'], measure['population'], vt, level,
        )
        assert cfg['dataset_id'] == 'cdc_hds_mortality_2022_2024'
        assert m['measure_id'] == 'heart_disease_death_rate'
        p = {
            'release': release_id, 'measure': measure['measure_id'],
            'period': measure['observation_period'], 'population': measure['population'],
            'value_type': vt, 'level': level,
            'west': west, 'south': south, 'east': east, 'north': north,
        }
        count = hds_mortality_api.ensure_cap(db, p)
        assert count > 0
        base = hds_mortality_api.metadata(CONFIG, measure, release_id, level, NC_BBOX)
        mapped = hds_mortality_api.map_data(db, p, count, base, 0.01)
        table = hds_mortality_api.table(db, p, base, count, 500, 0)
        legend = hds_mortality_api.legend(db, p, base)
        assert mapped['count'] == count == table['total']
        assert sum(s['n'] for s in legend['statuses']) == count
        assert legend['national_reference']['value'] == 315.3
        assert len(legend['quantile_breaks']) == 4

    vals = lookup.area_values(
        db, 'county', ['37063', '09110'],
        products=['cdc_hds_mortality'],
    )['values']
    by_key = {(r['geoid'], r['measure_id']): r for r in vals}
    assert by_key[('37063', 'heart_disease_death_rate')]['value'] == 227.2
    assert by_key[('37063', 'stroke_death_rate')]['value'] == 71.2
    assert by_key[('09110', 'heart_disease_death_rate')]['status'] == lookup.NOT_IN_RELEASE
    assert by_key[('09110', 'heart_disease_death_rate')]['value'] is None

    nat = {
        r['measure_id']: r['value']
        for r in lookup.national_reference(db)
        if r['product'] == 'cdc_hds_mortality'
    }
    assert nat == {'heart_disease_death_rate': 315.3, 'stroke_death_rate': 75.9}
