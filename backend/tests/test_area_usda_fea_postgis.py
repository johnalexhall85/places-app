"""Isolated PostGIS lifecycle test for the USDA Food Environment Atlas release controls and map parity."""
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

from app.area_pilot import usda_fea_api as api
from app.area_pilot import usda_fea_cli as cli
from app.area_pilot.usda_fea import MEASURE_IDS, file_evidence, load_registry
from app.db import DATABASE_URL

VERSIONS = Path(__file__).resolve().parents[1] / 'alembic' / 'versions'
TEST_DB = 'chip_usda_fea_test'
BASE = load_registry()
CONFIG = copy.deepcopy(BASE)
CONFIG['expected_source_only'] = [
    {'fips': ['09001'], 'measures': MEASURE_IDS, 'reason': 'legacy_ct_county_no_compatible_2024_boundary'},
    {'no_fips_state': 'AK', 'counties': ['Kenai Peninsula Area'], 'measures': ['farmers_markets_per_1000'],
     'reason': 'no_fips_alaska_agricultural_area', 'expected_value': '-8888'}]
for _rule in CONFIG['expected_boundary_only']:
    _rule['expected_count'] = 1
CONFIG['expected_source_rows'] = 100
CONFIG['expected_variable_count'] = 10
BOX = {'01001': (-87, 32, -86, 33), '01003': (-88, 30, -87, 31), '09110': (-73, 41.5, -72.5, 42),
       '72001': (-67, 18, -66.5, 18.3), '01': (-88, 30, -85, 35)}
OTHER = '00000000-0000-0000-0000-000000000001'


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
            migration('c8f1e4a7d3b6_add_usda_fea_area').upgrade()
        # A different product's pointer that must never move.
        conn.execute(text('''INSERT INTO area_pilot.release (id,dataset_id,source_release_id,status,semantic_sha256,
            schema_sha256,metadata_sha256,keyset_sha256,source_before,source_after,report,published_at)
            VALUES (:id,'cms_om_geographic_variation','x','published','a','b','c','d','{}','{}','{}',now())'''),
            {'id': OTHER})
        conn.execute(text('''INSERT INTO area_pilot.active_release (dataset_id,release_id)
            VALUES ('cms_om_geographic_variation',:id)'''), {'id': OTHER})
    yield test_engine
    test_engine.dispose()
    with admin.connect() as conn:
        conn.execute(text('DROP DATABASE IF EXISTS ' + TEST_DB + ' WITH (FORCE)'))
    admin.dispose()


def lookup():
    return {m['variable_code']: {'Variable_Name': m['variable_name'], 'Category_Name': m['category'],
                                 'Category_Code': 'X', 'Subcategory_Name': m['subcategory'],
                                 'Variable_Code': m['variable_code'], 'Units': m['source_units']}
            for m in CONFIG['measures']}


def rows(snap_autauga='1.25', extra=()):
    values = {'01001': {'PCT_LACCESS_LOWI19': '13.020998', 'SNAPSPTH23': snap_autauga, 'WICSPTH22': '0.2',
                        'FMRKTPTH18': '0', 'PCT_LACCESS_HHNV19': '2.5'},
              '01003': {'PCT_LACCESS_LOWI19': '0', 'SNAPSPTH23': '-9999', 'WICSPTH22': 'N/A',
                        'FMRKTPTH18': '0.04', 'PCT_LACCESS_HHNV19': '-9999'},
              '09001': {code: '3.5' if code.startswith('PCT') else '-9999' for code in lookup()}}
    result = {}
    for fips, by_code in values.items():
        for code, value in by_code.items():
            result[(fips, code)] = {'fips': fips, 'state': 'AL' if fips < '02' else 'CT',
                                    'county': 'County ' + fips, 'variable_code': code, 'value': value}
    result[('09110', 'FMRKTPTH18')] = {'fips': '09110', 'state': 'CT', 'county': 'Capitol',
                                       'variable_code': 'FMRKTPTH18', 'value': '-8888'}
    result[('N/A|AK|Kenai Peninsula Area', 'FMRKTPTH18')] = {
        'fips': 'N/A', 'state': 'AK', 'county': 'Kenai Peninsula Area', 'variable_code': 'FMRKTPTH18',
        'value': '-8888'}
    for key, row in extra:
        result[key] = row
    return result


