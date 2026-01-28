from fastapi import APIRouter, Response

router = APIRouter(tags=["tiles"])


@router.get("/tiles/counties/{z}/{x}/{y}.mvt")
def get_county_tiles(z: int, x: int, y: int) -> Response:
    return Response(content=b"", media_type="application/vnd.mapbox-vector-tile")
