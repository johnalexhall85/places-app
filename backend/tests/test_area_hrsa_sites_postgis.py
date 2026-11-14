"""PostGIS integration tests for HRSA health center sites in an isolated scratch database.

The scratch database is created from scratch on the local PostGIS server, migrated with the real
shared-release and site migrations, populated with synthetic boundaries and synthetic sites, and
dropped afterwards. No real withheld location is used or inferred. Skips if PostGIS is unreachable.
"""
import copy
import csv
import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.area_pilot import hrsa_sites_api as api
from app.area_pilot import hrsa_sites_cli as cli
from app.area_pilot.hrsa_sites import file_evidence, load_registry, parse_csv, parse_metadata
from app.db import DATABASE_URL

VERSIONS = Path(__file__).resolve().parents[1] / 'alembic' / 'versions'
TEST_DB = 'chip_hrsa_sites_test'
BASE = load_registry()
CONFIG = copy.deepcopy(BASE) | {'expected_source_rows': {'min': 1, 'max': 1000}}
HEADER = BASE['expected_header']
NATIONAL = '-180,-85,180,85'
LOCAL = '-87,32,-85,33'


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
            migration('e9b3f6a2c4d8_add_hrsa_health_center_sites').upgrade()
    yield test_engine
    test_engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)'))


@pytest.fixture(autouse=True)
def clean(engine):
    with engine.begin() as conn:
        conn.execute(text('''TRUNCATE area_pilot.site_hrsa, area_pilot.stage_hrsa_site, area_pilot.active_release,
            area_pilot.validation, area_pilot.source_file, area_pilot.run, area_pilot.release CASCADE'''))


def site(site_id, x, y, fips='01001', state='AL', state_fips='01', city='Testville', address='1 Synthetic Way',
         setting='All Other Clinic Types', site_type='Service Delivery Site', snapshot='11/14/2026', name=None):
    program = 'LAL' if '-LAL-' in site_id else 'H80'
    row = {h: '' for h in HEADER if h}
    row |= {'Health Center Type': BASE['program_consistency'][program]['program'],
            'Health Center Number': BASE['program_consistency'][program]['health_center_number_prefix'] + '00001',
            'BPHC Assigned Number': site_id, 'Site Name': name or f'Synthetic {site_id}', 'Site Address': address,
            'Site City': city, 'Site State Abbreviation': state, 'Site Postal Code': '00000',
            'Site Telephone Number': '555-555-0100',
            'Health Center Service Delivery Site Location Setting Description': setting,
            'Site Status Description': 'Active', 'Health Center Location Type Description': 'Permanent',
            'Health Center Type Description': site_type, 'Health Center Operator Description': 'Health Center/Applicant',
            'Health Center Operational Schedule Description': 'Unknown', 'Health Center Operating Calendar': 'Unknown',
            'Site Added to Scope this Date': '01/01/2001', 'Health Center Name': 'Synthetic Health Org',
            'Geocoding Artifact Address Primary X Coordinate': x, 'Geocoding Artifact Address Primary Y Coordinate': y,
            'State and County Federal Information Processing Standard Code': fips, 'State FIPS Code': state_fips,
            'Data Warehouse Record Create Date': snapshot}
    return row


