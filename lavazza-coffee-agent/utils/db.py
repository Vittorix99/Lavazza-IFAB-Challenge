"""
MongoDB client — singleton pattern.

Un'unica connessione condivisa tra tutti i nodi del grafo LangGraph.
"""

import os
from datetime import datetime, timezone
from pymongo import MongoClient
from pymongo.collection import Collection
from dotenv import load_dotenv

load_dotenv()

# --- Singleton -----------------------------------------------------------

_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27018"))
    return _client


def get_db():
    return get_client()[os.environ.get("MONGODB_DB", "lavazza_ifab")]


# --- Helpers lettura ------------------------------------------------------

def get_latest_doc(collection: str, source: str, country: str = "BR") -> dict | None:
    """Ritorna il documento più recente per una data source."""
    col: Collection = get_db()[collection]
    return col.find_one(
        {"source": source, "country": country},
        sort=[("collected_at", -1)],
    )


def get_recent_docs(
    collection: str,
    macroarea: str,
    country: str = "BR",
    limit: int = 10,
) -> list[dict]:
    """Ritorna gli ultimi N documenti per macroarea, ordinati dal più recente."""
    col: Collection = get_db()[collection]
    cursor = col.find(
        {"macroarea": macroarea, "country": country},
        sort=[("collected_at", -1)],
        limit=limit,
    )
    return list(cursor)


def get_docs_by_sources(collection: str, sources: list[str], country: str = "BR") -> list[dict]:
    """Ritorna il documento più recente per ciascuna source indicata."""
    return [
        doc
        for source in sources
        if (doc := get_latest_doc(collection, source, country)) is not None
    ]


# --- Helpers scrittura ----------------------------------------------------

def save_agent_run(run_doc: dict) -> str:
    """Salva un agent_run in MongoDB e ritorna l'_id come stringa."""
    col: Collection = get_db()["agent_runs"]
    result = col.insert_one(run_doc)
    return str(result.inserted_id)


def get_chart_series(
    collection: str,
    source: str,
    country: str = "BR",
) -> tuple[dict | None, list]:
    """
    Convenience wrapper per i chart builders.
    Ritorna (doc, series_list) dove series_list è estratta da _chart_fields.
    Ritorna (None, []) se il documento non viene trovato.
    """
    doc = get_latest_doc(collection, source, country)
    if doc is None:
        return None, []
    chart_fields = doc.get("_chart_fields", [])
    for field in chart_fields:
        val = doc.get(field)
        if isinstance(val, list) and val:
            return doc, val
    return doc, []


def get_chart_field_map(source: str, field_name: str) -> dict | None:
    """Controlla se Haiku ha già 'imparato' cosa significa un campo (cache)."""
    col: Collection = get_db()["chart_field_map"]
    return col.find_one({"source": source, "field_name": field_name})


def save_chart_field_map(source: str, field_name: str, mapping: dict) -> None:
    """Salva la mappatura campo→grafico scoperta da Haiku."""
    col: Collection = get_db()["chart_field_map"]
    col.update_one(
        {"source": source, "field_name": field_name},
        {"$set": {**mapping, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
