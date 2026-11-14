"""Isolated PostGIS lifecycle test for CMS nursing home release controls and map parity."""
import copy
import csv
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.area_pilot import cms_nursing_homes_api as api
from app.area_pilot import cms_nursing_homes_cli as cli
from app.area_pilot.cms_nursing_homes import file_evidence, load_registry
from app.db import DATABASE_URL

VERSIONS = Path(__file__).resolve().parents[1] / 'alembic' / 'versions'
TEST_DB = 'chip_cms_nursing_homes_test'
BASE = load_registry()
CONFIG = copy.deepcopy(BASE) | {'expected_source_rows': {'min': 3, 'max': 10}}


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
        with Operations.context(MigrationContext.configure(conn)):
            migration('a4d9e7c2b6f1_add_cms_nursing_homes').upgrade()
    yield test_engine
    test_engine.dispose()
    with admin.connect() as conn:
        conn.execute(text('DROP DATABASE IF EXISTS ' + TEST_DB + ' WITH (FORCE)'))
    admin.dispose()


def row(ccn, name, lat='32.5', lon='-86.5', overall='3', overall_note='', geocode=''):
    result = {field: '' for field in BASE['expected_header']}
    result.update({'CMS Certification Number (CCN)': ccn, 'Provider Name': name,
        'Provider Address': '1 TEST ST', 'City/Town': 'Testville', 'State': 'AL',
        'ZIP Code': '01234', 'County/Parish': 'Test',
        'Provider Type': 'Medicare and Medicaid', 'Ownership Type': 'Non profit - Corporation',
        'Number of Certified Beds': '0', 'Overall Rating': overall,
        'Overall Rating Footnote': overall_note, 'Health Inspection Rating': '2',
        'Staffing Rating': '4', 'QM Rating': '5', 'Latitude': lat, 'Longitude': lon,
        'Geocoding Footnote': geocode, 'Processing Date': '2026-10-01'})
    return result


def inputs(directory, rows):
    directory.mkdir()
    meta = {'identifier': '4pq5-n9py', 'accessLevel': 'public', 'description': 'one row per nursing home',
            'issued': '2026-09-01', 'modified': '2026-10-01', 'released': '2026-10-28',
            'distribution': [{'mediaType': 'text/csv', 'downloadURL':
              'https://data.cms.gov/provider-data/sites/default/files/resources/synthetic.csv',
              'describedBy': BASE['dictionary_url']}]}
    paths = {'metadata': directory/'metadata.json', 'api_count': directory/'count.json',
             'dictionary_pdf': directory/'dictionary.pdf', 'provider_csv': directory/'synthetic.csv'}
    paths['metadata'].write_text(json.dumps(meta))
    paths['api_count'].write_text(json.dumps({'count':len(rows)}))
    paths['dictionary_pdf'].write_bytes(b'synthetic dictionary; parse check is isolated')
    with paths['provider_csv'].open('w', newline='') as f:
        writer=csv.DictWriter(f,fieldnames=BASE['expected_header'])
        writer.writeheader()
        writer.writerows(rows)
    urls={'metadata':BASE['metadata_url'],'api_count':'https://data.cms.gov/provider-data/api/1/datastore/query/4pq5-n9py/0',
          'dictionary_pdf':BASE['dictionary_url'],
          'provider_csv':meta['distribution'][0]['downloadURL']}
    files=[file_evidence(path,urls[role],role) for role,path in paths.items()]
    provenance={'csv_url':urls['provider_csv'],'api_count':len(rows),
                'retrieved_at':datetime.now(timezone.utc).isoformat()}
    return rows,meta,files,provenance