def fixture_rows(snapshot='11/14/2026'):
    rows = [
        site('BPS-H80-000001', '-86.51234567', '32.51234567', name='Colocated A', snapshot=snapshot),
        site('BPS-H80-000002', '-86.51234567', '32.51234567', name='Colocated B', snapshot=snapshot),
        site('BPS-LAL-000003', '-85.51234567', '32.51234567', fips='01003', snapshot=snapshot),
        # Isolated synthetic suppressed record that (unlike real HRSA rows) carries coordinates and an address.
        site('BPS-H80-000004', '-86.41234567', '32.41234567', setting='Domestic Violence', address='9 Secret Rd', snapshot=snapshot),
        site('BPS-H80-000005', '', '', fips='     ', state='XX', state_fips='XX', city='', address='', snapshot=snapshot),
        site('BPS-H80-000006', '-200.12345678', '32.51234567', snapshot=snapshot),
        site('BPS-H80-000007', '-85.71234567', '32.71234567', fips='01001', snapshot=snapshot),  # lies in 01003
        site('BPS-H80-000008', '144.79123456', '13.44123456', fips='66010', state='GU', state_fips='66', snapshot=snapshot),
        site('BPS-H80-000009', '-86.31234567', '32.31234567', site_type='Administrative', snapshot=snapshot),
        site('BPS-H80-000010', '-86.71234567', '32.71234567', city='North', snapshot=snapshot),
        site('BPS-H80-000011', '-86.71234567', '32.71234567', city='South', snapshot=snapshot),
        site('BPS-H80-000012', '-86.61', '32.61234567', snapshot=snapshot),
        site('BPS-H80-000013', '-86.21234567', '32.21234567', fips='', snapshot=snapshot),
    ]
    for i in range(60):  # grid in West County for clustering
        rows.append(site(f'BPS-H80-{100 + i:06d}', f'-86.{9 - i % 8}{i:02d}34567', f'32.{1 + i // 8}{i:02d}34567', snapshot=snapshot))
    return rows


def write_inputs(directory, rows):
    import openpyxl

    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / 'sites.csv'
    with csv_path.open('w', newline='', encoding='utf-8') as out:
        writer = csv.writer(out, lineterminator='\r\n')
        writer.writerow(HEADER)
        for row in rows:
            writer.writerow([row[h] for h in HEADER if h])
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = BASE['metadata_sheet']
    sheet.append(BASE['metadata_header'])
    for column in (h for h in HEADER if h):
        definition = BASE['metadata_phrases'].get(column, 'Synthetic definition.')
        restriction = 'Restricted' if column == 'Site Added to Scope this Date' else 'Public'
        sheet.append([column, column.upper(), column, definition, restriction, 'HRSA', 'Daily', 'text', '', '', '', '2026/01/01'])
    xlsx_path = directory / 'metadata.xlsx'
    workbook.save(xlsx_path)
    pages = {}
    for role in ('download_page', 'topic_page'):
        pages[role] = directory / f'{role}.html'
        pages[role].write_text('<html>synthetic</html>', encoding='utf-8')
    files = [file_evidence(pages['download_page'], 'u', 'download_page'), file_evidence(pages['topic_page'], 'u', 'topic_page'),
             file_evidence(xlsx_path, 'u', 'metadata_xlsx'), file_evidence(csv_path, 'u', 'sites_csv')]
    provenance = {'http': {'sites_csv': {'last-modified': 'synthetic'}}, 'pages': {'topic_updated': None},
                  'restricted_attributes': ['Site Added to Scope this Date'], 'retrieved_at': '2026-11-14T00:00:00+00:00'}
    return parse_csv(csv_path, CONFIG), files, provenance, parse_metadata(xlsx_path, CONFIG)


def stage(engine, tmp_path, rows):
    return cli.fetch_stage(engine, CONFIG, directory=tmp_path, fetched=write_inputs(tmp_path / uuid.uuid4().hex, rows))


def publish(engine, candidate, report):
    cli.publish(engine, CONFIG, candidate, report['semantic_sha256'], report['schema_sha256'], report['metadata_sha256'])


def read(engine, fn, *args):
    """Run one read-only API call on a connection that is closed afterwards (no lingering locks)."""
    with engine.connect() as conn:
        return fn(conn, *args)


def staged_and_published(engine, tmp_path):
    candidate, report = stage(engine, tmp_path, fixture_rows())
    assert report['status'] == 'ready', report
    publish(engine, candidate, report)
    return candidate, report


# ---------------------------------------------------------------- lifecycle

