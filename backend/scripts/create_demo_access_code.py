#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import SessionLocal  # noqa: E402
from app.demo_access import service  # noqa: E402
from app.demo_access.settings import get_demo_access_settings  # noqa: E402


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a CHIP demo access code.")
    parser.add_argument("--label", required=True, help="Admin-facing label for this access code.")
    parser.add_argument("--recipient-name", default=None)
    parser.add_argument("--recipient-email", default=None)
    parser.add_argument("--organization", default=None)
    parser.add_argument("--notes", default=None)
    parser.add_argument("--created-by", default="script")
    parser.add_argument("--max-uses", type=int, default=None)
    parser.add_argument("--expires-at", default=None, help="ISO timestamp, for example 2026-05-01T00:00:00Z.")
    parser.add_argument("--code", default=None, help="Optional custom code. If omitted, a random code is generated.")
    parser.add_argument("--inactive", action="store_true", help="Create the code disabled.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_demo_access_settings()
    db = SessionLocal()
    try:
        code, plaintext = service.create_access_code(
            db,
            settings=settings,
            code_label=args.label,
            recipient_name=args.recipient_name,
            recipient_email=args.recipient_email,
            organization=args.organization,
            notes=args.notes,
            created_by=args.created_by,
            is_active=not args.inactive,
            max_uses=args.max_uses,
            expires_at=_parse_datetime(args.expires_at),
            plaintext_code=args.code,
        )
    finally:
        db.close()

    print("Created CHIP demo access code")
    print(f"id: {code.id}")
    print(f"label: {code.code_label}")
    print(f"recipient: {code.recipient_name or ''}")
    print(f"organization: {code.organization or ''}")
    print(f"plaintext_access_code: {plaintext}")
    print("Store the plaintext code now; only its hash is saved in the database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