def test_release_review_hold_pointer_and_map_parity(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(cli,'parse_dictionary',lambda path: {'pages':25})
    rows=[row('015009','Home A'),row('015010','Home B',overall='',overall_note='18'),
          row('015011','ZIP based',geocode='22')]
    first,report=cli.fetch_stage(engine,CONFIG,tmp_path,inputs(tmp_path/'first',rows))
    assert report['status']=='ready'
    assert report['summary']['mapped']==2
    assert cli.review(engine,first,CONFIG)['rows_verified']==3
    cli.publish(engine,CONFIG,first,report['semantic_sha256'],report['schema_sha256'],report['metadata_sha256'])
    again,duplicate=cli.fetch_stage(engine,CONFIG,tmp_path,inputs(tmp_path/'again',rows))
    assert again==first and duplicate['status']=='duplicate'

    metadata_only=list(inputs(tmp_path/'metadata_revision',rows))
    metadata_only[1]['nextUpdateDate']='2026-12-03'
    metadata_path=tmp_path/'metadata_revision'/'metadata.json'
    metadata_path.write_text(json.dumps(metadata_only[1]))
    metadata_only[2]=[file_evidence(metadata_path,BASE['metadata_url'],'metadata') if item['role']=='metadata'
                      else item for item in metadata_only[2]]
    metadata_candidate,metadata_hold=cli.fetch_stage(engine,CONFIG,tmp_path,tuple(metadata_only))
    assert metadata_hold['status']=='held' and metadata_hold['hold_reason']=='same_label_semantic_revision'
    assert cli.review(engine,metadata_candidate,CONFIG)['rows_verified']==3

    changed=copy.deepcopy(rows)
    changed[0]['Provider Name']='Revised Home A'
    second,held=cli.fetch_stage(engine,CONFIG,tmp_path,inputs(tmp_path/'revised',changed))
    assert held['status']=='held' and held['hold_reason']=='same_label_semantic_revision'
    assert cli.review(engine,second,CONFIG)['rows_verified']==3
    with engine.connect() as conn:
        assert conn.execute(text('''SELECT release_id FROM area_pilot.active_release
            WHERE dataset_id=:dataset'''),{'dataset':BASE['dataset_id']}).scalar_one()==first
    with pytest.raises(ValueError,match='checksums'):
        cli.release_reviewed_hold(engine,CONFIG,second,'wrong',held['schema_sha256'],
                                  held['metadata_sha256'],'reviewed')
    cli.release_reviewed_hold(engine,CONFIG,second,held['semantic_sha256'],
                              held['schema_sha256'],held['metadata_sha256'],'synthetic same-label revision reviewed')
    cli.publish(engine,CONFIG,second,held['semantic_sha256'],held['schema_sha256'],held['metadata_sha256'])
    with engine.connect() as conn:
        filters=api.parse_filters(api._choices(conn,second),overall='unrated')
        mapped=api.map_payload(conn,CONFIG,second,'-87,32,-85,33',9,filters)
        table=api.table_payload(conn,CONFIG,second,'-87,32,-85,33',filters,50,0)
        assert mapped['total']==table['total']==1
        assert table['rows'][0]['ccn']=='015010'
    bad=copy.deepcopy(rows);bad[1]['CMS Certification Number (CCN)']='015009'
    rejected,failure=cli.fetch_stage(engine,CONFIG,tmp_path,inputs(tmp_path/'bad',bad))
    assert failure['status']=='held' and failure['hold_reason']=='blocking_validation_failed'
    with engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM area_pilot.stage_cms_nursing_home WHERE release_id=:id'),
                            {'id':rejected}).scalar_one()==0
        assert conn.execute(text('SELECT release_id FROM area_pilot.active_release WHERE dataset_id=:dataset'),
                            {'dataset':BASE['dataset_id']}).scalar_one()==second
    with pytest.raises(Exception,match='immutable'):
        with engine.begin() as conn:
            conn.execute(text('''UPDATE area_pilot.cms_nursing_home SET provider_name='changed'
                WHERE release_id=:id AND ccn='015009' '''),{'id':second})
    cli.set_pointer(engine,'deactivate')
    with engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM area_pilot.active_release WHERE dataset_id=:dataset'),
                            {'dataset':BASE['dataset_id']}).scalar_one()==0
    cli.set_pointer(engine,'rollback',first)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT release_id FROM area_pilot.active_release WHERE dataset_id=:dataset'),
                            {'dataset':BASE['dataset_id']}).scalar_one()==first