def stub(selected, stats=None):
    def retrieved(config, directory):
        directory.mkdir(parents=True)
        files = []
        for role in sorted(cli.REQUIRED_ROLES):
            path = directory / (role + '.bin')
            path.write_text('evidence ' + role)
            files.append(file_evidence(path, 'https://www.ers.usda.gov/synthetic/' + role, role))
        provenance = {'csv_zip_href': CONFIG['release_markers']['csv_zip_href'],
                      'csv_last_updated': CONFIG['release_markers']['csv_last_updated'],
                      'raw_values_sha256': 'synthetic', 'retrieved_at': datetime.now(timezone.utc).isoformat()}
        return (selected, lookup(), stats or {'rows': 100, 'variables': 10, 'non_fips_rows': 1,
                                              'duplicate_keys_all_variables': 0}, files, provenance)
    return retrieved


def pointer(engine, dataset=CONFIG['dataset_id']):
    with engine.connect() as conn:
        value = conn.execute(text('SELECT release_id FROM area_pilot.active_release WHERE dataset_id=:d'),
                             {'d': dataset}).scalar_one_or_none()
    return str(value) if value else None


def params(release, measure, bbox='-180,-85,180,85'):
    west, south, east, north = map(float, bbox.split(','))
    return {'release': release, 'measure': measure['measure_id'], 'period': measure['observation_period'],
            'population': measure['population'], 'value_type': CONFIG['value_type'],
            'west': west, 'south': south, 'east': east, 'north': north}


def measure(measure_id):
    return next(m for m in CONFIG['measures'] if m['measure_id'] == measure_id)


