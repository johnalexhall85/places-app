"""Unit tests for the HRSA health center site product. All locations here are synthetic fixtures."""
import copy
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.area_pilot import hrsa_sites_api, hrsa_sites_cli
from app.area_pilot.hrsa_sites import (MAPPED, apply_boundary, load_registry, parse_csv, provisional_locations,
                                       public_attributes, semantic_sha, validate_rows, verify_pages)
from app.demo_access.middleware import _is_public_path

CONFIG = load_registry()
HEADER = CONFIG['expected_header']


def site(site_id='BPS-H80-000001', x='-86.51234567', y='32.51234567', fips='01001', state='AL', state_fips='01',
         city='Testville', address='1 Synthetic Way', setting='All Other Clinic Types', site_type='Service Delivery Site',
         status='Active', name=None, **extra):
    program = 'LAL' if '-LAL-' in site_id else 'H80'
    row = {h: '' for h in HEADER if h}
    row |= {
        'Health Center Type': CONFIG['program_consistency'][program]['program'],
        'Health Center Number': CONFIG['program_consistency'][program]['health_center_number_prefix'] + '00001',
        'BPHC Assigned Number': site_id, 'Site Name': name or f'Synthetic site {site_id[-3:]}',
        'Site Address': address, 'Site City': city, 'Site State Abbreviation': state, 'Site Postal Code': '00000',
        'Site Telephone Number': '555-555-0100', 'Site Web Address': 'example.invalid',
        'Health Center Service Delivery Site Location Setting Description': setting,
        'Site Status Description': status, 'Health Center Location Type Description': 'Permanent',
        'Health Center Type Description': site_type, 'Health Center Operator Description': 'Health Center/Applicant',
        'Health Center Operational Schedule Description': 'Full-Time', 'Health Center Operating Calendar': 'Year-Round',
        'Site Added to Scope this Date': '01/01/2001', 'Health Center Name': 'Synthetic Health Org',
        'Geocoding Artifact Address Primary X Coordinate': x, 'Geocoding Artifact Address Primary Y Coordinate': y,
        'State and County Federal Information Processing Standard Code': fips, 'State FIPS Code': state_fips,
        'Data Warehouse Record Create Date': '11/14/2026',
    }
    return row | extra


def write_csv(path, rows, header=HEADER):
    import csv
    with path.open('w', newline='', encoding='utf-8') as out:
        writer = csv.writer(out, lineterminator='\r\n')
        writer.writerow(header)
        for row in rows:
            writer.writerow([row[h] for h in header if h])
    return path


def statuses(rows, boundary=None, layer_states=('01',)):
    provisional = provisional_locations(rows, CONFIG)
    final = apply_boundary(rows, provisional, boundary or {}, set(layer_states), CONFIG)
    return {k: v['status'] for k, v in final.items()}, final


# ---------------------------------------------------------------- registry and source semantics

def test_registry_is_manual_and_never_exposes_restricted_or_suppressed_fields():
    assert CONFIG['refresh_policy']['auto_publish'] is False
    assert 'Site Added to Scope this Date' not in CONFIG['exposed_attributes'].values()
    dv = next(v for v in CONFIG['classifications']['setting']['values'] if v['source'] == 'Domestic Violence')
    assert dv['location_suppressed'] and not dv['default']
    administrative = next(v for v in CONFIG['classifications']['site_type']['values'] if v['source'] == 'Administrative')
    assert administrative['default'] is False
    assert CONFIG['location_policy']['crs'] == 'EPSG:4326'
    assert 'observation_year' not in CONFIG and 'observation_period' not in CONFIG


def test_csv_header_trailing_column_and_column_count(tmp_path):
    rows = parse_csv(write_csv(tmp_path / 'a.csv', [site()]), CONFIG)
    assert rows[0]['BPHC Assigned Number'] == 'BPS-H80-000001' and '' not in rows[0]
    with pytest.raises(ValueError, match='header differs'):
        parse_csv(write_csv(tmp_path / 'b.csv', [site()], header=HEADER[:-1]), CONFIG)
    bad = tmp_path / 'c.csv'
    bad.write_text(','.join(HEADER) + '\r\n' + 'a,b,c\r\n', encoding='utf-8')
    with pytest.raises(ValueError, match='columns'):
        parse_csv(bad, CONFIG)


