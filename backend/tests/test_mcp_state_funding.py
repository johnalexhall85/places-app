"""CDC state funding and grant-history MCP contracts on staging."""

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import text

from app.db import SessionLocal
from app.mcp_server import tools
from app.mcp_server.config import MAX_BYTES
from app.mcp_server.envelope import size_bytes
from app.state_funding import lookup


@pytest.fixture(scope='module')
def staging():
    try:
        with SessionLocal() as db:
            if db.execute(text('select current_database()')).scalar() != 'places_staging' or not lookup.build_info(db):
                pytest.skip('active places_staging state funding build required')
    except Exception as exc:
        pytest.skip(f'staging unreachable: {type(exc).__name__}')


def test_argument_validation(staging):
    for call, message in (
        (lambda: tools.get_state_funding('ZZ'), 'Unknown state'),
        (lambda: tools.get_state_funding('CA', 2019), 'fiscal year'),
        (lambda: tools.get_state_funding('CA', funding_type='bad'), 'funding_type'),
        (lambda: tools.get_state_funding('CA', award_type='bad'), 'award_type'),
        (lambda: tools.get_state_funding('CA', recipient_type='bad'), 'recipient_type'),
        (lambda: tools.get_state_funding('CA', category='NOT_A_CATEGORY'), 'category'),
        (lambda: tools.list_state_grants('CA', limit=101), 'limit'),
        (lambda: tools.list_state_grants('CA', sort='bad'), 'sort'),
        (lambda: tools.list_state_grants('CA', direction='bad'), 'direction'),
        (lambda: tools.get_grant_history('PS212102', limit=0), 'limit'),
        (lambda: tools.get_grant_history('CDC-RFA-PS21-9999'), 'NOFO'),
    ):
        with pytest.raises(ToolError, match=message):
            call()


def test_state_names_fips_paging_and_size(staging):
    by_code = tools.get_state_funding('CA', 2026)
    by_name = tools.get_state_funding('California', 2026)
    by_fips = tools.get_state_funding('06', 2026)
    assert by_code.data['totals'] == by_name.data['totals'] == by_fips.data['totals']
    assert by_code.data['state']['code'] == 'CA'
    assert by_code.data['by_category']
    assert size_bytes(by_code) < MAX_BYTES
    first = tools.list_state_grants('CA', 2026, limit=3)
    second = tools.list_state_grants('CA', 2026, offset=3, limit=3)
    assert first.data['total_rows'] == second.data['total_rows']
    assert {r['award_unique_key'] for r in first.data['rows']}.isdisjoint(
        {r['award_unique_key'] for r in second.data['rows']})
    largest = tools.list_state_grants('CA', 2026, limit=100)
    assert size_bytes(largest) < MAX_BYTES
    assert largest.data['sum_total'] == first.data['sum_total']
    assert largest.data['next_offset'] == len(largest.data['rows'])
    assert all(len(r.get('description') or '') <= 300 for r in largest.data['rows'])


def test_grant_history_size_and_filter(staging):
    history = tools.get_grant_history('OT202004', limit=100)
    assert size_bytes(history) < MAX_BYTES
    assert history.data['nofo']['nofo_key'] == 'OT202004'
    assert history.data['by_state']
    assert all(row['history'] for row in history.data['awards'])
    assert history.data['next_offset'] == len(history.data['awards'])
    ca = tools.get_grant_history('PS212102', state='California', include_past=False, limit=10)
    assert ca.data['totals']['latest_fy']['total'] == 10166689.0
    assert all(a['state'] == 'CA' and a['is_current'] for a in ca.data['awards'])
