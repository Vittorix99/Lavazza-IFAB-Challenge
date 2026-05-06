"""
Qdrant client — singleton pattern.

Usato da rag_node e dai sub-agenti geo/crops per ricerca semantica.
Gli embedding sono generati da OpenAI text-embedding-3-small (usato da n8n in ingestion).

Nota: qdrant-client >= 1.14 ha rimosso il metodo .search() in favore di .query_points().
Questo wrapper gestisce entrambe le versioni per compatibilità.
"""

import os
import time
from urllib.parse import urlsplit, urlunsplit
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from dotenv import load_dotenv

load_dotenv()

# --- Singleton -----------------------------------------------------------

_client: QdrantClient | None = None
_payload_indexes_checked: set[tuple[str, str]] = set()


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _debug_enabled() -> bool:
    return _truthy(os.environ.get("QDRANT_DEBUG"))


def _mask_secret(value: str | None) -> str:
    if not value:
        return "missing"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _safe_url(url: str) -> str:
    """Redige credenziali/query string dall'URL prima di stamparlo."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path.rstrip("/"), "", ""))
    except Exception:
        return "<invalid-url>"


def _qdrant_config() -> dict:
    url = (os.environ.get("QDRANT_URL") or "").strip()
    if not url:
        raise RuntimeError("QDRANT_URL mancante: questo progetto usa solo Qdrant Cloud.")
    api_key = os.environ.get("QDRANT_API_KEY") or None
    if "cloud.qdrant.io" in url and not api_key:
        raise RuntimeError("QDRANT_API_KEY mancante: Qdrant Cloud richiede una API key.")
    return {
        "url": url,
        "safe_url": _safe_url(url),
        "api_key": api_key,
        "api_key_masked": _mask_secret(api_key),
        "is_cloud": "cloud.qdrant.io" in url,
    }


def _log(message: str) -> None:
    if _debug_enabled():
        print(f"[qdrant-debug] {message}")


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        cfg = _qdrant_config()
        _log(
            "init client "
            f"url={cfg['safe_url']} "
            f"cloud={cfg['is_cloud']} "
            f"api_key={cfg['api_key_masked']}"
        )
        _client = QdrantClient(
            url=cfg["url"],
            api_key=cfg["api_key"],
        )
    return _client


# --- Helpers -------------------------------------------------------------

def diagnose_connection(collections: list[str] | None = None) -> dict:
    """
    Diagnostica esplicita per capire se Qdrant Cloud e' raggiungibile.

    Non espone mai la API key completa: restituisce solo un valore mascherato.
    """
    cfg = _qdrant_config()
    target_collections = collections or ["geo_texts", "crops_texts", "reports_archive"]
    started = time.perf_counter()
    result = {
        "ok": False,
        "url": cfg["safe_url"],
        "is_cloud": cfg["is_cloud"],
        "api_key": cfg["api_key_masked"],
        "latency_ms": None,
        "collections_available": [],
        "collections_checked": [],
        "error": None,
    }

    try:
        client = get_client()
        response = client.get_collections()
        available = sorted(c.name for c in getattr(response, "collections", []))
        result["collections_available"] = available
        result["ok"] = True
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)

        for name in target_collections:
            try:
                info = client.get_collection(name)
                count = client.count(collection_name=name, exact=True).count
                result["collections_checked"].append(
                    {
                        "name": name,
                        "exists": True,
                        "status": str(getattr(info, "status", "")),
                        "points_count": getattr(info, "points_count", None),
                        "vectors_count": getattr(info, "vectors_count", None),
                        "indexed_vectors_count": getattr(info, "indexed_vectors_count", None),
                        "exact_count": count,
                    }
                )
            except Exception as exc:
                result["collections_checked"].append(
                    {
                        "name": name,
                        "exists": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        _log(
            "diagnose ok "
            f"latency_ms={result['latency_ms']} "
            f"collections={available}"
        )
    except Exception as exc:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
        result["error"] = f"{type(exc).__name__}: {exc}"
        _log(f"diagnose failed latency_ms={result['latency_ms']} error={result['error']}")

    return result


def ensure_payload_index(collection: str, field_name: str, schema: str = "keyword") -> None:
    """
    Crea l'indice payload necessario per usare filtri Qdrant Cloud.

    Qdrant Cloud puo' rifiutare query filtrate su campi non indicizzati con:
    "Index required but not found". Per il chatbot usiamo soprattutto source=...
    quindi creiamo un keyword index lazy, una sola volta per processo.
    """
    cache_key = (collection, field_name)
    if cache_key in _payload_indexes_checked:
        return

    from qdrant_client import models

    schema_type = models.PayloadSchemaType.KEYWORD if schema == "keyword" else schema
    started = time.perf_counter()
    try:
        client = get_client()
        info = client.get_collection(collection)
        payload_schema = getattr(info, "payload_schema", {}) or {}
        if field_name in payload_schema:
            _log(f"payload index exists collection={collection} field={field_name}")
            return

        client.create_payload_index(
            collection_name=collection,
            field_name=field_name,
            field_schema=schema_type,
        )
        _log(
            "payload index created "
            f"collection={collection} field={field_name} schema={schema} "
            f"latency_ms={round((time.perf_counter() - started) * 1000)}"
        )
    except Exception as exc:
        message = str(exc).lower()
        if "already exists" not in message and "already has" not in message:
            _log(
                "payload index create skipped/failed "
                f"collection={collection} field={field_name} "
                f"latency_ms={round((time.perf_counter() - started) * 1000)} "
                f"error={type(exc).__name__}: {exc}"
            )
            raise
        _log(f"payload index already exists collection={collection} field={field_name}")
    finally:
        _payload_indexes_checked.add(cache_key)


def search(
    collection: str,
    query_vector: list[float],
    limit: int = 5,
    filters: dict | None = None,
) -> list[dict]:
    """
    Ricerca semantica su una collection Qdrant.

    Args:
        collection:   nome della collection (geo_texts, crops_texts, reports_archive)
        query_vector: embedding della query (generato fuori da questa funzione)
        limit:        numero massimo di risultati
        filters:      dict {field: value} per filtrare per metadata

    Returns:
        Lista di payload dict dei punti trovati, ordinati per score.
    """
    qdrant_filter = None
    if filters:
        for key, value in filters.items():
            if isinstance(value, str):
                ensure_payload_index(collection, key, schema="keyword")
        qdrant_filter = Filter(
            must=[
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filters.items()
            ]
        )

    client = get_client()
    started = time.perf_counter()
    _log(
        "search start "
        f"collection={collection} limit={limit} "
        f"vector_size={len(query_vector)} filters={filters or {}}"
    )

    # qdrant-client >= 1.14 usa query_points() invece di search()
    try:
        results = client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=limit,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        payloads = [hit.payload for hit in results.points]
        _log(
            "search ok "
            f"collection={collection} hits={len(payloads)} "
            f"latency_ms={round((time.perf_counter() - started) * 1000)}"
        )
        return payloads
    except AttributeError:
        # fallback per versioni più vecchie
        results = client.search(  # type: ignore[attr-defined]
            collection_name=collection,
            query_vector=query_vector,
            limit=limit,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        payloads = [hit.payload for hit in results]
        _log(
            "search ok legacy "
            f"collection={collection} hits={len(payloads)} "
            f"latency_ms={round((time.perf_counter() - started) * 1000)}"
        )
        return payloads
    except Exception as exc:
        _log(
            "search failed "
            f"collection={collection} "
            f"latency_ms={round((time.perf_counter() - started) * 1000)} "
            f"error={type(exc).__name__}: {exc}"
        )
        raise


def upsert(collection: str, point_id: str, vector: list[float], payload: dict) -> None:
    """Inserisce o aggiorna un punto in Qdrant."""
    from qdrant_client.models import PointStruct
    started = time.perf_counter()
    _log(
        "upsert start "
        f"collection={collection} point_id={point_id} vector_size={len(vector)} "
        f"payload_keys={sorted(payload.keys())}"
    )
    get_client().upsert(
        collection_name=collection,
        points=[PointStruct(id=point_id, vector=vector, payload=payload)],
    )
    _log(
        "upsert ok "
        f"collection={collection} point_id={point_id} "
        f"latency_ms={round((time.perf_counter() - started) * 1000)}"
    )


def collection_exists(collection: str) -> bool:
    """Controlla se una collection esiste (usato per skip graceful nel rag_node)."""
    try:
        get_client().get_collection(collection)
        _log(f"collection_exists collection={collection} exists=true")
        return True
    except Exception as exc:
        _log(f"collection_exists collection={collection} exists=false error={type(exc).__name__}: {exc}")
        return False


def ensure_collection(collection: str, vector_size: int = 1536) -> None:
    """Crea la collection se non esiste. Dimensione default: 1536 (text-embedding-3-small)."""
    if not collection_exists(collection):
        from qdrant_client.models import Distance, VectorParams
        get_client().create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        print(f"[qdrant] Collection '{collection}' creata (size={vector_size})")
