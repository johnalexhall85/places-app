from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# import your routers (adjust these imports to match your project)
from app.routers import county_boundaries, geojson, legend, measures, tiles

app = FastAPI()

# CORS must be added to the SAME `app` uvicorn runs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers AFTER middleware is added
app.include_router(measures.router)
app.include_router(legend.router)
app.include_router(tiles.router)
app.include_router(county_boundaries.router)
app.include_router(geojson.router)
