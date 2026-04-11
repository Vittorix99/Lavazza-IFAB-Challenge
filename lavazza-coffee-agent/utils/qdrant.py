"""
Qdrant client — singleton pattern.

Usato da rag_node e dai sub-agenti geo/crops per ricerca semantica.
Gli embedding sono generati da OpenAI text-embedding-3-small (usato da n8n in ingestion).

Nota: qdrant-client >= 1.14 ha rimosso il metodo .search() in favore di .query_points().
Questo wrapper gestisce entrambe le versioni per compatibilità.
"""

import os
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from dotenv import load_dotenv

load_dotenv()

# --- Singleton -----------------------------------------------------------

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=os.environ.get("QDRANT_URL", "http://localhost:6333"))
    return _client


# --- Helpers -------------------------------------------------------------

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
        qdrant_filter = Filter(
            must=[
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filters.items()
            ]
        )

    client = get_client()

    # qdrant-client >= 1.14 usa query_points() invece di search()
    try:
        from qdrant_client.models import QueryRequest
        results = client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=limit,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        return [hit.payload for hit in results.points]
    except AttributeError:
        # fallback per versioni più vecchie
        results = client.search(  # type: ignore[attr-defined]
            collection_name=collection,
            query_vector=query_vector,
            limit=limit,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        return [hit.payload for hit in results]


def upsert(collection: str, point_id: str, vector: list[float], payload: dict) -> None:
    """Inserisce o aggiorna un punto in Qdrant."""
    from qdrant_client.models import PointStruct
    get_client().upsert(
        collection_name=collection,
        points=[PointStruct(id=point_id, vector=vector, payload=payload)],
    )


def collection_exists(collection: str) -> bool:
    """Controlla se una collection esiste (usato per skip graceful nel rag_node)."""
    try:
        get_client().get_collection(collection)
        return True
    except Exception:
        return False
