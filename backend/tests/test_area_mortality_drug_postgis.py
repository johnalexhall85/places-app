"""Read-only PostGIS verification for NCHS drug poisoning mortality on places_staging.

Writes no database rows and creates no databases. Skips cleanly when places_staging
is unreachable or has no active published ``nchs_drug_poisoning_2021`` release yet.
"""
import pytest
from sqlalchemy import text

from app.area_pilot import drug_poisoning_api, lookup
from app.area_pilot.drug_poisoning import load_registry
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
        pytest.skip('No active published nchs_drug_poisoning_2021 release in places_staging')
    yield db, release_id
    db.close()


def test_drug_poisoning_catalog_map_legend_table_and_lookup_on_staging(staging_release):
    db, release_id = staging_release
    cat = drug_poisoning_api.catalog(db)
    assert cat['dataset_id'] == 'nchs_drug_poisoning_2021'
    assert cat['active_release_id'] == str(release_id)
    assert cat['limitations'] == CONFIG['limitations']

    measure = CONFIG['measures'][0]
    west, south, east, north = map(float, NC_BBOX.split(','))
    cfg, m = drug_poisoning_api.selection(
        db, CONFIG['dataset_id'], release_id, measure['measure_id'],
        measure['observation_period'], measure['population'], CONFIG['value_type'], 'county',
    )
    assert cfg['dataset_id'] == 'nchs_drug_poisoning_2021'
    assert m['measure_id'] == 'drug_poisoning_death_rate'
    p = {
        'release': release_id, 'measure': measure['measure_id'],
        'period': measure['observation_period'], 'population': measure['population'],
        'value_type': CONFIG['value_type'], 'level': 'county',
        'west': west, 'south': south, 'east': east, 'north': north,
    }
    count = drug_poisoning_api.ensure_cap(db, p)
    assert count > 0
    base = drug_poisoning_api.metadata(CONFIG, measure, release_id, 'county', NC_BBOX)
    mapped = drug_poisoning_api.map_data(db, p, count, base, 0.01)
    table = drug_poisoning_api.table(db, p, base, count, 500, 0)
    legend = drug_poisoning_api.legend(db, p, base)
    assert mapped['count'] == count == table['total']
    assert sum(s['n'] for s in legend['statuses']) == count
    assert legend['national_reference'] is None
    assert len(legend['quantile_breaks']) == 4

    vals = lookup.area_values(
        db, 'county', ['37063', '09110'],
        products=['nchs_drug_poisoning'],
    )['values']
    by_key = {(r['geoid'], r['measure_id']): r for r in vals}
    durham = by_key[('37063', 'drug_poisoning_death_rate')]
    assert durham['value'] == 23.87115
    assert durham['uncertainty'] == {
        'kind': 'ci95', 'low': 22.12165, 'high': 25.75957,
        'label': "95% interval from NCHS's model",
    }
    assert by_key[('09110', 'drug_poisoning_death_rate')]['status'] == lookup.NOT_IN_RELEASE
    assert by_key[('09110', 'drug_poisoning_death_rate')]['value'] is None
