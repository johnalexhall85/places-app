import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ingest.places_county_pipeline import (  # noqa: E402
    MAX_CHUNK_SIZE,
    print_preflight_text,
    run_county_ingestion,
    run_preflight,
)


DEFAULT_CSV = (
    "./data/PLACES__Local_Data_for_Better_Health,_County_Data_2024_release_20260219.csv"
)
DEFAULT_DICT = "./data/PLACES_and_500_Cities__Data_Dictionary_20260215.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight validator for PLACES county CSV. "
            "Default mode is read-only (no DB writes)."
        )
    )
    parser.add_argument("--csv", default=DEFAULT_CSV, help="Path to county CSV.")
    parser.add_argument("--dict", default=DEFAULT_DICT, help="Path to data dictionary CSV.")
    parser.add_argument(
        "--year",
        type=int,
        default=2024,
        help="Expected year for validation checks (default: 2024).",
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=10,
        help="Number of normalized sample rows to print.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="If provided, run ingestion writes after a successful preflight.",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format for preflight summary.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    csv_path = Path(args.csv).expanduser().resolve()
    dict_path = Path(args.dict).expanduser().resolve()

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    if args.sample_rows <= 0:
        raise ValueError("--sample-rows must be >= 1")

    preflight_banner = (
        f"Running county preflight (read-only={not args.write}) "
        f"with chunksize={MAX_CHUNK_SIZE}"
    )
    if args.output == "json":
        print(preflight_banner, file=sys.stderr)
    else:
        print(preflight_banner)
    summary = run_preflight(
        csv_path=csv_path,
        dict_path=dict_path,
        expected_year=args.year,
        sample_rows=args.sample_rows,
    )

    if args.output == "json":
        json_safe = dict(summary)
        # Mapping has non-JSON-friendly internals; remove noisy internals from JSON output.
        mapping = json_safe.get("mapping", {})
        if mapping:
            mapping = dict(mapping)
            if "duplicate_normalized" in mapping:
                mapping["duplicate_normalized"] = {
                    k: list(v) for k, v in mapping["duplicate_normalized"].items()
                }
            json_safe["mapping"] = mapping
        print(json.dumps(json_safe, indent=2, default=str))
    else:
        print_preflight_text(summary)

    if summary.get("status") == "error":
        raise SystemExit(2)

    if not args.write:
        return

    print("\nPreflight passed. Starting write mode ingestion using the same mapping...")
    ingestion_summary = run_county_ingestion(
        csv_path=csv_path,
        encoding=summary["csv"]["encoding"],
        delimiter=summary["csv"]["delimiter"],
        db_to_csv=summary["mapping"]["db_to_csv"],
        chunksize=MAX_CHUNK_SIZE,
    )
    print("write_summary:")
    print(json.dumps(ingestion_summary, indent=2, default=str))


if __name__ == "__main__":
    main()
