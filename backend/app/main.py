from fastapi import FastAPI

from app.routers.health import router as health_router
from app.routers.counties import router as counties_router

app = FastAPI(title="PLACES (independent) API", version="0.1.0")

app.include_router(health_router)
app.include_router(counties_router)
