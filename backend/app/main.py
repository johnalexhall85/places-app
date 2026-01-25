from fastapi import FastAPI

from app.routers.health import router as health_router
from app.routers.counties import router as counties_router
from app.routers.measures import router as measures_router
from app.routers.estimates import router as estimates_router
from app.routers.geojson import router as geojson_router
from app.routers.legend import router as legend_router

app = FastAPI(title="PLACES (independent) API", version="0.1.0")

app.include_router(health_router)
app.include_router(counties_router)
app.include_router(measures_router)
app.include_router(estimates_router)
app.include_router(geojson_router)
app.include_router(legend_router)
