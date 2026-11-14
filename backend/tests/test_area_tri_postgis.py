"""PostGIS integration tests for EPA TRI reporting facilities in an isolated scratch database.

The scratch database is created on the local PostGIS server, migrated with the real shared-release
and TRI migrations, populated with synthetic boundaries and synthetic forms, and dropped afterwards.
Skips if PostGIS is unreachable.
"""
import copy
import importlib.util
import json
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.area_pilot import tri_api as api
from app.area_pilot import tri_cli as cli
from app.db import DATABASE_URL
from tri_synthetic import F, HEADER, config, doc_number, form, write_inputs

VERSIONS = Path(__file__).resolve().parents[1] / 'alembic' / 'versions'
TEST_DB = 'chip_tri_facilities_test'
CONFIG = config()
NATIONAL = '-180,-85,180,85'
LOCAL = '-87,32,-85,33'
F1, F2, F3, F4, F5, F6, F7, F8, F9 = (f'0000{i}TSTFC000{i}A' for i in range(1, 10))
C1, C2, C3 = '0000050000', '0000071432', '0000108883'


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def engine():
    admin_url = make_url(DATABASE_URL).set(database='postgres')
    try:
        admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS {TEST_DB}'))
            conn.execute(text(f'CREATE DATABASE {TEST_DB}'))
    except Exception as exc:  # pragma: no cover - environment without local PostGIS
        pytest.skip(f'PostGIS scratch database unavailable: {type(exc).__name__}')
    test_engine = create_engine(make_url(DATABASE_URL).set(database=TEST_DB))
    with test_engine.begin() as conn:
        conn.execute(text('CREATE EXTENSION postgis'))
        with Operations.context(MigrationContext.configure(conn)):
            migration('a91c7e3f2b40_add_area_pilot').upgrade()
        conn.execute(text('''CREATE FUNCTION area_pilot.prevent_published_data_change() RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE target_release uuid;
            BEGIN
              target_release := CASE WHEN TG_OP = 'INSERT' THEN NEW.release_id ELSE OLD.release_id END;
              IF EXISTS (SELECT 1 FROM area_pilot.release WHERE id=target_release AND status='published') THEN
                RAISE EXCEPTION 'Published area observations and staging are immutable';
              END IF;
              IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
              RETURN NEW;
            END $$'''))
        conn.execute(text('''CREATE FUNCTION area_pilot.prevent_published_release_change() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF OLD.status='published' THEN RAISE EXCEPTION 'Published area release metadata are immutable'; END IF;
            RETURN NEW; END $$'''))
        conn.execute(text('''CREATE TRIGGER prevent_published_release_change BEFORE UPDATE OR DELETE ON area_pilot.release
            FOR EACH ROW EXECUTE FUNCTION area_pilot.prevent_published_release_change()'''))
        conn.execute(text('''CREATE TABLE area_pilot.acs_boundary_2024 (level text, geoid varchar, name text,
            source_sha256 varchar, geom geometry(MultiPolygon,4326))'''))
        conn.execute(text('''INSERT INTO area_pilot.acs_boundary_2024 VALUES
            ('state','01','Synthetic State','x',ST_Multi(ST_MakeEnvelope(-87,32,-85,33,4326))),
            ('county','01001','West County','x',ST_Multi(ST_MakeEnvelope(-87,32,-86,33,4326))),
            ('county','01003','East County','x',ST_Multi(ST_MakeEnvelope(-86,32,-85,33,4326)))'''))
        with Operations.context(MigrationContext.configure(conn)):
            migration('f2c8d4a6b1e3_add_epa_tri_facilities').upgrade()
    yield test_engine
    test_engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)'))


def truncate(engine):
    with engine.begin() as conn:
        conn.execute(text('''TRUNCATE area_pilot.tri_facility_chemical, area_pilot.tri_facility, area_pilot.tri_chemical,
            area_pilot.tri_report, area_pilot.stage_tri_report, area_pilot.active_release, area_pilot.validation,
            area_pilot.source_file, area_pilot.run, area_pilot.release CASCADE'''))


