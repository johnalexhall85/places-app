from __future__ import annotations

import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROFILES_CACHE_DIR = PROJECT_ROOT / "backend" / "app" / "data" / "profiles"

# Additional report cache roots requested for safe cleanup.
OPTIONAL_CACHE_DIRS = [
    PROJECT_ROOT / "backend" / "data" / "reports",
    PROJECT_ROOT / "backend" / "cache",
    PROJECT_ROOT / "backend" / "tmp",
    PROJECT_ROOT / "frontend" / "public" / "reports",
]


def _iter_cache_dirs() -> list[Path]:
    return [PROFILES_CACHE_DIR, *OPTIONAL_CACHE_DIRS]


def _remove_empty_dirs(root: Path, *, dry_run: bool = False) -> int:
    removed = 0
    for directory in sorted(root.rglob("*"), reverse=True):
        if not directory.is_dir():
            continue
        if any(directory.iterdir()):
            continue
        if dry_run:
            removed += 1
            continue
        directory.rmdir()
        removed += 1
    return removed


def clear_report_cache(
    *,
    include_charts: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, int]:
    removed_files = 0
    removed_dirs = 0

    for cache_root in _iter_cache_dirs():
        if not cache_root.exists():
            continue
        if not cache_root.is_dir():
            continue

        for file_path in cache_root.rglob("*"):
            if not file_path.is_file():
                continue

            is_pdf = file_path.suffix.lower() == ".pdf"
            is_profile_chart = (
                include_charts
                and cache_root == PROFILES_CACHE_DIR
                and file_path.parent.name == "charts"
                and file_path.suffix.lower() == ".png"
            )
            is_chart_marker = (
                include_charts
                and cache_root == PROFILES_CACHE_DIR
                and file_path.name == ".chart_style_version"
            )
            if not (is_pdf or is_profile_chart or is_chart_marker):
                continue

            if verbose:
                print(f"remove: {file_path}")
            if dry_run:
                removed_files += 1
                continue
            file_path.unlink(missing_ok=True)
            removed_files += 1

        removed_dirs += _remove_empty_dirs(cache_root, dry_run=dry_run)

    return {"removed_files": removed_files, "removed_dirs": removed_dirs}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Delete generated report cache files (PDFs by default) and optionally chart images."
        )
    )
    parser.add_argument(
        "--include-charts",
        action="store_true",
        help="Also remove cached chart PNG files under backend/app/data/profiles/*/charts.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without deleting files.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each file that is removed.",
    )
    args = parser.parse_args()

    summary = clear_report_cache(
        include_charts=args.include_charts,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    mode = "dry-run" if args.dry_run else "deleted"
    print(
        f"{mode}: {summary['removed_files']} files, "
        f"{summary['removed_dirs']} empty directories"
    )


if __name__ == "__main__":
    main()

