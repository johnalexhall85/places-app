"""SQL for map shapes whose neighbours still fit together after simplification.

Simplifying each polygon on its own (ST_SimplifyPreserveTopology) moves a shared border differently
in each neighbour, which opens gaps and overlaps on the map. Snapping every vertex to one common grid
moves a shared vertex to the same place in both neighbours, so borders stay identical. The second
step removes only points that lie exactly on a straight line, which cannot move a border.

The tolerance is the grid size in degrees (roughly one screen pixel at the requested zoom).
Zero returns the stored geometry. A shape too small for the grid is returned unsimplified, never dropped.
"""
COLLINEAR_TOLERANCE = '1e-9'


def fitted_geom(geom: str, param: str = 'simplify') -> str:
    grid = f'CAST(:{param} AS double precision)'
    snapped = f'ST_SnapToGrid({geom}, {grid})'
    return (f'CASE WHEN {grid} <= 0 OR ST_IsEmpty({snapped}) THEN {geom} '
            f'ELSE ST_Simplify({snapped}, {COLLINEAR_TOLERANCE}, true) END')