@pytest.fixture(autouse=True)
def clean(engine):
    truncate(engine)


def fixture_rows():
    """Deterministic synthetic forms (fixed control numbers so reruns are byte-identical)."""
    n = iter(range(1, 10000))
    rows = [
        form(F1, C1, doc=doc_number(next(n))), form(F1, C1, doc=doc_number(next(n)), naics='325180'),
        form(F1, 'N420', doc=doc_number(next(n)), chemical='Lead compounds', form_type='A'),
        form(F1, 'N420', doc=doc_number(next(n)), chemical='Lead  And Lead Compounds',
             **{F['elemental_metal_included']: 'YES'}),
        form(F2, C1, doc=doc_number(next(n))),  # colocated with F1, distinct facility
        form(F3, C2, doc=doc_number(next(n)), form_type='A', sector='562', lat='32.512345', lon='-85.512345'),
        form(F4, C2, doc=doc_number(next(n)), state='GA', lat='32.212345', lon='-86.212345'),  # published GA, inside AL county
        form(F5, C2, doc=doc_number(next(n)), state='GU', lat='13.441234', lon='144.791234'),
        form(F6, C1, doc=doc_number(next(n)), lat='', lon=''),
        form(F7, C1, doc=doc_number(next(n)), lat='95.123456', lon='-86.123456'),
        form(F8, C1, doc=doc_number(next(n)), lat='32.51', lon='-86.51'),
        form(F9, C3, doc=doc_number(next(n)), sector='324', lat='32.712345', lon='-86.712345'),
        form(F9, C3, doc=doc_number(next(n)), sector='4247', naics='424710', lat='32.712345', lon='-86.712345'),
    ]
    for i in range(60):  # grid in West County for clustering
        rows.append(form(f'9{i:04d}GRIDFAC{i:03d}', C1, doc=doc_number(next(n)), sector='332',
                         lat=f'32.{1 + i // 8}{i:02d}345', lon=f'-86.{9 - i % 8}{i:02d}345'))
    return rows


def stage(engine, tmp_path, rows, processed='November 5, 2025'):
    return cli.fetch_stage(engine, CONFIG, directory=tmp_path,
                           fetched=write_inputs(tmp_path / uuid.uuid4().hex, rows, processed=processed))


def publish(engine, candidate, report):
    cli.publish(engine, CONFIG, candidate, report['semantic_sha256'], report['schema_sha256'], report['metadata_sha256'])


def read(engine, fn, *args):
    with engine.connect() as conn:
        return fn(conn, *args)


def staged_and_published(engine, tmp_path):
    candidate, report = stage(engine, tmp_path, fixture_rows())
    assert report['status'] == 'ready', report
    publish(engine, candidate, report)
    return candidate, report


# ---------------------------------------------------------------- lifecycle

