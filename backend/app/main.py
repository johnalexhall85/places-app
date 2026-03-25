from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.routers.health import router as health_router
from app.routers.counties import router as counties_router
from app.routers.measures import router as measures_router
from app.routers.estimates import router as estimates_router
from app.routers.geojson import router as geojson_router
from app.routers.legend import router as legend_router
from app.routers.county_boundaries import router as county_boundaries_router
from app.routers.state_geojson import router as state_geojson_router
from app.routers.tracts import router as tracts_router
from app.routers.meta import router as meta_router
from app.routers.history import router as history_router
from app.routers.search import router as search_router
from app.routers.assistant import router as assistant_router
from app.routers.acs_nmf import router as acs_nmf_router
from app.routers.profiles import router as profiles_router
from app.routers.profile_reports import router as profile_reports_router
from app.routers.svi import router as svi_router
from app.routers.hpsa import router as hpsa_router
from app.cms.router import router as cms_router
from app.fema_nri.router import router as fema_nri_router
from app.usda_food_access.router import router as usda_food_access_router
from app.usda_food_env.router import router as usda_food_env_router
from app.cdc_funding.router import router as cdc_funding_router
from app.taggs.router import router as taggs_router
from app.funding_models.router import router as funding_models_router

app = FastAPI(title="PLACES (independent) API", version="0.1.0")

app.add_middleware(
    GZipMiddleware,
    minimum_size=1000,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(counties_router)
app.include_router(measures_router)
app.include_router(estimates_router)
app.include_router(geojson_router)
app.include_router(legend_router)
app.include_router(county_boundaries_router)
app.include_router(state_geojson_router)
app.include_router(tracts_router)
app.include_router(meta_router)
app.include_router(history_router)
app.include_router(search_router)
app.include_router(assistant_router)
app.include_router(acs_nmf_router)
app.include_router(profiles_router)
app.include_router(profile_reports_router)
app.include_router(svi_router)
app.include_router(hpsa_router)
app.include_router(cms_router)
app.include_router(fema_nri_router)
app.include_router(usda_food_access_router)
app.include_router(usda_food_env_router)
app.include_router(cdc_funding_router)
app.include_router(taggs_router)
app.include_router(funding_models_router)