def test_page_verification_requires_links_terms_and_suppression_note():
    page = ('<a href="/DataDownload/DD_Files/Health_Center_Service_Delivery_and_LookAlike_Sites.csv">c</a>'
            '<a href="/DataDownload/DD_Files/Health_Center_Service_Delivery_and_LookAlike_Sites_Data_Download_Metadata.xlsx">m</a>'
            '<p>' + ' '.join(CONFIG['download_page_phrases']) + '</p>')
    topic = '<p>' + ' 16,200 '.join(CONFIG['topic_page_phrases']) + ' Updated: 11/14/2026 Refresh Cycle: Daily</p>'
    result = verify_pages(page, topic, CONFIG)
    assert result['topic_updated'] == '2026-11-14' and result['topic_refresh_cycle'] == 'Daily'
    with pytest.raises(ValueError, match='suppression note'):
        verify_pages(page.replace('domestic violence shelters', 'shelters'), topic, CONFIG)
    with pytest.raises(ValueError, match='no longer links'):
        verify_pages(page.replace('.csv', '.zip'), topic, CONFIG)


def test_validation_reports_duplicates_conflicts_vocabulary_and_snapshot():
    config = copy.deepcopy(CONFIG) | {'expected_source_rows': {'min': 1, 'max': 100}}
    rows = [site(), site(), site('BPS-LAL-000002', **{'Health Center Type': 'Federally Qualified Health Center (FQHC)'}),
            site('BPS-H80-000003', setting='Pop-up clinic'), site('BPS-H80-000004', **{'Data Warehouse Record Create Date': '11/13/2026'}),
            site('BPS-X-1')]
    checks, issues, snapshot = validate_rows(rows, config)
    assert not checks['site_ids_valid_unique'] and issues['duplicate_site_ids'] == ['BPS-H80-000001']
    assert issues['malformed_site_ids'] == ['BPS-X-1']
    assert not checks['site_program_consistency'] and 'BPS-LAL-000002' in issues['conflicting_site_program']
    assert not checks['classification_vocabulary']
    assert issues['unreviewed_values']['Health Center Service Delivery Site Location Setting Description'] == ['Pop-up clinic']
    assert not checks['single_snapshot_date'] and snapshot is None
    good, _, day = validate_rows([site()], config)
    assert all(good.values()) and day.isoformat() == '2026-11-14'


# ---------------------------------------------------------------- location policy

def test_domestic_violence_location_is_never_mapped_even_with_coordinates():
    rows = [site('BPS-H80-000009', setting='Domestic Violence', x='-86.41234567', y='32.41234567')]
    found, final = statuses(rows, boundary={'BPS-H80-000009': True})
    assert found == {'BPS-H80-000009': 'suppressed_source_policy'}
    assert final['BPS-H80-000009']['lon'] is None and final['BPS-H80-000009']['exclusion_reason'] == 'suppressed_source_policy'
    attributes = public_attributes(rows[0], CONFIG, 'suppressed_source_policy')
    assert attributes['site_address'] is None and attributes['site_postal_code'] is None and attributes['site_phone'] is None
    values = hrsa_sites_cli.site_values(rows[0], final, CONFIG, 'r')
    assert values['source_x'] is None and values['source_y'] is None and values['x'] is None


@pytest.mark.parametrize('x, y, expected', [
    ('', '', 'no_published_coordinates'), ('-86.5', '', 'invalid_coordinates'), ('abc', '32.5', 'invalid_coordinates'),
    ('-200.0', '32.5', 'invalid_coordinates'), ('-86.5', '95.0', 'invalid_coordinates'), ('0', '0', 'invalid_coordinates'),
    ('NaN', '32.5', 'invalid_coordinates'), ('-86.51', '32.51234567', 'coarse_coordinate'),
])
def test_unmappable_coordinates_are_kept_with_explicit_status(x, y, expected):
    found, final = statuses([site(x=x, y=y)], boundary={'BPS-H80-000001': True})
    assert found['BPS-H80-000001'] == expected and final['BPS-H80-000001']['lon'] is None