def test_stage_review_publish_with_explicit_location_statuses(engine, tmp_path):
    candidate, report = stage(engine, tmp_path, fixture_rows())
    assert report['status'] == 'ready' and all(report['checks'].values())
    counts = report['summary']['location_status_counts']
    assert counts == {'mapped': 65, 'suppressed_source_policy': 1, 'no_published_coordinates': 1,
                      'invalid_coordinates': 1, 'outside_published_county': 1, 'approximate_shared_coordinate': 2,
                      'coarse_coordinate': 1, 'published_county_not_in_boundary_layer': 1}
    assert report['summary']['source_rows'] == sum(counts.values()) == 73
    checked = cli.review(engine, candidate, CONFIG)
    assert checked['sites_verified'] == checked['staged_rows'] == 73 and checked['mapped_sites_verified'] == 65
    publish(engine, candidate, report)
    with engine.connect() as conn:
        dv = conn.execute(text('''SELECT source_x,source_y,geom,attributes FROM area_pilot.site_hrsa
            WHERE site_id='BPS-H80-000004' ''')).mappings().one()
        assert dv['source_x'] is None and dv['geom'] is None and dv['attributes']['site_address'] is None
        # The raw source row stays in staging only, which the API never reads.
        assert conn.execute(text('''SELECT record->>'Site Address' FROM area_pilot.stage_hrsa_site
            WHERE site_id='BPS-H80-000004' ''')).scalar_one() == '9 Secret Rd'
        island = conn.execute(text('''SELECT location_status,boundary_check FROM area_pilot.site_hrsa
            WHERE site_id='BPS-H80-000008' ''')).one()
        assert tuple(island) == ('mapped', 'outside_chip_boundary_layer')
        assert conn.execute(text('SELECT release_id FROM area_pilot.active_release')).scalar_one() == candidate
    with pytest.raises(Exception, match='immutable'):
        with engine.begin() as conn:
            conn.execute(text("UPDATE area_pilot.site_hrsa SET site_name='changed' WHERE site_id='BPS-H80-000001'"))
    catalog = read(engine, api.catalog_payload, CONFIG)
    assert catalog['active_release_id'] == str(candidate) and catalog['snapshot_date'] == '2026-11-14'
    assert catalog['counts']['source_sites'] == 73 and catalog['counts']['mapped_eligible_sites'] == 65
    assert catalog['counts']['default_filter_mapped_sites'] == 64  # administrative-only site off by default
    assert catalog['counts']['not_mapped_by_reason']['suppressed_source_policy'] == 1
    assert all(v['code'] != 'domestic_violence' for f in catalog['filters'] for v in f['values'])


def test_review_detects_tampered_read_model_and_archive(engine, tmp_path):
    candidate, _ = stage(engine, tmp_path, fixture_rows())
    with engine.begin() as conn:
        conn.execute(text("UPDATE area_pilot.site_hrsa SET site_name='Tampered' WHERE site_id='BPS-H80-000001' AND release_id=:r"),
                     {'r': candidate})
    with pytest.raises(ValueError, match='read model differs'):
        cli.review(engine, candidate, CONFIG)
    with engine.begin() as conn:
        path = conn.execute(text("SELECT path FROM area_pilot.source_file WHERE release_id=:r AND role='sites_csv'"),
                            {'r': candidate}).scalar_one()
    Path(path).write_text('tampered', encoding='utf-8')
    with pytest.raises(ValueError, match='checksum mismatch'):
        cli.review(engine, candidate, CONFIG)


