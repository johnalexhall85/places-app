from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db_fqtn import cms_table  # noqa: E402
from app.db_schemas import CMS_SCHEMA  # noqa: E402

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"


def main() -> int:
    db_url = os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    required_tables = (
        "geo_dim",
        "gv_measure_dim",
        "gv_fact",
        "ssp_measure_dim",
        "ssp_fact",
    )

    print(f"Verifying CMS tables in schema: {CMS_SCHEMA}")
    try:
        engine = create_engine(db_url, future=True)
        with engine.connect() as connection:
            for table_name in required_tables:
                fq_name = cms_table(table_name)
                exists = connection.execute(
                    text("SELECT to_regclass(:name) IS NOT NULL AS exists"),
                    {"name": fq_name},
                ).mappings().one()["exists"]
                if exists:
                    print(f"[OK] {fq_name}")
                else:
                    print(f"[MISSING] {fq_name}")
    except SQLAlchemyError as exc:
        print(
            "Could not connect to the database to verify CMS tables. "
            f"Details: {exc}"
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