def test_colocated_distinct_sites_are_retained_and_place_level_geocodes_are_excluded():
    rows = [site('BPS-H80-000001', name='Clinic A'), site('BPS-H80-000002', name='Clinic B'),
            site('BPS-H80-000003', x='-170.74700000', y='-14.31900000', city='Village One', fips='60050', state_fips='60', state='AS'),
            site('BPS-H80-000004', x='-170.74700000', y='-14.31900000', city='Village Two', fips='60050', state_fips='60', state='AS'),
            site('BPS-H80-000005', x='-86.123', y='32.456', address='10 First St'),
            site('BPS-H80-000006', x='-86.123', y='32.456', address='99 Other Rd'),
            site('BPS-H80-000007', x='-86.12345678', y='32.45678901', address='10 First St'),
            site('BPS-H80-000008', x='-86.12345678', y='32.45678901', address='12 First St')]
    found, _ = statuses(rows, boundary={f'BPS-H80-00000{i}': True for i in (1, 2, 5, 6, 7, 8)})
    assert found['BPS-H80-000001'] == found['BPS-H80-000002'] == MAPPED
    assert found['BPS-H80-000003'] == found['BPS-H80-000004'] == 'approximate_shared_coordinate'
    assert found['BPS-H80-000005'] == found['BPS-H80-000006'] == 'approximate_shared_coordinate'
    # Precise shared coordinate with nearby house numbers stays mapped (adjacent buildings).
    assert found['BPS-H80-000007'] == found['BPS-H80-000008'] == MAPPED


def test_boundary_cross_check_statuses():
    rows = [site('BPS-H80-000001'), site('BPS-H80-000002'),
            site('BPS-H80-000003', fips='', state_fips='01'),
            site('BPS-H80-000004', x='144.79123456', y='13.44123456', fips='66010', state_fips='66', state='GU')]
    found, final = statuses(rows, boundary={'BPS-H80-000001': True, 'BPS-H80-000002': False})
    assert found['BPS-H80-000001'] == MAPPED and final['BPS-H80-000001']['boundary_check'] == 'within_published_county'
    assert found['BPS-H80-000002'] == 'outside_published_county'
    assert found['BPS-H80-000003'] == 'published_county_not_in_boundary_layer'
    assert found['BPS-H80-000004'] == MAPPED and final['BPS-H80-000004']['boundary_check'] == 'outside_chip_boundary_layer'


def test_public_attributes_are_documented_public_fields_only():
    attributes = public_attributes(site(), CONFIG, MAPPED)
    assert set(attributes) == set(CONFIG['exposed_attributes'])
    assert '01/01/2001' not in json.dumps(attributes)  # restricted scope date
    assert attributes['organization_name'] == 'Synthetic Health Org' and attributes['site_name'].startswith('Synthetic site')


def test_semantic_checksum_ignores_order_and_processing_date_but_not_content():
    a, b = site('BPS-H80-000001'), site('BPS-H80-000002')
    assert semantic_sha([a, b], CONFIG) == semantic_sha([b, a], CONFIG)
    assert semantic_sha([a], CONFIG) == semantic_sha([a | {'Data Warehouse Record Create Date': '11/15/2026'}], CONFIG)
    assert semantic_sha([a], CONFIG) != semantic_sha([a | {'Site Name': 'Renamed'}], CONFIG)


# ---------------------------------------------------------------- lifecycle controls (no database)

class Recorder:
    def __init__(self, row=None):
        self.statements, self.row = [], row

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        row = self.row
        return SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: row, one_or_none=lambda: row),
                               scalar_one=lambda: 0, scalar_one_or_none=lambda: None)

    def begin(self):
        conn = self

        class Context:
            def __enter__(self): return conn
            def __exit__(self, *_): return False
        return Context()


