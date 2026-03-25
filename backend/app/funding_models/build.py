from __future__ import annotations

import argparse

from app.db import SessionLocal
from app.funding_models.schemas import FundingModelActionRequest
from app.funding_models.service import build_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a saved funding profile model version.")
    parser.add_argument("--model-id", required=True, help="Funding profile model id, slug, or internal_model_id")
    parser.add_argument("--version", type=int, default=None, help="Optional version number to build")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = build_model(
            db,
            args.model_id,
            FundingModelActionRequest(version_number=args.version),
        )
        build_run = result.get("build_run") or {}
        print(
            f"Built funding model {args.model_id} "
            f"(version={args.version or 'current'}) status={build_run.get('status')}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
