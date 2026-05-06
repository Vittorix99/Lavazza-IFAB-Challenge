#!/usr/bin/env python3
"""
Quick Qdrant Cloud diagnostic.

Usage:
    doppler run -- lavazza-coffee-agent/.venv/bin/python3 scripts/debug_qdrant.py --debug
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "lavazza-coffee-agent"
sys.path.insert(0, str(AGENT_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Qdrant Cloud connection")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose qdrant.py logs for this run",
    )
    parser.add_argument(
        "--collections",
        nargs="*",
        default=["geo_texts", "crops_texts", "reports_archive"],
        help="Collections to inspect",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(AGENT_DIR / ".env")

    if args.debug:
        os.environ["QDRANT_DEBUG"] = "1"

    from utils.qdrant import diagnose_connection

    diagnostics = diagnose_connection(args.collections)
    print(json.dumps(diagnostics, indent=2, ensure_ascii=False))
    return 0 if diagnostics.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
