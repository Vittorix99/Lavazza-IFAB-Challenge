#!/usr/bin/env python3
"""
Crea/aggiorna il catalogo dinamico delle source per il chatbot.

Il catalogo viene salvato in MongoDB nella collection `source_catalog` e contiene:
- source, area, raw_collection
- conteggi e ultimo collected_at
- campi osservati nei documenti recenti
- descrizione testuale
- embedding della descrizione per routing semantico

Uso:
    doppler run -- lavazza-coffee-agent/.venv/bin/python3 scripts/build_source_catalog.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "lavazza-coffee-agent"
sys.path.insert(0, str(AGENT_DIR))


def _load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(AGENT_DIR / ".env")


def _json_safe(value: Any, max_chars: int = 300) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = str(value)
    text = " ".join(text.split())
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text


def _field_summary(docs: list[dict], max_fields: int = 40) -> list[dict]:
    technical = {"_id", "_chart_fields", "country", "macroarea"}
    seen: dict[str, dict] = {}
    for doc in docs:
        for key, value in doc.items():
            if key in technical or key in seen:
                continue
            if value is None:
                continue
            seen[key] = {
                "name": key,
                "type": type(value).__name__,
                "sample": _json_safe(value),
            }
            if len(seen) >= max_fields:
                break
    return list(seen.values())


def _signals_excerpt(doc: dict) -> str:
    chunks = []
    for key in ["summary_en", "summary", "movement_label", "topic", "headline", "release_title"]:
        if value := doc.get(key):
            chunks.append(f"{key}: {_json_safe(value, max_chars=500)}")

    signals = doc.get("signals")
    if isinstance(signals, list) and signals:
        chunks.append("signals: " + _json_safe(signals[:5], max_chars=900))

    return "\n".join(chunks)


def _build_description(
    *,
    source: str,
    title: str,
    area: str,
    raw_collection: str,
    cadence: str,
    doc_count: int,
    latest_doc: dict,
    fields: list[dict],
) -> str:
    field_text = ", ".join(f"{item['name']} ({item['type']})" for item in fields)
    latest_at = latest_doc.get("collected_at", "unknown")
    signal_text = _signals_excerpt(latest_doc)
    return f"""\
Source: {source}
Title: {title}
Area: {area}
Mongo collection: {raw_collection}
Cadence: {cadence}
Documents available: {doc_count}
Latest collected_at: {latest_at}
Observed fields: {field_text}

Recent content summary:
{signal_text}
""".strip()


def _embed_texts(texts: list[str], model: str) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def build_catalog(country: str, dry_run: bool = False, no_embeddings: bool = False) -> dict:
    _load_env()

    from source_configs.sources import (
        get_all_raw_collections,
        get_area_for_raw_collection,
        get_source_area,
        get_source_cadence,
        get_source_title,
        normalize_area,
    )
    from utils.chat_router_config import SOURCE_CATALOG_EMBEDDING_MODEL
    from utils.db import get_db

    db = get_db()
    model = SOURCE_CATALOG_EMBEDDING_MODEL
    now = datetime.now(timezone.utc).isoformat()

    candidates = []
    for raw_collection in get_all_raw_collections():
        col = db[raw_collection]
        try:
            sources = sorted(col.distinct("source", {"country": country}))
        except Exception:
            sources = []

        for source in sources:
            docs = list(
                col.find({"source": source, "country": country})
                .sort([("collected_at", -1)])
                .limit(3)
            )
            if not docs:
                continue

            latest_doc = docs[0]
            area = (
                normalize_area(latest_doc.get("macroarea", ""))
                or get_source_area(source)
                or get_area_for_raw_collection(raw_collection)
            )
            cadence = str(latest_doc.get("cadenza") or "").strip().lower() or get_source_cadence(source)
            title = get_source_title(source)
            doc_count = col.count_documents({"source": source, "country": country})
            fields = _field_summary(docs)
            description = _build_description(
                source=source,
                title=title,
                area=area,
                raw_collection=raw_collection,
                cadence=cadence,
                doc_count=doc_count,
                latest_doc=latest_doc,
                fields=fields,
            )

            candidates.append(
                {
                    "source": source,
                    "country": country,
                    "area": area,
                    "raw_collection": raw_collection,
                    "title": title,
                    "cadence": cadence,
                    "doc_count": doc_count,
                    "latest_collected_at": latest_doc.get("collected_at"),
                    "sample_fields": fields,
                    "description": description,
                    "active": True,
                    "updated_at": now,
                }
            )

    embeddings: list[list[float] | None]
    if no_embeddings:
        embeddings = [None] * len(candidates)
    else:
        descriptions = [item["description"] for item in candidates]
        embeddings = _embed_texts(descriptions, model=model) if descriptions else []

    for item, embedding in zip(candidates, embeddings):
        if embedding is not None:
            item["embedding"] = embedding
            item["embedding_model"] = model

    if not dry_run:
        existing_keys = set()
        for item in candidates:
            key = {
                "source": item["source"],
                "country": item["country"],
                "raw_collection": item["raw_collection"],
            }
            existing_keys.add((item["source"], item["country"], item["raw_collection"]))
            db["source_catalog"].update_one(key, {"$set": item}, upsert=True)

        for old in db["source_catalog"].find({"country": country}, {"source": 1, "country": 1, "raw_collection": 1}):
            old_key = (old.get("source"), old.get("country"), old.get("raw_collection"))
            if old_key not in existing_keys:
                db["source_catalog"].update_one({"_id": old["_id"]}, {"$set": {"active": False, "updated_at": now}})

        db["source_catalog"].create_index([("country", 1), ("active", 1)])
        db["source_catalog"].create_index([("source", 1), ("country", 1), ("raw_collection", 1)], unique=True)

    return {
        "country": country,
        "count": len(candidates),
        "embedding_model": None if no_embeddings else model,
        "dry_run": dry_run,
        "sources": [
            {
                "source": item["source"],
                "area": item["area"],
                "raw_collection": item["raw_collection"],
                "cadence": item["cadence"],
                "doc_count": item["doc_count"],
                "latest_collected_at": item["latest_collected_at"],
                "has_embedding": "embedding" in item,
            }
            for item in candidates
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build dynamic source catalog for semantic chat routing")
    parser.add_argument("--country", default="BR")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-embeddings", action="store_true")
    args = parser.parse_args()

    result = build_catalog(country=args.country, dry_run=args.dry_run, no_embeddings=args.no_embeddings)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