def test_full_lifecycle(engine, tmp_path):
    other = pointer(engine, 'cms_om_geographic_variation')
    first, report = cli.fetch_stage(engine, CONFIG, tmp_path, stub(rows()))
    assert report['status'] == 'ready', (report['checks'], report.get('value_error'))
    assert report['matched_counties'] == {m: 2 for m in MEASURE_IDS} | {'farmers_markets_per_1000': 3}
    assert report['observation_count'] == 11
    assert report['boundary_without_source_row']['snap_stores_per_1000'] == {
        'ct_planning_region_not_published_for_period': 1, 'puerto_rico_outside_atlas_coverage': 1}
    assert report['status_counts']['farmers_markets_per_1000'] == {'true_zero': 1, 'available': 1, 'did_not_exist': 1}

    # Idempotent: identical content records a duplicate run against the same candidate.
    again, duplicate = cli.fetch_stage(engine, CONFIG, tmp_path, stub(rows()))
    assert again == first and duplicate['status'] == 'duplicate'

    reviewed = cli.review(engine, first, CONFIG)
    assert reviewed['observations_verified'] == 11 and reviewed['staged_rows'] == 17
    with pytest.raises(ValueError, match='reviewed checksums'):
        cli.publish(engine, CONFIG, first, report['semantic_sha256'], report['schema_sha256'], 'wrong')
    assert pointer(engine) is None
    digests = (report['semantic_sha256'], report['schema_sha256'], report['metadata_sha256'])
    cli.publish(engine, CONFIG, first, *digests)
    assert pointer(engine) == str(first) and pointer(engine, 'cms_om_geographic_variation') == other

    # Representative source-to-database cells: text value, exact numeric, status.
    with engine.connect() as conn:
        cells = {(r.geoid, r.measure_id): (r.source_value, r.value, r.status, r.value_note) for r in conn.execute(text(
            'SELECT geoid,measure_id,source_value,value,status,value_note FROM area_pilot.observation_usda_fea '
            'WHERE release_id=:r'), {'r': first})}
        staged = {(r.measure_id, r.source_key): r.exclusion_reason for r in conn.execute(text(
            "SELECT measure_id,source_key,exclusion_reason FROM area_pilot.stage_usda_fea "
            "WHERE release_id=:r AND boundary_status='source_only'"), {'r': first})}
    source, stored, status, _ = cells[('01001', 'low_income_low_access_pct')]
    assert (source, str(stored), status) == ('13.020998', '13.020998', 'available')
    assert cells[('01003', 'low_income_low_access_pct')][2] == 'true_zero'
    assert cells[('01003', 'snap_stores_per_1000')] == ('-9999', None, 'not_available', None)
    assert cells[('01003', 'wic_stores_per_1000')] == ('N/A', None, 'not_available', None)
    assert cells[('09110', 'farmers_markets_per_1000')] == (
        '-8888', None, 'did_not_exist', 'ct_planning_region_created_2022_after_period')
    assert ('09001', 'snap_stores_per_1000') not in cells
    assert staged[('snap_stores_per_1000', '09001')] == 'legacy_ct_county_no_compatible_2024_boundary'
    assert staged[('farmers_markets_per_1000', 'N/A|AK|Kenai Peninsula Area')] == 'no_fips_alaska_agricultural_area'

    # Read API: map, legend, and table agree; boundary-only counties get explicit read-time statuses.
    with engine.connect() as conn:
        for measure_id, expected in (('snap_stores_per_1000', {'01001': 'available', '01003': 'not_available',
                                                               '09110': 'boundary_not_comparable', '72001': 'not_covered'}),
                                     ('farmers_markets_per_1000', {'01001': 'true_zero', '01003': 'available',
                                                                   '09110': 'did_not_exist', '72001': 'not_covered'})):
            m = measure(measure_id)
            p = params(first, m)
            base = api.metadata(CONFIG, m, first, '-180,-85,180,85')
            count = api.ensure_cap(conn, p)
            mapped, table, legend = (api.map_data(conn, p, count, base, 0.01), api.table(conn, p, base, count, 100, 0),
                                     api.legend(conn, p, base))
            assert {f['properties']['geography_id']: f['properties']['status'] for f in mapped['features']} == expected
            assert [f['properties']['geography_id'] for f in mapped['features']] == [r['geography_id'] for r in table['rows']]
            assert [f['properties']['status'] for f in mapped['features']] == [r['status'] for r in table['rows']]
            assert sum(s['n'] for s in legend['statuses']) == count == table['total'] == 4
            assert all(f['properties']['observation_period'] == m['observation_period'] for f in mapped['features'])
        zero = next(f['properties'] for f in mapped['features'] if f['properties']['geography_id'] == '01001')
        assert zero['value'] == 0 and zero['source_value'] == '0'
        local = params(first, measure('wic_stores_per_1000'), '-87.5,31.5,-85.5,33.5')
        assert api.ensure_cap(conn, local) == 1
        assert api.table(conn, local, api.metadata(CONFIG, measure('wic_stores_per_1000'), first, ''), 1, 1, 0)['rows'][0][
            'value'] == 0.2
        # The 5,000-county cap returns 413 instead of truncating.
        original = api.CAP
        try:
            api.CAP = 3
            with pytest.raises(HTTPException) as error:
                api.ensure_cap(conn, params(first, measure('wic_stores_per_1000')))
            assert error.value.status_code == 413
        finally:
            api.CAP = original

    # Published rows are immutable.
    with pytest.raises(Exception, match='immutable'):
        with engine.begin() as conn:
            conn.execute(text("UPDATE area_pilot.observation_usda_fea SET source_value='1' WHERE release_id=:r"),
                         {'r': first})

    # A failed retrieval, an unexplained geography, and an undocumented value all hold without moving a pointer.
    def broken(_config, _directory):
        raise RuntimeError('USDA download failed after 3 attempts')
    failed, failure = cli.fetch_stage(engine, CONFIG, tmp_path, broken)
    assert failure['status'] == 'held'
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM area_pilot.release WHERE id=:r"), {'r': failed}).scalar_one() == 'held'
    stray = (('01005', 'SNAPSPTH23'), {'fips': '01005', 'state': 'AL', 'county': 'Barbour',
                                       'variable_code': 'SNAPSPTH23', 'value': '1'})
    mismatch_id, mismatch = cli.fetch_stage(engine, CONFIG, tmp_path, stub(rows(extra=[stray])))
    assert mismatch['status'] == 'held' and mismatch['hold_reason'] == 'geography_mismatch'
    assert ['snap_stores_per_1000', '01005'] in mismatch['unexplained']
    bad_value = rows(); bad_value[('01001', 'WICSPTH22')]['value'] = '-7777'
    bad_id, bad = cli.fetch_stage(engine, CONFIG, tmp_path, stub(bad_value))
    assert bad['status'] == 'held' and not bad['checks']['values_and_sentinels_documented']
    totals_id, totals = cli.fetch_stage(engine, CONFIG, tmp_path, stub(rows(), {'rows': 99, 'variables': 10}))
    assert totals['status'] == 'held' and not totals['checks']['source_totals']
    for candidate, item in ((mismatch_id, mismatch), (bad_id, bad)):
        with pytest.raises(ValueError, match='not ready'):
            cli.publish(engine, CONFIG, candidate, item['semantic_sha256'], item['schema_sha256'], item['metadata_sha256'])
    assert pointer(engine) == str(first)

    # Revised content under the same label is held, then released only by checksum-bound review.
    revised, revision = cli.fetch_stage(engine, CONFIG, tmp_path, stub(rows(snap_autauga='1.26')))
    assert revision['status'] == 'held' and revision['hold_reason'] == 'same_label_semantic_revision'
    with pytest.raises(ValueError, match='not ready'):
        cli.publish(engine, CONFIG, revised, revision['semantic_sha256'], revision['schema_sha256'],
                    revision['metadata_sha256'])
    assert pointer(engine) == str(first)
    rdigests = (revision['semantic_sha256'], revision['schema_sha256'], revision['metadata_sha256'])
    with pytest.raises(ValueError, match='note'):
        cli.release_reviewed_hold(engine, CONFIG, revised, *rdigests, ' ')
    cli.release_reviewed_hold(engine, CONFIG, revised, *rdigests, 'Reviewed USDA same-label revision')
    cli.publish(engine, CONFIG, revised, *rdigests)
    assert pointer(engine) == str(revised)
    # The superseded release stays queryable by ID.
    with engine.connect() as conn:
        m = measure('snap_stores_per_1000')
        old = api.table(conn, params(first, m), api.metadata(CONFIG, m, first, ''), 4, 10, 0)
        new = api.table(conn, params(revised, m), api.metadata(CONFIG, m, revised, ''), 4, 10, 0)
    assert old['rows'][0]['source_value'] == '1.25' and new['rows'][0]['source_value'] == '1.26'

    # Rollback and deactivation affect only this product; failed or foreign candidates are never targets.
    with pytest.raises(ValueError, match='retained published'):
        cli.set_pointer(engine, CONFIG, 'rollback', failed)
    with pytest.raises(ValueError, match='retained published'):
        cli.set_pointer(engine, CONFIG, 'rollback', OTHER)
    cli.set_pointer(engine, CONFIG, 'rollback', first)
    assert pointer(engine) == str(first)
    cli.set_pointer(engine, CONFIG, 'deactivate')
    assert pointer(engine) is None and pointer(engine, 'cms_om_geographic_variation') == other
    cli.set_pointer(engine, CONFIG, 'rollback', first)
    assert pointer(engine) == str(first)

    with engine.connect() as conn:
        m = measure('snap_stores_per_1000')
        args = (CONFIG['dataset_id'], m['measure_id'], m['observation_period'], m['population'], CONFIG['value_type'])
        with pytest.raises(HTTPException) as error:
            api.selection(conn, args[0], failed, *args[1:], 'county')
        assert error.value.status_code == 404
        with pytest.raises(HTTPException) as error:
            api.selection(conn, args[0], first, *args[1:], 'state')
        assert error.value.status_code == 400
