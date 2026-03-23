from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.db_fqtn import acs_table, cms_table, hrsa_table, places_table, svi_table
from app.db_schemas import SCHEMA_BY_SOURCE


def _probe_table(
    db: Session,
    *,
    source: str,
    fq_table_name: str,
) -> bool:
    exists = db.execute(
        text("SELECT to_regclass(:table_name) AS exists"),
        {"table_name": fq_table_name},
    ).mappings().one()["exists"]

    if exists is None:
        print(f"[WARN] {source}: missing table {fq_table_name}")
        return False

    db.execute(text(f"SELECT 1 FROM {fq_table_name} LIMIT 1")).scalar_one_or_none()
    print(f"[OK] {source}: {fq_table_name}")
    return True


def main() -> int:
    print("Resolved schema mapping:")
    for source, schema in SCHEMA_BY_SOURCE.items():
        print(f"  {source}: {schema}")

    default_mapping = {
        "places": "public",
        "acs": "public",
        "svi": "public",
        "hrsa": "public",
        "cms": "cms",
        "usda_food_access": "usda_food_access",
        "usda_food_environment": "usda_food_env",
        "usda_food_env": "usda_food_env",
        "usda": "usda_food_access",
        "fema": "fema_nri",
        "fema_nri": "fema_nri",
        "fema_national_risk_index": "fema_nri",
        "cdc": "cdc_funding",
        "cdc_funding": "cdc_funding",
        "usaspending": "usaspending",
        "cdc_profiles": "cdc_profiles",
        "taggs": "taggs",
        "recon": "recon",
        "analytics": "analytics",
    }
    if SCHEMA_BY_SOURCE == default_mapping:
        print("Defaults active: behavior should match existing schema layout.")
    else:
        print("Custom schema override(s) active via environment variables.")

    try:
        with SessionLocal() as db:
            _probe_table(
                db,
                source="places",
                fq_table_name=places_table("dim_county"),
            )
            _probe_table(
                db,
                source="acs",
                fq_table_name=acs_table("acs_nmf_county_estimates"),
            )
            _probe_table(
                db,
                source="svi",
                fq_table_name=svi_table("svi_measures"),
            )
            _probe_table(
                db,
                source="hrsa",
                fq_table_name=hrsa_table("county_hpsa_summary"),
            )

            cms_candidates = (
                "geo_dim",
                "gv_measure_dim",
                "gv_fact",
                "ssp_measure_dim",
                "ssp_fact",
            )
            cms_checked = False
            for table_name in cms_candidates:
                if _probe_table(
                    db,
                    source="cms",
                    fq_table_name=cms_table(table_name),
                ):
                    cms_checked = True
                    break
            if not cms_checked:
                print("[WARN] cms: no CMS tables found (optional check).")
    except SQLAlchemyError as exc:
        print(f"[ERROR] Database verification failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