def test_stage_review_publish_keeps_report_grain_and_explicit_location_statuses(engine, tmp_path):
    candidate, report = stage(engine, tmp_path, fixture_rows())
    assert report['status'] == 'ready' and all(report['checks'].values())
    s = report['summary']
    assert s['source_reports'] == 73 and s['distinct_facilities'] == 69 and s['distinct_chemical_ids'] == 4
    assert s['facility_chemical_relationships'] == 70 and s['multi_form_facility_chemical_pairs'] == 3
    assert s['location_status_counts'] == {'mapped': 66, 'no_published_coordinates': 1, 'invalid_coordinates': 1,
                                           'coarse_coordinate': 1}
    assert s['boundary_check_counts'] == {'within_published_state': 64, 'outside_published_state': 1,
                                          'outside_chip_boundary_layer': 1}
    assert s['colocated_coordinate_groups'] == 1 and s['multi_sector_facilities'] == 1
    assert report['processed_as_of'] == '2025-11-05' and report['source_release_id'] == 'TRI RY2024 basic US file'
    checked = cli.review(engine, candidate, CONFIG)
    assert checked['staged_forms_verified'] == checked['reports_verified'] == 73
    assert checked['facilities_verified'] == 69 and checked['mapped_facilities_verified'] == 66
    assert checked['facility_chemical_relationships_verified'] == 70
    publish(engine, candidate, report)
    with engine.connect() as conn:
        f1 = conn.execute(text(f"SELECT report_count,form_r_count,form_a_count,chemical_count FROM area_pilot.tri_facility WHERE facility_id='{F1}'")).one()
        assert tuple(f1) == (4, 3, 1, 2)
        pair = conn.execute(text(f"""SELECT report_count,form_types,names FROM area_pilot.tri_facility_chemical
            WHERE facility_id='{F1}' AND chemical_id='N420'""")).one()
        assert pair[0] == 2 and pair[1] == ['A', 'R'] and pair[2] == ['Lead  And Lead Compounds', 'Lead compounds']
        mismatch = conn.execute(text(f"""SELECT location_status,boundary_check,derived_county_geoid,state_abbr
            FROM area_pilot.tri_facility WHERE facility_id='{F4}'""")).one()
        assert tuple(mismatch) == ('mapped', 'outside_published_state', '01001', 'GA')
        unmapped = conn.execute(text(f"""SELECT location_status,exclusion_reason,geom FROM area_pilot.tri_facility
            WHERE facility_id='{F6}'""")).one()
        assert unmapped[0] == unmapped[1] == 'no_published_coordinates' and unmapped[2] is None
        # Quantities live only in the raw staged form, which the API never reads.
        raw = conn.execute(text(f"SELECT record->>51 FROM area_pilot.stage_tri_report WHERE doc_ctrl_num='{doc_number(1)}'")).scalar_one()
        assert raw == '1.000'
        columns = set(conn.execute(text('''SELECT column_name FROM information_schema.columns WHERE table_schema='area_pilot'
            AND table_name IN ('tri_report','tri_facility','tri_facility_chemical','tri_chemical')''')).scalars())
        assert not any(word in c for c in columns for word in ('release_q', 'air', 'total', 'pound'))
        assert conn.execute(text('SELECT release_id FROM area_pilot.active_release')).scalar_one() == candidate
    with pytest.raises(Exception, match='immutable'):
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE area_pilot.tri_facility SET facility_name='changed' WHERE facility_id='{F1}'"))
    catalog = read(engine, api.catalog_payload, CONFIG)
    assert catalog['active_release_id'] == str(candidate) and catalog['processed_as_of'] == '2025-11-05'
    assert catalog['counts']['source_reports'] == 73 and catalog['counts']['facilities'] == 69
    assert catalog['counts']['mapped_facilities'] == 66 and catalog['counts']['form_a_reports'] == 2
    assert catalog['counts']['not_mapped_by_reason'] == {'coarse_coordinate': 1, 'invalid_coordinates': 1,
                                                         'no_published_coordinates': 1}
    sectors = {s['code']: s['mapped_facilities'] for s in catalog['sectors']}
    assert sectors['332'] == 60 and sectors['324'] == sectors['4247'] == 1 and sectors['562'] == 1


def test_review_detects_tampered_read_models_staging_and_archive(engine, tmp_path):
    candidate, _ = stage(engine, tmp_path, fixture_rows())
    tamper = [
        (f"UPDATE area_pilot.tri_facility SET facility_name='Tampered' WHERE facility_id='{F1}' AND release_id=:r", 'facility read model'),
        (f"UPDATE area_pilot.tri_facility_chemical SET report_count=1 WHERE facility_id='{F1}' AND chemical_id='{C1}' AND release_id=:r",
         'facility-chemical relationship'),
        (f"UPDATE area_pilot.tri_report SET form_type='A' WHERE doc_ctrl_num='{doc_number(1)}' AND release_id=:r", 'report read model'),
        (f"UPDATE area_pilot.stage_tri_report SET record=jsonb_set(record,'{{51}}','\"9.000\"') WHERE doc_ctrl_num='{doc_number(1)}' AND release_id=:r",
         'staged raw form'),
    ]
    for statement, message in tamper:
        with engine.begin() as conn:
            conn.execute(text(statement), {'r': candidate})
        with pytest.raises(ValueError, match=message):
            cli.review(engine, candidate, CONFIG)
        # Identical content would be recorded as a duplicate of the tampered candidate; start clean instead.
        truncate(engine)
        candidate, _ = stage(engine, tmp_path, fixture_rows())
    with engine.begin() as conn:
        path = conn.execute(text("SELECT path FROM area_pilot.source_file WHERE release_id=:r AND role='basic_csv'"),
                            {'r': candidate}).scalar_one()
    Path(path).write_text('tampered', encoding='utf-8')
    with pytest.raises(ValueError, match='checksum mismatch'):
        cli.review(engine, candidate, CONFIG)


