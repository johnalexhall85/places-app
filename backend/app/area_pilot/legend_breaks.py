"""Quintile class breaks for area legends.

Equal-width classes between the lowest and highest value let one outlier push most areas into
the lightest class. These breaks are the 20th, 40th, 60th, and 80th percentiles of the published
values for one release, measure, and geography level across the whole release, so they do not
change with the viewport. They are display classes only: no value is derived or stored.
"""
from sqlalchemy import text

VALUE_STATUSES = ('available', 'true_zero')
KEYS = ('release', 'measure', 'period', 'population', 'value_type', 'level')
BASIS = 'quintiles_of_published_values_in_release'


def quantile_breaks(db, table: str, p: dict, by_level: bool = False):
    """Four ascending cut points, or None when fewer than five published values exist."""
    level = ' AND level=:level' if by_level else ''
    row = db.execute(text(f'''SELECT count(*) AS n,
        percentile_cont(ARRAY[0.2,0.4,0.6,0.8]) WITHIN GROUP (ORDER BY value) AS cuts
        FROM {table} WHERE release_id=:release AND measure_id=:measure AND observation_period=:period
        AND population=:population AND value_type=:value_type{level}
        AND value IS NOT NULL AND status IN ('available','true_zero')'''),
        {key: p[key] for key in KEYS if key in p}).mappings().one()
    if not row['n'] or row['n'] < 5 or row['cuts'] is None:
        return None
    return [float(cut) for cut in row['cuts']]


def legend_fields(db, table: str, p: dict, by_level: bool = False) -> dict:
    return {'quantile_breaks': quantile_breaks(db, table, p, by_level), 'quantile_basis': BASIS}
