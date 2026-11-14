"""Isolated PostGIS lifecycle test for CMS Original Medicare GV release controls and map parity."""
import copy
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.area_pilot import cms_gv_api as api
from app.area_pilot import cms_gv_cli as cli
from app.area_pilot.cms_gv import file_evidence, load_registry
from app.db import DATABASE_URL

VERSIONS = Path(__file__).resolve().parents[1] / 'alembic' / 'versions'
TEST_DB = 'chip_cms_om_gv_test'
BASE = load_registry()
FIELDS = [m['source_field'] for m in BASE['measures']]
HEADER = BASE['source_dimensions'] + FIELDS + ['BENE_FEML_PCT']
CONFIG = copy.deepcopy(BASE)
CONFIG['expected_levels'] = {'National': 1, 'State': 6, 'County': 4}
for rule in CONFIG['expected_source_exclusions']:
    if 'expected_count' in rule:
        rule['expected_count'] = 1
CONFIG['expected_boundary_without_source'] = [
    {'level': 'county', 'code_pattern': '^11001$', 'reason': 'cms_publishes_dc_at_state_level_only', 'expected_count': 1},
    {'level': 'county', 'code_pattern': '^72[0-9]{3}$', 'reason': 'cms_publishes_puerto_rico_at_state_level_only',
     'expected_count': 1}]
BOX = {'01': (-88, 30, -85, 35), '11': (-77.2, 38.8, -76.9, 39.0), '72': (-67.5, 17.8, -65.5, 18.6),
       '01001': (-87, 32, -86, 33), '01003': (-88, 30, -87, 31), '11001': (-77.2, 38.8, -76.9, 39.0),
       '72001': (-67, 18, -66.5, 18.3)}


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def engine():
    admin = create_engine(make_url(DATABASE_URL).set(database='postgres'), isolation_level='AUTOCOMMIT')
    try:
        with admin.connect() as conn:
            conn.execute(text('DROP DATABASE IF EXISTS ' + TEST_DB))
            conn.execute(text('CREATE DATABASE ' + TEST_DB))
    except Exception as exc:
        pytest.skip('PostGIS scratch database unavailable: ' + type(exc).__name__)
    test_engine = create_engine(make_url(DATABASE_URL).set(database=TEST_DB))
    with test_engine.begin() as conn:
        conn.execute(text('CREATE EXTENSION postgis'))
        with Operations.context(MigrationContext.configure(conn)):
            migration('a91c7e3f2b40_add_area_pilot').upgrade()
        conn.execute(text('''CREATE FUNCTION area_pilot.prevent_published_data_change()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE target_release uuid;
            BEGIN
              target_release := CASE WHEN TG_OP = 'INSERT' THEN NEW.release_id ELSE OLD.release_id END;
              IF EXISTS (SELECT 1 FROM area_pilot.release WHERE id=target_release AND status='published') THEN
                RAISE EXCEPTION 'Published data are immutable';
              END IF;
              IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
              RETURN NEW;
            END $$'''))
        conn.execute(text('''CREATE TABLE area_pilot.acs_boundary_2024
            (level text, geoid varchar(12), name text, source_sha256 varchar(64), geom geometry(MultiPolygon,4326))'''))
        for geoid, (w, s, e, n) in BOX.items():
            conn.execute(text('''INSERT INTO area_pilot.acs_boundary_2024 VALUES
                (:level,:geoid,:name,'x',ST_Multi(ST_MakeEnvelope(:w,:s,:e,:n,4326)))'''),
                {'level': 'state' if len(geoid) == 2 else 'county', 'geoid': geoid, 'name': 'Area ' + geoid,
                 'w': w, 's': s, 'e': e, 'n': n})
        with Operations.context(MigrationContext.configure(conn)):
            migration('b7e3c5a9d2f4_add_cms_om_gv_area').upgrade()
        # A different product's pointer that must never move.
        conn.execute(text('''INSERT INTO area_pilot.release (id,dataset_id,source_release_id,status,semantic_sha256,
            schema_sha256,metadata_sha256,keyset_sha256,source_before,source_after,report,published_at)
            VALUES ('00000000-0000-0000-0000-000000000001','epa_airdata_aqi_county_2025','x','published',
            'a','b','c','d','{}','{}','{}',now())'''))
        conn.execute(text('''INSERT INTO area_pilot.active_release (dataset_id,release_id)
            VALUES ('epa_airdata_aqi_county_2025','00000000-0000-0000-0000-000000000001')'''))
    yield test_engine
    test_engine.dispose()
    with admin.connect() as conn:
        conn.execute(text('DROP DATABASE IF EXISTS ' + TEST_DB + ' WITH (FORCE)'))
    admin.dispose()


def rec(level, code, desc, values=('4000', '12527.77', '230.5', '600.25', '0.2069'), female='0.5'):
    return dict(zip(HEADER, ['2024', level, desc, code, 'All', *values, female]))