def test_idempotent_rerun_revision_holds_and_pointer_recovery(engine, tmp_path):
    first, report = staged_and_published(engine, tmp_path)
    again, duplicate = stage(engine, tmp_path, fixture_rows(), processed='December 1, 2025')
    assert again == first and duplicate['status'] == 'duplicate' and duplicate['confirmed_processed_as_of'] == '2025-12-01'
    assert read(engine, api.catalog_payload, CONFIG)['counts']['last_confirmed_processed_as_of'] == '2025-12-01'
    revised = fixture_rows()
    revised[0][HEADER[51]] = '5.000'  # a facility revises a quantity under the same reporting-year label
    held, same_label = stage(engine, tmp_path, revised, processed='January 5, 2026')
    assert same_label['status'] == 'held' and same_label['hold_reason'] == 'same_label_semantic_revision'
    withdrawn = fixture_rows()[1:] + [form('77777NEWFC0077A', C2, doc=doc_number(9001), lat='32.312345', lon='-86.312345')]
    for row in withdrawn[20:30]:
        row[F['facility_name']] = row[F['facility_name']] + ' LLC'
    big, big_report = stage(engine, tmp_path, withdrawn, processed='February 5, 2026')
    assert big_report['hold_reason'] == 'same_label_semantic_revision'
    change = big_report['change_vs_active']
    assert change['reports_no_longer_present'] == 1 and change['reports_added'] == 1 and change['facilities_added'] == 1
    assert change['facilities_changed'] >= 10
    with pytest.raises(ValueError, match='not ready'):
        publish(engine, big, big_report)
    cli.release_reviewed_hold(engine, CONFIG, big, big_report['semantic_sha256'], big_report['schema_sha256'],
                              big_report['metadata_sha256'], 'Synthetic EPA revision/withdrawal reviewed')
    publish(engine, big, big_report)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT release_id FROM area_pilot.active_release')).scalar_one() == big
    cli.set_pointer(engine, CONFIG, 'rollback', first)
    assert read(engine, api.catalog_payload, CONFIG)['active_release_id'] == str(first)
    with pytest.raises(ValueError, match='retained published TRI'):
        cli.set_pointer(engine, CONFIG, 'rollback', held)
    other = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(text('''INSERT INTO area_pilot.release (id,dataset_id,source_release_id,status,semantic_sha256,schema_sha256,
            metadata_sha256,keyset_sha256,source_before,source_after,report,published_at)
            VALUES (:id,'hrsa_health_center_sites','other','published','a','b','c','d','{}','{}','{}',now())'''), {'id': other})
    with pytest.raises(ValueError, match='retained published TRI'):
        cli.set_pointer(engine, CONFIG, 'rollback', other)
    cli.set_pointer(engine, CONFIG, 'deactivate')
    assert read(engine, api.catalog_payload, CONFIG)['active_release_id'] is None
    # Published content stays queryable by release ID after deactivation.
    assert read(engine, api.table_payload, CONFIG, first, LOCAL, api.parse_filters(CONFIG), 10, 0)['total'] == 65


