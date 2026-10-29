"""CLI for manage.ps1 (JSON output, read-only)."""

from __future__ import annotations

import argparse
import json
import sys

from app.db.session import get_sessionmaker
from app.runtime.diagnostics import collect_status, doctor_checks
from app.runtime.redaction import redact_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.runtime.cli")
    parser.add_argument("command", choices=["status", "doctor"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "status":
        session = get_sessionmaker()()
        try:
            payload = collect_status(session)
        finally:
            session.close()
    else:
        payload = doctor_checks()

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(redact_text(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
