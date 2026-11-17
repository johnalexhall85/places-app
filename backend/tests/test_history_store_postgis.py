"""Isolated PostGIS lifecycle test for history releases: stage, review, tamper, publish, duplicate, pointers."""
import copy
import importlib.util
import sys
import types
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.area_pilot.history import store
from app.area_pilot.history.fetch import evidence
from app.area_pilot.history.registry import load_history_registry
from app.area_pilot.history.rows import make_row, to_decimal
from app.db import DATABASE_URL

VERSIONS = Path(__file__).resolve().parents[1] / 'alembic' / 'versions'
TEST_DB = 'chip_area_history_test'


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_parser():
    """A parser over a tiny CSV: level,geoid,measure,period,value,status."""
    module = types.ModuleType('app.area_pilot.history.parsers.fake_test')
    module.SCHEMA_VERSION = '1'

    def parse(config, files, evidence_out):
        lines = files['csv'].read_text().strip().splitlines()[1:]
        evidence_out['rows'] = len(lines)
        by_period = {}
        for line in lines:
            level, geoid, measure, period, value, status = line.split(',')
            by_period.setdefault(period, []).append(make_row(
                config, measure, period, level, geoid, value=to_decimal(value), status=status, source_value=value))
        for period in sorted(by_period):
            yield f'p{period}', by_period[period]
    module.parse = parse
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
        for level, geoid in (('state', '01'), ('state', '09'), ('county', '01001'), ('county', '09110')):
            conn.execute(text('''INSERT INTO area_pilot.acs_boundary_2024 VALUES
                (:level,:geoid,'x','x',ST_Multi(ST_MakeEnvelope(0,0,1,1,4326)))'''), {'level': level, 'geoid': geoid})
        with Operations.context(MigrationContext.configure(conn)):
            migration('f7d1a4c8e2b6_add_area_history').upgrade()
        for geoid in ('01001', '09001'):
            conn.execute(text('''INSERT INTO area_pilot.history_boundary VALUES
                ('2020','county',:geoid,'x','x',ST_Multi(ST_MakeEnvelope(0,0,1,1,4326)))'''), {'geoid': geoid})
        # The current product's pointer must never move.
        conn.execute(text('''INSERT INTO area_pilot.release (id,dataset_id,source_release_id,status,semantic_sha256,
            schema_sha256,metadata_sha256,keyset_sha256,source_before,source_after,report,published_at)
            VALUES ('00000000-0000-0000-0000-000000000001','cms_om_geographic_variation','x','published',
            'a','b','c','d','{}','{}','{}',now())'''))
        conn.execute(text('''INSERT INTO area_pilot.active_release (dataset_id,release_id)
            VALUES ('cms_om_geographic_variation','00000000-0000-0000-0000-000000000001')'''))
    yield test_engine
    test_engine.dispose()
    with admin.connect() as conn:
        conn.execute(text('DROP DATABASE IF EXISTS ' + TEST_DB + ' WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def config(monkeypatch):
    sys.modules['app.area_pilot.history.parsers.fake_test'] = fake_parser()
    base = copy.deepcopy(load_history_registry('cms_gv'))
    base['parser'] = 'fake_test'
    base['sources'] = [{'role': 'csv', 'url': 'test://csv'}]
    for measure in base['measures']:
        measure['periods'] = [p for p in measure['periods'] if p['period'] in ('2021', '2022')]
    base['measures'] = base['measures'][:1]
    base['_index'] = {(m['measure_id'], p['period']): (m, p) for m in base['measures'] for p in m['periods']}
    base['unmatched_tolerance'] = {'state': 0, 'county': 0}
    return base


ROWS = ['state,01,om_beneficiaries,2021,100,available', 'county,01001,om_beneficiaries,2021,40.50,available',
        'county,09001,om_beneficiaries,2021,,suppressed', 'state,09,om_beneficiaries,2022,0,true_zero',
        'county,09110,om_beneficiaries,2022,7,available']


def retrieved_for(tmp_path, lines):
    def retrieved(run_dir):
        path = tmp_path / 'source.csv'
        path.write_text('level,geoid,measure,period,value,status\n' + '\n'.join(lines) + '\n')
        return {'csv': path}, [evidence(path, 'csv', 'test://csv')]
    return retrieved


def test_lifecycle(engine, config, tmp_path):
    candidate, report = store.fetch_stage(engine, config, directory=tmp_path, retrieved=retrieved_for(tmp_path, ROWS))
    assert report['status'] == 'ready', report.get('checks')
    assert report['observation_count'] == 5 and set(report['parts']) == {'p2021', 'p2022'}
    reviewed = store.review(engine, candidate, config)
    assert reviewed['parts_verified'] == 2
    with engine.connect() as conn:
        assert conn.execute(text("SELECT value FROM area_pilot.observation_history WHERE geoid='01001'")).scalar_one() \
            == Decimal('40.5')
        assert conn.execute(text("SELECT boundary_vintage FROM area_pilot.observation_history WHERE geoid='09110'")
                            ).scalar_one() == '2024'

    # Same content again is a duplicate run, not a new release.
    again, dup = store.fetch_stage(engine, config, directory=tmp_path, retrieved=retrieved_for(tmp_path, ROWS))
    assert dup['status'] == 'duplicate' and again == candidate

    with pytest.raises(ValueError):
        store.publish(engine, config, candidate, 'x', reviewed['schema_sha256'], reviewed['metadata_sha256'])
    store.publish(engine, config, candidate, reviewed['semantic_sha256'], reviewed['schema_sha256'],
                  reviewed['metadata_sha256'])
    with engine.connect() as conn:
        pointers = dict(conn.execute(text('SELECT dataset_id,release_id::text FROM area_pilot.active_release')).all())
    assert pointers['cms_om_geographic_variation'] == '00000000-0000-0000-0000-000000000001'
    assert pointers['cms_om_geographic_variation:history'] == str(candidate)
    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(text("UPDATE area_pilot.observation_history SET value=1 WHERE geoid='01001'"))

    store.set_pointer(engine, config, 'deactivate')
    store.set_pointer(engine, config, 'rollback', candidate)


def test_tampered_rows_fail_review(engine, config, tmp_path):
    rows = [r.replace(',100,', ',101,') for r in ROWS]
    config['source_release_id'] += ' (tamper test)'
    candidate, report = store.fetch_stage(engine, config, directory=tmp_path, retrieved=retrieved_for(tmp_path, rows))
    assert report['status'] == 'ready'
    with engine.begin() as conn:
        conn.execute(text("UPDATE area_pilot.observation_history SET value=102 WHERE release_id=:id AND geoid='01'"),
                     {'id': candidate})
    with pytest.raises(ValueError, match='stored rows differ'):
        store.review(engine, candidate, config)


@pytest.mark.parametrize('lines,check', [
    (ROWS[:3], 'registry_coverage'),                                           # 2022 missing
    (ROWS + ['county,01003,om_beneficiaries,2021,5,available'], 'boundary_match'),
    (ROWS[:-1] + ['county,09110,om_beneficiaries,2022,,available'], 'row_contract'),
])
def test_validation_holds(engine, config, tmp_path, lines, check):
    _, report = store.fetch_stage(engine, config, directory=tmp_path, retrieved=retrieved_for(tmp_path, lines))
    assert report['status'] == 'held' and report['checks'][check] is False


def test_undeclared_period_and_duplicates_hold(engine, config, tmp_path):
    _, report = store.fetch_stage(engine, config, directory=tmp_path,
                                  retrieved=retrieved_for(tmp_path, ROWS + ['state,01,om_beneficiaries,2019,1,available']))
    assert report['status'] == 'held' and 'parse' in report['hold_reason']
    _, report = store.fetch_stage(engine, config, directory=tmp_path, retrieved=retrieved_for(tmp_path, ROWS + ROWS[:1]))
    assert report['status'] == 'held' and 'duplicate' in report['hold_reason']
