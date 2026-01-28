from fastapi import APIRouter, Request, Response

router = APIRouter(tags=["tiles"])


@router.api_route("/tiles/counties/{z}/{x}/{y}.mvt", methods=["GET", "HEAD"])
def get_county_tiles(z: int, x: int, y: int, request: Request) -> Response:
    mvt_bytes = b""
    response = Response(content=mvt_bytes, media_type="application/x-protobuf")
    if request.method == "HEAD":
        return Response(content=b"", status_code=response.status_code, headers=dict(response.headers))
    return response
