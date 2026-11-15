"""Map shapes must keep shared borders: no per-polygon simplification in map queries."""
from pathlib import Path

from app.geometry_sql import fitted_geom

APP = Path(__file__).resolve().parents[1] / 'app'
# Funding maps are state-level and keep their own geometry handling; lookup outlines draw one area alone.
EXEMPT = ('cdc_funding', 'taggs', 'area_pilot/lookup.py', 'geometry_sql.py')


def test_fitted_geom_snaps_to_a_common_grid_and_never_drops_a_shape():
    sql = fitted_geom('b.geom')
    assert 'ST_SnapToGrid(b.geom, CAST(:simplify AS double precision))' in sql
    assert 'ST_SimplifyPreserveTopology' not in sql
    assert sql.startswith('CASE WHEN CAST(:simplify AS double precision) <= 0 OR ST_IsEmpty(') and 'THEN b.geom ELSE' in sql
    assert ':simplify_degrees' in fitted_geom('t.geom', 'simplify_degrees')


def test_area_and_legacy_map_queries_do_not_simplify_each_polygon_separately():
    offenders = [str(path.relative_to(APP)) for path in APP.rglob('*.py')
                 if 'ST_SimplifyPreserveTopology' in path.read_text()
                 and not any(part in str(path.relative_to(APP)) for part in EXEMPT)]
    assert offenders == []
