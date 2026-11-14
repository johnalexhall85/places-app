"""Unit tests for the EPA TRI reporting-facility product. All facilities and forms are synthetic."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.area_pilot import tri_api, tri_cli
from app.area_pilot.tri import (MAPPED, apply_boundary, build_relationships, facility_locations, iter_rows,
                                load_registry, parse_coordinates, profile_csv, semantic_sha, validate, verify_basic_page)
from app.demo_access.middleware import _is_public_path
from tri_synthetic import BASE, F, HEADER, config, doc_number, form, page_html, write_csv

CONFIG = config()


def profile_of(tmp_path, rows, name='t.csv'):
    return profile_csv(write_csv(tmp_path / name, rows), CONFIG)


# ---------------------------------------------------------------- registry and source contract

def test_registry_is_manual_year_pinned_and_reads_no_quantity_columns():
    registry = load_registry()
    assert registry['refresh_policy']['auto_publish'] is False
    assert registry['reporting_year'] == 2024 and '2024_US' in registry['source_urls']['basic_csv']
    quantity_columns = set(HEADER[50:])
    assert not quantity_columns & set(registry['fields'].values())
    assert registry['short_label'] == 'TRI reporting facilities'
    text = ' '.join(registry['interpretation'])
    for phrase in ('does not establish a regulatory violation', 'does not establish the absence of pollution',
                   'not necessarily released to air, or released at all', 'does not show that the facility is operating today'):
        assert phrase in text


def test_header_is_exact_and_column_count_is_enforced(tmp_path):
    path = write_csv(tmp_path / 'bad.csv', [form('00001TSTFC0001A')], header=[*HEADER[:-1], 'EXTRA'])
    with pytest.raises(ValueError, match='header differs'):
        list(iter_rows(path, CONFIG))
    good = write_csv(tmp_path / 'good.csv', [form('00001TSTFC0001A')])
    good.write_text(good.read_text() + '1,2,3\r\n')
    with pytest.raises(ValueError, match='columns, expected 122'):
        list(iter_rows(good, CONFIG))


def test_basic_page_gives_processing_date_and_fails_closed():
    result = verify_basic_page(page_html(), CONFIG)
    assert result['processed_as_of'] == '2025-11-05' and result['newer_year_listed'] is False
    assert verify_basic_page(page_html(years=(2025, 2024)), CONFIG)['newer_year_listed'] is True
    with pytest.raises(ValueError, match='no longer lists reporting year 2024'):
        verify_basic_page(page_html(years=(2023,)), CONFIG)
    with pytest.raises(ValueError, match='template changed'):
        verify_basic_page(page_html(omit='template'), CONFIG)
    with pytest.raises(ValueError, match='wording changed'):
        verify_basic_page(page_html(omit=BASE['basic_page_phrases'][1]), CONFIG)


# ---------------------------------------------------------------- grain, keys, and relationships

def test_multiple_forms_per_facility_and_chemical_are_all_kept(tmp_path):
    rows = [form('00001TSTFC0001A', '0000050000', doc=doc_number(1), naics='325199'),
            form('00001TSTFC0001A', '0000050000', doc=doc_number(2), naics='325180', sector='325'),
            form('00001TSTFC0001A', 'N420', doc=doc_number(3), chemical='Lead compounds', form_type='A'),
            form('00001TSTFC0001A', 'N420', doc=doc_number(4), chemical='Lead  And Lead Compounds'),
            form('00002TSTFC0002A', '0000050000', doc=doc_number(5))]
    profile = profile_of(tmp_path, rows)
    checks, issues = validate(profile, CONFIG)
    assert all(checks.values()) and issues['multi_form_facility_chemical_pairs'] == 2
    facilities, pairs, chemicals = build_relationships(profile)
    assert len(profile.reports) == 5 and len(facilities) == 2 and len(pairs) == 3
    assert pairs[('00001TSTFC0001A', '0000050000')]['reports'] == 2
    assert pairs[('00001TSTFC0001A', 'N420')]['forms'] == {'A', 'R'}
    assert sorted(profile.chemical_names['N420']) == ['Lead  And Lead Compounds', 'Lead compounds']
    assert len(chemicals['0000050000']['facilities']) == 2 and chemicals['0000050000']['reports'] == 3
    assert facilities['00001TSTFC0001A']['naics'] == {'325199', '325180'}


def test_validation_detects_duplicate_keys_year_conflicts_and_unreviewed_values(tmp_path):
    rows = [form('00001TSTFC0001A', doc=doc_number(1)), form('00001TSTFC0001A', '0000060000', doc=doc_number(1))]
    checks, issues = validate(profile_of(tmp_path, rows, 'dup.csv'), CONFIG)
    assert not checks['report_keys_valid_unique'] and issues['duplicate_doc_ctrl_nums'] == [doc_number(1)]
    rows = [form('00001TSTFC0001A', doc=doc_number(1)), form('00001TSTFC0001A', '0000060000', doc=doc_number(2), name='OTHER NAME'),
            form('00002TSTFC0002A', doc=doc_number(3), lat='33.1', lon='-86.1')]
    checks, issues = validate(profile_of(tmp_path, rows, 'conflict.csv'), CONFIG)
    assert not checks['facility_attributes_consistent'] and issues['facility_conflicts'] == {'00001TSTFC0001A': ['facility_name']}
    rows = [form('00001TSTFC0001A', doc=doc_number(1), **{F['year']: '2023'})]
    assert not validate(profile_of(tmp_path, rows, 'year.csv'), CONFIG)[0]['reporting_year']
    rows = [form('00001TSTFC0001A', doc=doc_number(1), **{F['horizontal_datum']: 'NAD27'}),
            form('00002TSTFC0002A', doc=doc_number(2), sector='325', **{F['industry_sector']: 'Renamed'})]
    checks, issues = validate(profile_of(tmp_path, rows, 'vocab.csv'), CONFIG)
    assert not checks['reviewed_vocabularies']
    assert issues['unreviewed_values']['horizontal_datum'] == ['NAD27'] and issues['unreviewed_values']['industry_sector']
    rows = [form('bad-id', doc=doc_number(1)), form('00002TSTFC0002A', 'not a chem', doc='1323000000001')]
    checks, _ = validate(profile_of(tmp_path, rows, 'ids.csv'), CONFIG)
    assert not checks['facility_and_chemical_ids_valid'] and not checks['report_keys_valid_unique']


# ---------------------------------------------------------------- coordinates and boundaries

@pytest.mark.parametrize('lat,lon,expected', [
    ('', '', 'no_published_coordinates'), ('32.1', '', 'invalid_coordinates'), ('abc', '-86.1', 'invalid_coordinates'),
    ('95.123456', '-86.123456', 'invalid_coordinates'), ('32.123456', '-186.123456', 'invalid_coordinates'),
    ('0', '0', 'invalid_coordinates'), ('32.12', '-86.123456', 'coarse_coordinate'), ('32.123', '-86.123', MAPPED)])
def test_coordinate_statuses_never_repair_values(lat, lon, expected):
    assert parse_coordinates(lat, lon)[3] == expected


def test_colocated_facilities_stay_distinct_and_state_mismatch_is_flagged_not_excluded(tmp_path):
    rows = [form('00001TSTFC0001A', doc=doc_number(1)), form('00002TSTFC0002A', doc=doc_number(2)),
            form('00003TSTFC0003A', doc=doc_number(3), state='GA', lat='32.612345', lon='-85.612345'),
            form('00004TSTFC0004A', doc=doc_number(4), state='GU', lat='13.44123', lon='144.79123'),
            form('00005TSTFC0005A', doc=doc_number(5), lat='', lon='')]
    profile = profile_of(tmp_path, rows)
    locations = facility_locations(profile, CONFIG)
    derived = {'00001TSTFC0001A': '01001', '00002TSTFC0002A': '01001', '00003TSTFC0003A': '01003'}
    final = apply_boundary(locations, derived, profile, CONFIG)
    assert final['00001TSTFC0001A']['status'] == final['00002TSTFC0002A']['status'] == MAPPED
    assert final['00003TSTFC0003A']['status'] == MAPPED and final['00003TSTFC0003A']['boundary_check'] == 'outside_published_state'
    assert final['00004TSTFC0004A']['boundary_check'] == 'outside_chip_boundary_layer'
    assert final['00005TSTFC0005A']['status'] == 'no_published_coordinates'
    assert final['00005TSTFC0005A']['boundary_check'] == 'not_applicable' and final['00005TSTFC0005A']['lon'] is None


def test_semantic_checksum_is_order_independent_and_covers_every_column(tmp_path):
    rows = [form('00001TSTFC0001A', doc=doc_number(1)), form('00002TSTFC0002A', doc=doc_number(2))]
    first = semantic_sha(profile_of(tmp_path, rows, 'a.csv'))
    assert semantic_sha(profile_of(tmp_path, list(reversed(rows)), 'b.csv')) == first
    changed = [dict(rows[0]), rows[1]]
    changed[0][HEADER[51]] = '2.000'  # a quantity column: never displayed, but part of the snapshot identity
    assert semantic_sha(profile_of(tmp_path, changed, 'c.csv')) != first


# ---------------------------------------------------------------- lifecycle guards without a database

class Recorder:
    def __init__(self, row=None):
        self.row, self.statements = row, []

    def execute(self, statement, params=None, **_):
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
        raise RuntimeError('EPA TRI download failed after 3 attempts')
    monkeypatch.setattr(tri_cli, 'retrieve', broken)
    engine = Recorder()
    _, report = tri_cli.fetch_stage(engine, CONFIG, directory=tmp_path)
    assert report['status'] == 'held' and 'download failed' in report['hold_reason']
    assert not any('active_release' in s for s in engine.statements)


def test_blocking_validation_holds_without_staging(tmp_path):
    engine = Recorder()
    rows = [form('00001TSTFC0001A', doc=doc_number(1)), form('00001TSTFC0001A', '0000060000', doc=doc_number(1))]
    profile = profile_of(tmp_path, rows)
    _, report = tri_cli.fetch_stage(engine, CONFIG, fetched=(profile, [], {'page': {'processed_as_of': '2025-11-05'}}))
    assert report['hold_reason'] == 'blocking_validation_failed'
    assert not any('tri_' in s or 'active_release' in s for s in engine.statements)


def test_publish_and_hold_release_require_exact_state_and_checksums():
    held = Recorder({'dataset_id': CONFIG['dataset_id'], 'status': 'held', 'report': {'hold_reason': 'validation_failed'}})
    with pytest.raises(ValueError, match='not ready'):
        tri_cli.publish(held, CONFIG, 'c', 'a', 'b', 'c')
    with pytest.raises(ValueError, match='not an eligible'):
        tri_cli.release_reviewed_hold(held, CONFIG, 'c', 'a', 'b', 'c', 'reviewed')
    ready = Recorder({'dataset_id': CONFIG['dataset_id'], 'status': 'ready', 'semantic_sha256': 'x',
                      'schema_sha256': 'y', 'metadata_sha256': 'z'})
    with pytest.raises(ValueError, match='reviewed checksums'):
        tri_cli.publish(ready, CONFIG, 'c', 'x', 'y', 'other')
    other_product = Recorder({'dataset_id': 'hrsa_health_center_sites', 'status': 'ready'})
    with pytest.raises(ValueError, match='not ready'):
        tri_cli.publish(other_product, CONFIG, 'c', 'x', 'y', 'z')
    with pytest.raises(ValueError, match='retained published TRI'):
        tri_cli.set_pointer(Recorder(), CONFIG, 'rollback', 'not-published')
    for engine in (held, ready, other_product):
        assert not any('INSERT INTO area_pilot.active_release' in s for s in engine.statements)


# ---------------------------------------------------------------- read API contracts

def test_filters_default_explicit_empty_and_unknown():
    defaults = tri_api.parse_filters(CONFIG)
    assert defaults['sector'] == sorted(s['code'] for s in CONFIG['industry_sectors']) and defaults['chemical'] is None
    assert tri_api.parse_filters(CONFIG, '325,211', ' N420 ') == {'sector': ['211', '325'], 'chemical': 'N420'}
    for sector, chemical in ((',', None), ('999,000', None), (None, 'X' * 13)):
        with pytest.raises(HTTPException) as error:
            tri_api.parse_filters(CONFIG, sector, chemical)
        assert error.value.status_code == 400


def test_tri_routes_are_authenticated_and_bbox_is_required_and_bounded():
    for name in ('catalog', 'map', 'table', 'detail', 'chemicals'):
        assert not _is_public_path(f'/area/tri/{name}') and not _is_public_path(f'/api/area/tri/{name}')
    for bbox in ('', '1,2,3', '-200,0,0,10', '10,0,5,10'):
        with pytest.raises(HTTPException) as error:
            tri_api.query_params('r', bbox, tri_api.parse_filters(CONFIG))
        assert error.value.status_code == 400


def test_detail_link_uses_the_verified_frs_tris_pattern():
    url = CONFIG['detail_link']['template'].format(facility_id='00001TSTFC0001A')
    assert url == ('https://frs-public.epa.gov/ords/frs_public2/fii_query_dtl.disp_program_facility'
                   '?pgm_sys_id_in=00001TSTFC0001A&pgm_sys_acrnm_in=TRIS')