def test_failed_candidates_preserve_active_release(engine, tmp_path, monkeypatch):
    first, _ = staged_and_published(engine, tmp_path)
    duplicate_docs = fixture_rows()
    duplicate_docs.append(dict(duplicate_docs[0]) | {F['chemical_id']: C3})
    held, report = stage(engine, tmp_path, duplicate_docs)
    assert report['hold_reason'] == 'blocking_validation_failed' and report['issues']['duplicate_doc_ctrl_nums'] == [doc_number(1)]
    conflicted = fixture_rows()
    conflicted[1][F['latitude']] = '32.512399'  # same TRIFD, different published coordinates
    conflict_id, conflict = stage(engine, tmp_path, conflicted)
    assert conflict['status'] == 'held' and conflict['hold_reason'] == 'validation_failed'
    assert conflict['issues']['facility_conflicts'] == {F1: ['latitude']}

    def broken(*_):
        raise RuntimeError('EPA TRI download failed after 3 attempts')
    monkeypatch.setattr(cli, 'retrieve', broken)
    _, failed = cli.fetch_stage(engine, CONFIG, directory=tmp_path)
    assert failed['status'] == 'held'
    with engine.connect() as conn:
        assert conn.execute(text('SELECT release_id FROM area_pilot.active_release')).scalar_one() == first
        assert conn.execute(text('SELECT count(*) FROM area_pilot.tri_facility WHERE release_id=:r'), {'r': held}).scalar_one() == 0
    with pytest.raises(ValueError, match='not ready'):
        cli.publish(engine, CONFIG, conflict_id, conflict['semantic_sha256'], conflict['schema_sha256'], conflict['metadata_sha256'])


# ---------------------------------------------------------------- read API on real PostGIS

def all_table_rows(conn, release, bbox, filters):
    rows, offset = [], 0
    while True:
        page = api.table_payload(conn, CONFIG, release, bbox, filters, 7, offset)
        rows += page['rows']
        offset += 7
        if offset >= page['total']:
            return page['total'], rows


def test_chemical_and_sector_filters_return_unique_facilities_with_map_table_parity(engine, tmp_path):
    release, _ = staged_and_published(engine, tmp_path)
    with engine.connect() as conn:
        cases = {(None, None): 65, (None, C1): 62, (None, 'N420'): 1, ('332', None): 60, ('324', None): 1,
                 ('4247', C3): 1, ('562', C2): 1, ('332', 'N420'): 0, (None, C2): 2}
        for (sector, chemical), expected in cases.items():
            filters = api.parse_filters(CONFIG, sector, chemical)
            clusters = api.map_payload(conn, CONFIG, release, NATIONAL, 3, filters)
            points = api.map_payload(conn, CONFIG, release, LOCAL, 10, filters)
            total, rows = all_table_rows(conn, release, LOCAL, filters)
            national_total, _ = all_table_rows(conn, release, NATIONAL, filters)
            assert sum(c['count'] for c in clusters['clusters']) == clusters['total'] == national_total
            assert points['mode'] == 'points' and points['total'] == total == len(rows) == expected, (sector, chemical)
            assert sorted(p['facility_id'] for p in points['points']) == sorted(r['facility_id'] for r in rows)
            assert len({r['facility_id'] for r in rows}) == len(rows)  # never one marker per form
        c1 = {p['facility_id'] for p in api.map_payload(conn, CONFIG, release, LOCAL, 10, api.parse_filters(CONFIG, None, C1))['points']}
        assert {F1, F2} <= c1 and c1.isdisjoint({F6, F7, F8})  # F1 has two C1 forms, still one facility
        colocated = [p for p in api.map_payload(conn, CONFIG, release, LOCAL, 10, api.parse_filters(CONFIG))['points']
                     if p['facility_id'] in (F1, F2)]
        assert len(colocated) == 2 and {p['location_key'] for p in colocated} == {'-86.512345,32.512345'}
        pacific = api.map_payload(conn, CONFIG, release, '144,13,145,14', 10, api.parse_filters(CONFIG))
        assert [p['facility_id'] for p in pacific['points']] == [F5]
        multi = next(r for r in all_table_rows(conn, release, LOCAL, api.parse_filters(CONFIG, '324'))[1])
        assert [s['code'] for s in multi['sectors']] == ['324', '4247']
        with pytest.raises(HTTPException) as error:
            api.map_payload(conn, CONFIG, release, LOCAL, 10, api.parse_filters(CONFIG, None, '0000000001'))
        assert error.value.status_code == 400


