from copy import deepcopy

import pytest
from fastapi import HTTPException

from app.area_pilot.cms_nursing_homes import load_registry, location, typed, validate
from app.area_pilot.cms_nursing_homes_api import parse_filters


def source_row(**changes):
    row = {
        'CMS Certification Number (CCN)': '015009', 'Provider Name': 'Example Home',
        'Provider Address': '1 MAIN ST', 'City/Town': 'Example', 'State': 'AL',
        'ZIP Code': '01234', 'County/Parish': 'Example',
        'Provider Type': 'Medicare and Medicaid', 'Ownership Type': 'Non profit - Corporation',
        'Number of Certified Beds': '0', 'Overall Rating': '1', 'Overall Rating Footnote': '',
        'Health Inspection Rating': '2', 'Health Inspection Rating Footnote': '',
        'Staffing Rating': '3', 'Staffing Rating Footnote': '',
        'QM Rating': '4', 'QM Rating Footnote': '',
        'Latitude': '34.5', 'Longitude': '-87.7', 'Geocoding Footnote': '',
        'Processing Date': '2026-10-01',
    }
    row.update(changes)
    return row


def test_leading_zero_ccn_beds_zero_and_ratings_are_distinct():
    item = typed(source_row(), load_registry())
    assert item['ccn'] == '015009'
    assert item['beds'] == 0
    assert [item[k] for k in ('overall', 'health', 'staffing', 'qm')] == [1, 2, 3, 4]
    assert item['location_status'] == 'mapped'


def test_unrated_has_null_value_and_published_explanation():
    item = typed(source_row(**{'Overall Rating': '', 'Overall Rating Footnote': '18'}), load_registry())
    assert item['overall'] is None
    assert item['footnotes']['overall']['code'] == '18'
    assert 'special focus' in item['footnotes']['overall']['explanation']
    with pytest.raises(ValueError, match='Unexplained missing'):
        typed(source_row(**{'Overall Rating': ''}), load_registry())
    with pytest.raises(ValueError, match='Invalid Overall Rating'):
        typed(source_row(**{'Overall Rating': '0'}), load_registry())


def test_zip_based_geocode_is_retained_without_a_point():
    row = source_row(**{'Geocoding Footnote': '22'})
    item = typed(row, load_registry())
    assert item['location_status'] == 'zip_based_coordinate'
    assert item['source_latitude'] == '34.5'
    assert item['lon'] is None and item['lat'] is None
    assert location(source_row(**{'Latitude': '', 'Longitude': ''}))[0] == 'no_published_coordinates'
    assert location(source_row(**{'Latitude': '99'}))[0] == 'invalid_coordinates'


def test_duplicate_ccn_holds_including_conflicting_rows():
    config = deepcopy(load_registry())
    config['expected_source_rows'] = {'min': 2, 'max': 2}
    rows = [source_row(), source_row(**{'Provider Name': 'Different campus'})]
    checks, issues, records = validate(rows, config)
    assert checks['ccn_valid_unique'] is False
    assert issues['duplicate_ccns'] == ['015009']
    assert records == []


def test_overall_filter_keeps_unrated_separate_and_rejects_unknown_values():
    choices = {'provider_type': ['Medicare', 'Medicaid'], 'ownership': ['Non profit - Corporation']}
    filters = parse_filters(choices, overall='unrated')
    assert filters['overall'] == ['unrated']
    assert parse_filters(choices)['overall'] == ['1', '2', '3', '4', '5', 'unrated']
    with pytest.raises(HTTPException):
        parse_filters(choices, overall='0')