def records(al_count='370678', extra=None):
    rows = [rec('National', '', 'National', ('27732177', '12553.26', '224.8391', '590.5484', '0.1807'), '0.546'),
            rec('State', '01', 'AL', (al_count, '11000.5', '210.1', '600.2', '0.1764')),
            rec('State', '11', 'DC', ('47529', '13000', '250', '700', '0.2038')),
            rec('State', '72', 'PR', ('26979', '6685.46', '148.218', '390.8596', '0.1589')),
            rec('State', '78', 'VI', ('12643', '6000', '120', '440', '0.1952')),
            rec('State', '', 'Territory', ('*',) * 5), rec('State', '', 'ZZ', ('*',) * 5),
            rec('County', '01001', 'AL-Autauga', ('4000', '12527.77', '230.5', '600.25', '*')),
            rec('County', '01003', 'AL-Baldwin', ('30000', '11000', '200', '500', '0')),
            rec('County', '01000', 'AL-UNKNOWN', ('*',) * 5),
            rec('County', '78010', 'VI-St. Croix', ('6266', '6924.36', '131.6629', '465.0495', '0.1978'))]
    rows += extra or []
    return {(r['BENE_GEO_LVL'], r['BENE_GEO_CD'], r['BENE_GEO_DESC']): r for r in rows}


def stub(selected, tmp_path):
    def retrieved(directory):
        directory.mkdir(parents=True)
        files = []
        for role in sorted(cli.REQUIRED_ROLES):
            path = directory / (role + '.bin')
            path.write_text('evidence ' + role)
            files.append(file_evidence(path, 'https://data.cms.gov/synthetic/' + role, role))
        levels = {}
        for level, _, _ in selected:
            levels[f'{level}|All'] = levels.get(f'{level}|All', 0) + 1
        stats = {'header_sha256': CONFIG['expected_header_sha256'], 'latest_year': '2024',
                 'selected_year_age_counts': levels | {'State|<65': 6, 'State|>=65': 6}}
        provenance = {'api_cross_check': {'passed': True}, 'catalog_entry': {'modified': '2026-05-15'},
                      'retrieved_at': datetime.now(timezone.utc).isoformat()}
        return selected, stats, files, provenance
    return retrieved


def pointer(engine, dataset=CONFIG['dataset_id']):
    with engine.connect() as conn:
        value = conn.execute(text('SELECT release_id FROM area_pilot.active_release WHERE dataset_id=:d'),
                             {'d': dataset}).scalar_one_or_none()
    return str(value) if value else None


def selection_params(release, measure, level, bbox='-180,-85,180,85'):
    west, south, east, north = map(float, bbox.split(','))
    return {'release': release, 'measure': measure['measure_id'], 'period': measure['observation_period'],
            'population': measure['population'], 'value_type': CONFIG['value_type'], 'level': level,
            'west': west, 'south': south, 'east': east, 'north': north}


