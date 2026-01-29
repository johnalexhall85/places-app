from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

# import your routers (adjust these imports to match your project)
from app.db import get_db
from app.routers import county_boundaries, geojson, legend, measures, state_geojson, tiles

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


@app.get("/debug/cors")
def debug_cors():
    return {"ok": True}


@app.get("/debug/db/states_table")
def debug_states_table(db: Session = Depends(get_db)):
    query = text(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'states'
        ORDER BY ordinal_position
        """
    )
    rows = db.execute(query).mappings().all()
    return {"columns": rows}

# Include routers AFTER middleware is added
app.include_router(measures.router)
app.include_router(legend.router)
app.include_router(tiles.router)
app.include_router(county_boundaries.router)
app.include_router(geojson.router)
app.include_router(state_geojson.router)
