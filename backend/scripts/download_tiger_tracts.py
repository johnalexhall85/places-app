import argparse
from pathlib import Path


TIGER_YEAR = 2020
BASE_URL = f"https://www2.census.gov/geo/tiger/TIGER{TIGER_YEAR}/TRACT"
DEFAULT_STATE_FIPS = [
    "01",
    "02",
    "04",
    "05",
    "06",
    "08",
    "09",
    "10",
    "11",
    "12",
    "13",
    "15",
    "16",
    "17",
    "18",
    "19",
    "20",
    "21",
    "22",
    "23",
    "24",
    "25",
    "26",
    "27",
    "28",
    "29",
    "30",
    "31",
    "32",
    "33",
    "34",
    "35",
    "36",
    "37",
    "38",
    "39",
    "40",
    "41",
    "42",
    "44",
    "45",
    "46",
    "47",
    "48",
    "49",
    "50",
    "51",
    "53",
    "54",
    "55",
    "56",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download TIGER/Line 2020 tract shapefiles."
    )
    parser.add_argument(
        "--state",
        action="append",
        dest="states",
        default=[],
        help="2-digit state FIPS. Repeat for multiple states.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory for TIGER ZIP files (default: data/shapes/tracts).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing ZIP files if present.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="HTTP timeout in seconds.",
    )
    return parser.parse_args()


def normalize_state_fips(value: str) -> str:
    normalized = value.strip()
    if len(normalized) == 1:
        normalized = f"0{normalized}"
    if len(normalized) != 2 or not normalized.isdigit():
        raise ValueError(f"Invalid state FIPS: {value}")
    return normalized


def resolve_output_dir(path_arg: str | None) -> Path:
    if path_arg:
        out_dir = Path(path_arg).expanduser().resolve()
    else:
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent.parent
        out_dir = project_root / "data" / "shapes" / "tracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def download_file(url: str, target_path: Path, timeout: int) -> None:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError(
            "requests is required. Install backend dependencies first."
        ) from exc

    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with target_path.open("wb") as output_file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output_file.write(chunk)


def main() -> None:
    args = parse_args()
    states = (
        [normalize_state_fips(state) for state in args.states]
        if args.states
        else DEFAULT_STATE_FIPS
    )
    out_dir = resolve_output_dir(args.out_dir)

    print(f"Downloading TIGER tract ZIPs to: {out_dir}")
    print(f"States: {', '.join(states)}")

    for statefp in states:
        filename = f"tl_{TIGER_YEAR}_{statefp}_tract.zip"
        url = f"{BASE_URL}/{filename}"
        target = out_dir / filename

        if target.exists() and not args.overwrite:
            print(f"Skipping existing file: {target.name}")
            continue

        print(f"Downloading {target.name} ...")
        download_file(url=url, target_path=target, timeout=args.timeout)
        print(f"Saved: {target}")

    print("Done.")


if __name__ == "__main__":
    main()