def test_failed_retrieval_holds_and_never_touches_pointer(tmp_path, monkeypatch):
    def broken(*_):
        raise RuntimeError('HRSA download failed after 3 attempts')
    monkeypatch.setattr(hrsa_sites_cli, 'retrieve', broken)
    engine = Recorder()
    _, report = hrsa_sites_cli.fetch_stage(engine, CONFIG, directory=tmp_path)
    assert report['status'] == 'held' and 'download failed' in report['hold_reason']
    assert not any('active_release' in s for s in engine.statements)


def test_blocking_validation_holds_without_staging():
    engine = Recorder()
    rows = [site(), site()]
    _, report = hrsa_sites_cli.fetch_stage(engine, CONFIG, fetched=(rows, [], {}, {'digest': 'x'}))
    assert report['hold_reason'] == 'blocking_validation_failed'
    assert not any('site_hrsa' in s or 'active_release' in s for s in engine.statements)


def test_publish_and_hold_release_require_exact_state_and_checksums():
    held = Recorder({'dataset_id': CONFIG['dataset_id'], 'status': 'held', 'report': {'hold_reason': 'validation_failed'}})
    with pytest.raises(ValueError, match='not ready'):
        hrsa_sites_cli.publish(held, CONFIG, 'c', 'a', 'b', 'c')
    with pytest.raises(ValueError, match='not an eligible'):
        hrsa_sites_cli.release_reviewed_hold(held, CONFIG, 'c', 'a', 'b', 'c', 'reviewed')
    ready = Recorder({'dataset_id': CONFIG['dataset_id'], 'status': 'ready', 'semantic_sha256': 'x',
                      'schema_sha256': 'y', 'metadata_sha256': 'z'})
    with pytest.raises(ValueError, match='reviewed checksums'):
        hrsa_sites_cli.publish(ready, CONFIG, 'c', 'x', 'y', 'other')
    with pytest.raises(ValueError, match='retained published'):
        hrsa_sites_cli.set_pointer(Recorder(), CONFIG, 'rollback', 'not-published')
    for engine in (held, ready):
        assert not any('INSERT INTO area_pilot.active_release' in s for s in engine.statements)


# ---------------------------------------------------------------- read API contracts

def test_filters_default_explicit_empty_unknown_and_suppressed():
    defaults = hrsa_sites_api.parse_filters(CONFIG, {})
    assert defaults['site_type'] == ['admin_and_service', 'service_delivery']
    assert 'domestic_violence' not in defaults['setting']
    assert hrsa_sites_api.parse_filters(CONFIG, {'site_type': 'administrative'})['site_type'] == ['administrative']
    for raw in ({'program': ''}, {'program': 'hospital'}, {'setting': 'domestic_violence'}):
        with pytest.raises(HTTPException) as error:
            hrsa_sites_api.parse_filters(CONFIG, raw)
        assert error.value.status_code == 400


def test_site_routes_are_authenticated_and_bbox_is_required_and_bounded():
    for path in ('/area/sites/catalog', '/area/sites/map', '/area/sites/table', '/area/sites/detail',
                 '/api/area/sites/catalog', '/api/area/sites/map', '/api/area/sites/table', '/api/area/sites/detail'):
        assert not _is_public_path(path)
    for bbox in ('', '1,2,3', '-200,0,0,10', '10,0,5,10'):
        with pytest.raises(HTTPException) as error:
            hrsa_sites_api.query_params('r', bbox, {})
        assert error.value.status_code == 400


def test_cluster_cells_shrink_with_zoom():
    assert hrsa_sites_api.cluster_cell_m(4, 64) == pytest.approx(2 * hrsa_sites_api.cluster_cell_m(5, 64))
    assert hrsa_sites_api.cluster_cell_m(0, 256) == pytest.approx(hrsa_sites_api.EARTH_CIRCUMFERENCE_M)