def test_full_lifecycle(engine, tmp_path):
    other = pointer(engine, 'epa_airdata_aqi_county_2025')
    first, report = cli.fetch_stage(engine, CONFIG, tmp_path, stub(records(), tmp_path))
    assert report['status'] == 'ready', report['checks']
    assert report['matched'] == {'state': 3, 'county': 2}
    assert report['observation_count'] == (1 + 3 + 2) * 5
    assert report['boundary_without_source_observation'] == {
        'cms_publishes_dc_at_state_level_only': 1, 'cms_publishes_puerto_rico_at_state_level_only': 1}
    assert set(report['source_rows_without_compatible_boundary'].values()) == {
        'territory_outside_chip_2024_boundary_layer', 'non_fips_state_aggregate', 'unknown_county_of_residence'}

    # Idempotent: identical content records a duplicate run against the same candidate.
    again, duplicate = cli.fetch_stage(engine, CONFIG, tmp_path, stub(records(), tmp_path))
    assert again == first and duplicate['status'] == 'duplicate'

    reviewed = cli.review(engine, first, CONFIG)
    assert reviewed['observations_verified'] == 30 and reviewed['staged_rows'] == 11
    with pytest.raises(ValueError, match='reviewed checksums'):
        cli.publish(engine, CONFIG, first, report['semantic_sha256'], report['schema_sha256'], 'wrong')
    assert pointer(engine) is None
    cli.publish(engine, CONFIG, first, report['semantic_sha256'], report['schema_sha256'], report['metadata_sha256'])
    assert pointer(engine) == str(first) and pointer(engine, 'epa_airdata_aqi_county_2025') == other

    # Representative cells: source string, stored numeric, and status at both levels.
    with engine.connect() as conn:
        cells = {(r.geo_level, r.geoid, r.measure_id): (r.source_value, r.value, r.status) for r in conn.execute(text(
            'SELECT geo_level,geoid,measure_id,source_value,value,status FROM area_pilot.observation_cms_gv '
            'WHERE release_id=:r'), {'r': first})}
    assert cells[('state', '01', 'om_beneficiaries')][:2] == ('370678', 370678)
    assert cells[('county', '01001', 'readmission_rate')] == ('*', None, 'suppressed')
    assert cells[('county', '01003', 'readmission_rate')][2] == 'true_zero'
    assert float(cells[('national', 'US', 'readmission_rate')][1]) == 0.1807
    assert ('state', '78', 'om_beneficiaries') not in cells and ('county', '01000', 'om_beneficiaries') not in cells

    # Read API at both levels: map, legend, and table agree; the national row is never a feature.
    with engine.connect() as conn:
        for level, expected in (('state', ['01', '11', '72']), ('county', ['01001', '01003', '11001', '72001'])):
            measure = CONFIG['measures'][-1]
            p = selection_params(first, measure, level)
            base = api.metadata(CONFIG, measure, first, level, '-180,-85,180,85')
            count = api.ensure_cap(conn, p)
            mapped, table, legend = (api.map_data(conn, p, count, base, 0.01), api.table(conn, p, base, count, 100, 0),
                                     api.legend(conn, p, base))
            ids = [f['properties']['geography_id'] for f in mapped['features']]
            assert ids == expected == [r['geography_id'] for r in table['rows']]
            assert [f['properties']['status'] for f in mapped['features']] == [r['status'] for r in table['rows']]
            assert sum(s['n'] for s in legend['statuses']) == count == table['total']
            assert legend['national_reference']['value'] == 0.1807
        county = {f['properties']['geography_id']: f['properties'] for f in mapped['features']}
        assert county['11001']['status'] == 'not_published' and county['72001']['status'] == 'not_published'
        assert county['01001']['status'] == 'suppressed' and county['01001']['value'] is None
        assert county['01003']['value'] == 0 and county['01003']['status'] == 'true_zero'
        local = selection_params(first, CONFIG['measures'][0], 'county', '-87.5,31.5,-85.5,33.5')
        assert api.ensure_cap(conn, local) == 1

    # Published rows are immutable.
    with pytest.raises(Exception, match='immutable'):
        with engine.begin() as conn:
            conn.execute(text("UPDATE area_pilot.observation_cms_gv SET source_value='1' WHERE release_id=:r"), {'r': first})

    # A failed retrieval and an unexplained geography both hold without touching any pointer.
    def broken(_directory):
        raise RuntimeError('CMS download failed after 3 attempts')
    failed, failure = cli.fetch_stage(engine, CONFIG, tmp_path, broken)
    assert failure['status'] == 'held'
    unknown = records(extra=[rec('County', '01005', 'AL-Barbour')])
    mismatch_id, mismatch = cli.fetch_stage(engine, CONFIG | {'expected_levels': {'National': 1, 'State': 6, 'County': 5}},
                                            tmp_path, stub(unknown, tmp_path))
    assert mismatch['status'] == 'held' and mismatch['hold_reason'] == 'geography_mismatch'
    assert ['County', '01005', 'AL-Barbour'] in mismatch['unexplained']
    with pytest.raises(ValueError, match='not ready'):
        cli.publish(engine, CONFIG, mismatch_id, mismatch['semantic_sha256'], mismatch['schema_sha256'],
                    mismatch['metadata_sha256'])
    assert pointer(engine) == str(first)

    # Revised content under the same label is held, then released only by checksum-bound review.
    revised, revision = cli.fetch_stage(engine, CONFIG, tmp_path, stub(records(al_count='370679'), tmp_path))
    assert revision['status'] == 'held' and revision['hold_reason'] == 'same_label_semantic_revision'
    with pytest.raises(ValueError, match='not ready'):
        cli.publish(engine, CONFIG, revised, revision['semantic_sha256'], revision['schema_sha256'],
                    revision['metadata_sha256'])
    assert pointer(engine) == str(first)
    digests = (revision['semantic_sha256'], revision['schema_sha256'], revision['metadata_sha256'])
    cli.release_reviewed_hold(engine, CONFIG, revised, *digests, 'Reviewed CMS same-label revision')
    cli.publish(engine, CONFIG, revised, *digests)
    assert pointer(engine) == str(revised)

    # Rollback and deactivation affect only this product; failed candidate is never a target.
    with pytest.raises(ValueError, match='retained published'):
        cli.set_pointer(engine, CONFIG, 'rollback', failed)
    with pytest.raises(ValueError, match='retained published'):
        cli.set_pointer(engine, CONFIG, 'rollback', '00000000-0000-0000-0000-000000000001')
    cli.set_pointer(engine, CONFIG, 'rollback', first)
    assert pointer(engine) == str(first)
    cli.set_pointer(engine, CONFIG, 'deactivate')
    assert pointer(engine) is None and pointer(engine, 'epa_airdata_aqi_county_2025') == other
    cli.set_pointer(engine, CONFIG, 'rollback', first)
    assert pointer(engine) == str(first)

    with engine.connect() as conn:
        with pytest.raises(HTTPException) as error:
            api.selection(conn, CONFIG['dataset_id'], failed, 'om_beneficiaries', '2024',
                          CONFIG['measures'][0]['population'], CONFIG['value_type'], 'county')
        assert error.value.status_code == 404
