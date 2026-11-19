"""Profile-chart lookup helpers (docs/profile-viz/CHART_CONTRACT.md section 3). Staging database only."""
import os

import pytest

from app.area_pilot import lookup, national
from app.db import DATABASE_URL, SessionLocal

pytestmark = pytest.mark.skipif(not os.getenv('DATABASE_URL', DATABASE_URL).endswith('/places_staging'),
                                reason='staging database only')

KEYS = [('places', 'diabetes_crudeprev'), ('places', 'bphigh_crudeprev'), ('places', 'dental_crudeprev'),
        ('acs', 'B19013_001E'), ('acs_profile', 'poverty_pct'), ('acs_profile', 'total_population'),
        ('cms_gv', 'std_payment_per_capita'), ('ahrf', 'hosp_23'), ('clh', 'CCBP_SOGS_RATE'),
        ('epa_aqi', 'median_aqi'), ('usda_fea', 'snap_stores_per_1000')]


@pytest.fixture(scope='module')
def db():
    with SessionLocal() as session:
        yield session


@pytest.mark.parametrize('level,geoid,keys', [
    ('county', '01063', KEYS), ('county', '09003', KEYS[:6]), ('state', '01', [('brfss', 'diabetes'), ('brfss', 'uninsured_18_64'),
     ('acs', 'B19013_001E'), ('cms_gv', 'readmission_rate')]), ('cd', '5401', [('acs_profile', 'poverty_pct')])])
def test_matches_area_measure_series(db, level, geoid, keys):
    many = lookup.area_series_many(db, level, geoid, keys)
    assert list(many) == [f'{p}:{m}' for p, m in keys]
    for product, measure_id in keys:
        assert many[f'{product}:{measure_id}'] == lookup.area_measure_series(db, level, geoid, product, measure_id)


def test_unknown_measure_raises(db):
    with pytest.raises(lookup.LookupError_):
        lookup.area_series_many(db, 'county', '01063', [('places', 'nope')])


def test_comparability_rules():
    assert lookup.comparability('places')['state_marker_levels'] == []
    assert lookup.comparability('places')['trend_style'] == 'dots_ci'
    assert lookup.comparability('acs', 'B19013_001E')['state_marker_levels'] == ['county', 'cd']
    for product, measure_id in [('acs_profile', 'total_population'), ('cms_gv', 'om_beneficiaries'), ('ahrf', 'hosp_23')]:
        rule = lookup.comparability(product, measure_id)
        assert rule['state_marker_levels'] == [] and rule['national_marker_levels'] == [] and rule['count_measure']
    with pytest.raises(lookup.LookupError_):
        lookup.comparability('hrsa_hc_sites')


def test_national_series_shape(db):
    result = lookup.national_series(db, 'acs', 'B19013_001E')
    assert result['geoid'] == 'US' and result['level'] == 'national'
    periods = [r['period'] for r in result['series']]
    assert periods == sorted(periods)
    if result['release'] is not None:
        assert periods[-1] == '2020–2024' and result['series'][-1]['current_period']
        assert all(r['uncertainty']['kind'] == 'moe90' for r in result['series'])


def test_acs_plan_covers_every_window():
    for product in ('acs', 'acs_profile'):
        plan = national.acs_plan(product)
        assert list(plan) == ['2019', '2020', '2021', '2022', '2023', '2024']


def test_parse_acs_us_row():
    entries = national.acs_plan('acs')['2024']
    header = national._fields(entries) + ['us']
    row = ['United States', '80734', '149', '', ''] + ['1']
    (parsed,) = national.parse_acs('acs', '2024', [header, row])
    assert parsed['value'] == 80734 and parsed['moe'] == 149 and parsed['status'] == 'available'
    with pytest.raises(ValueError):
        national.parse_acs('acs', '2024', [header, row[:-1] + ['0']])
