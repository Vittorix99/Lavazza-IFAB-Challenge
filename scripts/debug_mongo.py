#!/usr/bin/env python3
"""
Diagnostica MongoDB Atlas per agenti e dati n8n.

Esegue:
- ping ad Atlas
- conteggi per raw_* e ingestion_log
- ultime source per collection
- stessa lettura usata dagli agenti Python

Uso:
    doppler run -- lavazza-coffee-agent/.venv/bin/python3 scripts/debug_mongo.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "lavazza-coffee-agent"
sys.path.insert(0, str(AGENT_DIR))


RAW_COLLECTIONS = ["raw_geo", "raw_prices", "raw_crops", "raw_environment"]


def _load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(AGENT_DIR / ".env")


def _safe_mongo_uri(uri: str) -> str:
    try:
        parts = urlsplit(uri)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except Exception:
        return "<invalid-uri>"


def _days_old(value) -> int | None:
    if not value:
        return None
    try:
        raw = str(value).strip().replace("Z", "+00:00")
        if "." in raw:
            head, tail = raw.split(".", 1)
            suffix = ""
            if "+" in tail:
                suffix = "+" + tail.split("+", 1)[1]
            raw = head + suffix
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days
    except Exception:
        return None


def _latest_by_source(db, collection: str, country: str) -> list[dict]:
    rows = []
    try:
        sources = sorted(db[collection].distinct("source", {"country": country}))
    except Exception:
        sources = []

    for source in sources:
        doc = db[collection].find_one(
            {"source": source, "country": country},
            sort=[("collected_at", -1)],
            projection={"_id": 0, "source": 1, "country": 1, "macroarea": 1, "collected_at": 1, "cadenza": 1},
        )
        if doc:
            rows.append(
                {
                    "source": doc.get("source"),
                    "macroarea": doc.get("macroarea"),
                    "collected_at": doc.get("collected_at"),
                    "days_old": _days_old(doc.get("collected_at")),
                    "cadenza": doc.get("cadenza", "missing"),
                }
            )
    return rows


def diagnose(country: str = "BR") -> dict:
    _load_env()

    from source_configs.sources import get_crops_sources
    from utils.db import get_client, get_db, get_recent_docs

    uri = os.environ.get("MONGODB_URI", "")
    db_name = os.environ.get("MONGODB_DB", "lavazza_ifab")
    client = get_client()
    db = get_db()

    result: dict = {
        "ok": False,
        "uri": _safe_mongo_uri(uri),
        "is_atlas": uri.startswith("mongodb+srv://"),
        "db": db_name,
        "ping_ms": None,
        "collections": {},
        "agent_reads": {},
        "ingestion_log_latest": [],
        "error": None,
    }

    started = datetime.now(timezone.utc)
    try:
        client.admin.command("ping")
        result["ping_ms"] = round((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        result["ok"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    for collection in RAW_COLLECTIONS:
        col = db[collection]
        result["collections"][collection] = {
            "count": col.count_documents({}),
            "count_br": col.count_documents({"country": country}),
            "latest_by_source": _latest_by_source(db, collection, country),
        }

    result["agent_reads"] = {
        "geo_agent_raw_geo": len(get_recent_docs("raw_geo", "geo", country=country, limit=5)),
        "prices_agent_raw_prices": len(get_recent_docs("raw_prices", "prices", country=country, limit=10)),
        "environment_agent_raw_environment": len(
            get_recent_docs("raw_environment", "environment", country=country, limit=10)
        ),
        "crops_expected_sources": [source for source, _cadence in get_crops_sources()],
    }
    result["agent_reads"]["crops_found_sources"] = [
        source
        for source, _cadence in get_crops_sources()
        if db["raw_crops"].find_one({"source": source, "country": country})
    ]

    logs = list(
        db["ingestion_log"]
        .find(
            {"country": country},
            projection={"_id": 0, "source": 1, "status": 1, "completed_at": 1, "run_date": 1, "cadenza": 1},
        )
        .sort([("completed_at", -1), ("run_date", -1)])
        .limit(20)
    )
    result["ingestion_log_latest"] = logs

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnostica MongoDB Atlas")
    parser.add_argument("--country", default="BR")
    args = parser.parse_args()

    result = diagnose(country=args.country)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
