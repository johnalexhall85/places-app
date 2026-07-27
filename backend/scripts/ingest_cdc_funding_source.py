from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.cdc_funding.source_ingest import main  # noqa: E402


if __name__ == "__main__":
    main()