def test_idempotent_rerun_changed_content_holds_and_pointer_recovery(engine, tmp_path):
    first, report = staged_and_published(engine, tmp_path)
    again, duplicate = stage(engine, tmp_path, fixture_rows(snapshot='11/15/2026'))
    assert again == first and duplicate['status'] == 'duplicate' and duplicate['confirmed_snapshot_date'] == '2026-11-15'
    assert read(engine, api.catalog_payload, CONFIG)['counts']['last_confirmed_snapshot_date'] == '2026-11-15'
    changed = fixture_rows()
    changed[0]['Site Name'] = 'Renamed under the same snapshot label'
    held, same_label = stage(engine, tmp_path, changed)
    assert same_label['status'] == 'held' and same_label['hold_reason'] == 'same_label_semantic_revision'
    large = fixture_rows(snapshot='11/16/2026')
    for row in large[20:40]:
        row['Site Telephone Number'] = '555-555-0199'
    big, big_report = stage(engine, tmp_path, large)
    assert big_report['hold_reason'] == 'large_change_vs_active'
    assert big_report['change_vs_active']['changed'] == 20
    with pytest.raises(ValueError, match='not ready'):
        publish(engine, big, big_report)
    cli.release_reviewed_hold(engine, CONFIG, big, big_report['semantic_sha256'], big_report['schema_sha256'],
                              big_report['metadata_sha256'], 'Synthetic phone update reviewed')
    publish(engine, big, big_report)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT release_id FROM area_pilot.active_release')).scalar_one() == big
    cli.set_pointer(engine, CONFIG, 'rollback', first)
    assert read(engine, api.catalog_payload, CONFIG)['active_release_id'] == str(first)
    with pytest.raises(ValueError, match='retained published'):
        cli.set_pointer(engine, CONFIG, 'rollback', held)
    cli.set_pointer(engine, CONFIG, 'deactivate')
    assert read(engine, api.catalog_payload, CONFIG)['active_release_id'] is None
    # Published content stays queryable by release ID after deactivation.
    assert read(engine, api.table_payload, CONFIG, first, LOCAL, api.parse_filters(CONFIG, {}), 10, 0)['total'] == 63


def test_failed_candidates_preserve_active_release(engine, tmp_path, monkeypatch):
    first, _ = staged_and_published(engine, tmp_path)
    duplicate_ids = fixture_rows(snapshot='11/17/2026')
    duplicate_ids.append(dict(duplicate_ids[0]))
    held, report = stage(engine, tmp_path, duplicate_ids)
    assert report['hold_reason'] == 'blocking_validation_failed' and report['issues']['duplicate_site_ids'] == ['BPS-H80-000001']

    def broken(*_):
        raise RuntimeError('HRSA download failed after 3 attempts')
    monkeypatch.setattr(cli, 'retrieve', broken)
    _, failed = cli.fetch_stage(engine, CONFIG, directory=tmp_path)
    assert failed['status'] == 'held'
    with engine.connect() as conn:
        assert conn.execute(text('SELECT release_id FROM area_pilot.active_release')).scalar_one() == first
        assert conn.execute(text('SELECT count(*) FROM area_pilot.site_hrsa WHERE release_id=:r'), {'r': held}).scalar_one() == 0


# ---------------------------------------------------------------- read API on real PostGIS

def all_table_rows(conn, release, bbox, filters):
    rows, offset = [], 0
    while True:
        page = api.table_payload(conn, CONFIG, release, bbox, filters, 7, offset)
        rows += page['rows']
        offset += 7
        if offset >= page['total']:
            return page['total'], rows


