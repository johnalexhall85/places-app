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


@app.get("/debug/schema")
def debug_schema(db: Session = Depends(get_db)):
    boundary_candidates = db.execute(
        text(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
                AND (table_name ILIKE '%state%' OR table_name ILIKE '%county%')
            ORDER BY table_name
            """
        )
    ).mappings().all()

    estimate_candidates = db.execute(
        text(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
                AND (
                    table_name ILIKE '%estimate%'
                    OR table_name ILIKE '%measure%'
                    OR table_name ILIKE '%places%'
                )
            ORDER BY table_name
            """
        )
    ).mappings().all()

    geometry_columns = db.execute(
        text(
            """
            SELECT f_table_schema AS table_schema,
                   f_table_name AS table_name,
                   f_geometry_column AS column_name,
                   type AS udt_name,
                   srid
            FROM geometry_columns
            ORDER BY f_table_name, f_geometry_column
            """
        )
    ).mappings().all()

    configured_tables = [
        "states",
        "dim_county_boundary",
        "dim_measure",
        "fact_estimate_county",
        "fact_estimate_state",
    ]
    configured_columns = {}
    for table_name in configured_tables:
        columns = db.execute(
            text(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table_name
                ORDER BY ordinal_position
                """
            ),
            {"table_name": table_name},
        ).mappings().all()
        configured_columns[table_name] = columns

    return {
        "boundary_candidates": boundary_candidates,
        "estimate_candidates": estimate_candidates,
        "geometry_columns": geometry_columns,
        "configured_columns": configured_columns,
    }


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
