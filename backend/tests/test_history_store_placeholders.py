"""The opt-in placeholder filter drops only blank, boundary-less area-periods."""
from decimal import Decimal

from app.area_pilot.history.rows import HistoryRow
from app.area_pilot.history.store import drop_unbounded_placeholders


def _row(geoid, measure, value, period='2016–2020', vintage='2020'):
    return HistoryRow('tract', geoid, measure, period, 'households', 'percent',
                      None if value is None else Decimal(value), 'available' if value else 'missing',
                      'none', None, None, None, value or '', vintage)


ROWS = [
    _row('01001020100', 'A', '5.1'), _row('01001020100', 'B', None),   # bounded, has a value
    _row('01001020200', 'A', None), _row('01001020200', 'B', None),    # bounded, all blank: kept
    _row('01001020500', 'A', None), _row('01001020500', 'B', None),    # no boundary, all blank: dropped
    _row('01001020600', 'A', '2.0'), _row('01001020600', 'B', None),   # no boundary, has a value: kept
]
BOUNDARIES = {('tract', '2020'): {'01001020100', '01001020200'}}


def test_filter_is_off_unless_the_registry_opts_in():
    assert drop_unbounded_placeholders(None, {}, 'p', ROWS, dict(BOUNDARIES), {}) == ROWS


def test_drops_only_blank_areas_without_a_boundary_and_counts_them():
    evidence = {}
    kept = drop_unbounded_placeholders(None, {'drop_unbounded_blank_areas': True}, 'tract_2020', ROWS,
                                       dict(BOUNDARIES), evidence)
    assert {r.geoid for r in kept} == {'01001020100', '01001020200', '01001020600'}
    assert len(kept) == 6
    assert evidence == {'dropped_unbounded_blank_areas': {'tract_2020|tract|2016–2020': 1}}
