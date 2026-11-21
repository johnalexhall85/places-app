"""Read-only PostGIS verification for NCI cancer mortality on places_staging.

Writes no database rows and creates no databases. Skips cleanly when places_staging
is unreachable or has no active published ``nci_cancer_mortality_2020_2024`` release yet.
"""
import pytest
from sqlalchemy import text

from app.area_pilot import cancer_mortality_api, lookup
from app.area_pilot.cancer_mortality import load_registry
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
        pytest.skip('No active published nci_cancer_mortality_2020_2024 release in places_staging')
    yield db, release_id
    db.close()


def test_cancer_mortality_catalog_map_legend_table_and_lookup_on_staging(staging_release):
    db, release_id = staging_release
    cat = cancer_mortality_api.catalog(db)
    assert cat['dataset_id'] == 'nci_cancer_mortality_2020_2024'
    assert cat['active_release_id'] == str(release_id)
    assert cat['limitations'] == CONFIG['limitations']

    measure = CONFIG['measures'][0]
    west, south, east, north = map(float, NC_BBOX.split(','))
    for level in ('state', 'county'):
        cfg, m = cancer_mortality_api.selection(
            db, CONFIG['dataset_id'], release_id, measure['measure_id'],
            measure['observation_period'], measure['population'], CONFIG['value_type'], level,
        )
        assert cfg['dataset_id'] == 'nci_cancer_mortality_2020_2024'
        assert m['measure_id'] == 'cancer_death_rate_all'
        p = {
            'release': release_id, 'measure': measure['measure_id'],
            'period': measure['observation_period'], 'population': measure['population'],
            'value_type': CONFIG['value_type'], 'level': level,
            'west': west, 'south': south, 'east': east, 'north': north,
        }
        count = cancer_mortality_api.ensure_cap(db, p)
        assert count > 0
        base = cancer_mortality_api.metadata(CONFIG, measure, release_id, level, NC_BBOX)
        mapped = cancer_mortality_api.map_data(db, p, count, base, 0.01)
        table = cancer_mortality_api.table(db, p, base, count, 500, 0)
        legend = cancer_mortality_api.legend(db, p, base)
        assert mapped['count'] == count == table['total']
        assert sum(s['n'] for s in legend['statuses']) == count
        assert legend['national_reference']['value'] == 143.2
        assert len(legend['quantile_breaks']) == 4

    vals = lookup.area_values(
        db, 'county', ['37063', '09110'],
        products=['nci_cancer_mortality'],
    )['values']
    by_key = {(r['geoid'], r['measure_id']): r for r in vals}
    assert by_key[('37063', 'cancer_death_rate_all')]['value'] == 132.6
    assert by_key[('37063', 'cancer_death_rate_all')]['uncertainty']['low'] == 127.2
    assert by_key[('37063', 'cancer_death_rate_all')]['uncertainty']['high'] == 138.2
    assert by_key[('09110', 'cancer_death_rate_all')]['status'] == lookup.NOT_IN_RELEASE
    assert by_key[('09110', 'cancer_death_rate_all')]['value'] is None

    nat = {
        r['measure_id']: r['value']
        for r in lookup.national_reference(db)
        if r['product'] == 'nci_cancer_mortality'
    }
    assert nat == {
        'cancer_death_rate_all': 143.2,
        'cancer_death_rate_lung': 30.2,
        'cancer_death_rate_colorectal': 12.7,
    }