def test_cluster_points_and_table_parity_under_filters(engine, tmp_path):
    release, _ = staged_and_published(engine, tmp_path)
    with engine.connect() as conn:
        defaults = api.parse_filters(CONFIG, {})
        for filters in (defaults, api.parse_filters(CONFIG, {'site_type': 'administrative'}),
                        api.parse_filters(CONFIG, {'program': 'look_alike'}),
                        api.parse_filters(CONFIG, {'site_type': 'service_delivery,admin_and_service,administrative'})):
            clusters = api.map_payload(conn, CONFIG, release, NATIONAL, 3, filters)
            points = api.map_payload(conn, CONFIG, release, LOCAL, 10, filters)
            total, rows = all_table_rows(conn, release, LOCAL, filters)
            national_total, _ = all_table_rows(conn, release, NATIONAL, filters)
            assert clusters['mode'] == 'clusters' and sum(c['count'] for c in clusters['clusters']) == clusters['total'] == national_total
            assert points['mode'] == 'points' and points['total'] == total == len(rows)
            assert sorted(p['site_id'] for p in points['points']) == sorted(r['site_id'] for r in rows)
            assert len({r['site_id'] for r in rows}) == len(rows)
        by_filter = api.map_payload(conn, CONFIG, release, LOCAL, 10, api.parse_filters(CONFIG, {'site_type': 'administrative'}))
        assert [p['site_id'] for p in by_filter['points']] == ['BPS-H80-000009']
        default_points = api.map_payload(conn, CONFIG, release, LOCAL, 10, defaults)['points']
        ids = {p['site_id'] for p in default_points}
        assert {'BPS-H80-000001', 'BPS-H80-000002'} <= ids  # colocated distinct sites both returned
        assert ids.isdisjoint({'BPS-H80-000004', 'BPS-H80-000005', 'BPS-H80-000006', 'BPS-H80-000007',
                               'BPS-H80-000009', 'BPS-H80-000010', 'BPS-H80-000011', 'BPS-H80-000012', 'BPS-H80-000013'})
        keys = {p['location_key'] for p in default_points if p['site_id'] in ('BPS-H80-000001', 'BPS-H80-000002')}
        assert keys == {'-86.51234567,32.51234567'}
        pacific = api.map_payload(conn, CONFIG, release, '144,13,145,14', 10, defaults)
        assert [p['site_id'] for p in pacific['points']] == ['BPS-H80-000008']


def test_viewport_limits_never_truncate(engine, tmp_path):
    release, _ = staged_and_published(engine, tmp_path)
    with engine.connect() as conn:
        defaults = api.parse_filters(CONFIG, {})
        small = copy.deepcopy(CONFIG)
        small['clustering']['point_cap'] = 10
        capped = api.map_payload(conn, small, release, LOCAL, 12, defaults)
        assert capped['mode'] == 'clusters' and sum(c['count'] for c in capped['clusters']) == capped['total'] == 63
        assert 'zoom in' in capped['message'].lower()
        small['clustering']['cluster_cap'] = 2
        with pytest.raises(HTTPException) as error:
            api.map_payload(conn, small, release, LOCAL, 14, defaults)
        assert error.value.status_code == 413
        low_zoom = api.map_payload(conn, CONFIG, release, LOCAL, 6, defaults)
        assert low_zoom['mode'] == 'clusters' and 'Zoom to level 8' in low_zoom['message']
        with pytest.raises(HTTPException) as error:
            api.table_payload(conn, CONFIG, release, LOCAL, defaults, 201, 0)
        assert error.value.status_code == 400


def test_detail_access_and_release_pinning(engine, tmp_path):
    release, _ = staged_and_published(engine, tmp_path)
    with engine.connect() as conn:
        detail = api.detail_payload(conn, CONFIG, release, 'BPS-H80-000001')
        assert detail['location']['sites_at_location'] == 2 and detail['location']['published_x'] == '-86.51234567'
        assert detail['attributes']['organization_name'] == 'Synthetic Health Org' and detail['site_id'] == 'BPS-H80-000001'
        assert 'services' in detail['services_note']
        for site_id in ('BPS-H80-000004', 'BPS-H80-000005', 'BPS-H80-000010', 'BPS-H80-999999'):
            with pytest.raises(HTTPException) as error:
                api.detail_payload(conn, CONFIG, release, site_id)
            assert error.value.status_code == 404
        candidate, _ = stage(engine, tmp_path, fixture_rows(snapshot='11/18/2026') + [
            site('BPS-H80-000500', '-86.11234567', '32.11234567', snapshot='11/18/2026')])
        for call in (lambda: api.map_payload(conn, CONFIG, candidate, LOCAL, 10, api.parse_filters(CONFIG, {})),
                     lambda: api.detail_payload(conn, CONFIG, uuid.uuid4(), 'BPS-H80-000001')):
            with pytest.raises(HTTPException) as error:
                call()
            assert error.value.status_code == 404