def test_viewport_limits_never_truncate(engine, tmp_path):
    release, _ = staged_and_published(engine, tmp_path)
    with engine.connect() as conn:
        defaults = api.parse_filters(CONFIG)
        small = copy.deepcopy(CONFIG)
        small['clustering']['point_cap'] = 10
        capped = api.map_payload(conn, small, release, LOCAL, 12, defaults)
        assert capped['mode'] == 'clusters' and sum(c['count'] for c in capped['clusters']) == capped['total'] == 65
        assert 'zoom in' in capped['message'].lower()
        small['clustering']['cluster_cap'] = 2
        with pytest.raises(HTTPException) as error:
            api.map_payload(conn, small, release, LOCAL, 14, defaults)
        assert error.value.status_code == 413
        low_zoom = api.map_payload(conn, CONFIG, release, LOCAL, 6, defaults)
        assert low_zoom['mode'] == 'clusters' and 'Zoom to level 8' in low_zoom['message']
        for call in (lambda: api.table_payload(conn, CONFIG, release, LOCAL, defaults, 201, 0),
                     lambda: api.chemicals_payload(conn, CONFIG, release, None, 201, 0),
                     lambda: api.detail_payload(conn, CONFIG, release, F1, 201, 0)):
            with pytest.raises(HTTPException) as error:
                call()
            assert error.value.status_code == 400


def test_detail_chemical_list_and_release_pinning(engine, tmp_path):
    release, _ = staged_and_published(engine, tmp_path)
    with engine.connect() as conn:
        detail = api.detail_payload(conn, CONFIG, release, F1, 100, 0)
        assert detail['facility_id'] == F1 and detail['reporting_year'] == 2024 and detail['processed_as_of'] == '2025-11-05'
        assert detail['forms'] == {'total': 4, 'form_r': 3, 'form_a': 1} and detail['chemical_total'] == 2
        assert detail['location']['facilities_at_location'] == 2 and detail['location']['published_latitude'] == '32.512345'
        assert detail['location']['derived_county_geoid'] == '01001' and detail['location']['derived_county_name'] == 'West County'
        assert detail['epa_link']['url'].endswith(f'pgm_sys_id_in={F1}&pgm_sys_acrnm_in=TRIS')
        assert {c['chemical_id']: c['forms'] for c in detail['chemicals']} == {C1: 2, 'N420': 2}
        assert 'quantit' in detail['quantities_note'] and 'current operation' in detail['reporting_note']
        assert not any(key in json.dumps(detail) for key in ('FUGITIVE', 'STACK AIR', 'TOTAL RELEASES'))
        page = api.detail_payload(conn, CONFIG, release, F1, 1, 1)
        assert len(page['chemicals']) == 1 and page['chemical_total'] == 2
        for facility_id in (F6, F7, F8, '00000NOTREAL00A'):
            with pytest.raises(HTTPException) as error:
                api.detail_payload(conn, CONFIG, release, facility_id, 10, 0)
            assert error.value.status_code == 404
        listed = api.chemicals_payload(conn, CONFIG, release, None, 2, 0)
        assert listed['total'] == 4 and len(listed['rows']) == 2
        lead = api.chemicals_payload(conn, CONFIG, release, 'lead', 50, 0)
        assert [r['chemical_id'] for r in lead['rows']] == ['N420'] and lead['rows'][0]['mapped_facilities'] == 1
        c1 = api.chemicals_payload(conn, CONFIG, release, C1, 50, 0)['rows'][0]
        assert c1['facilities'] == 65 and c1['mapped_facilities'] == 62
        assert api.chemicals_payload(conn, CONFIG, release, '100%_', 50, 0)['total'] == 0
        candidate, _ = stage(engine, tmp_path, fixture_rows() + [form('88888NEWFC0088A', C1, doc=doc_number(8888))])
        for call in (lambda: api.map_payload(conn, CONFIG, candidate, LOCAL, 10, api.parse_filters(CONFIG)),
                     lambda: api.detail_payload(conn, CONFIG, uuid.uuid4(), F1, 10, 0),
                     lambda: api.chemicals_payload(conn, CONFIG, candidate, None, 10, 0)):
            with pytest.raises(HTTPException) as error:
                call()
            assert error.value.status_code == 404
