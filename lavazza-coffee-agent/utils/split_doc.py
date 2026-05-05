"""
split_doc — separa i dati analitici dalle timeseries.

Ogni documento MongoDB dichiara in `_chart_fields` quali campi contengono
array grandi (timeseries, serie storiche). Questo permette agli agenti di
ricevere solo i dati testuali/aggregati, mentre il chart_node riceve solo
gli array da plottare.

Principio: schema-agnostico. Nessun campo è hardcodato qui.
"""

from bson import ObjectId


def _clean_for_llm(doc: dict) -> dict:
    """Rimuove campi interni MongoDB non utili al modello."""
    skip = {"_id", "_chart_fields"}
    return {k: v for k, v in doc.items() if k not in skip}


def split_doc(doc: dict) -> tuple[dict, dict]:
    """
    Divide un documento MongoDB in due parti:

    - doc_for_llm:    tutto tranne i chart_fields → va all'agente Haiku
    - doc_for_charts: solo i chart_fields → va al chart_node

    Returns:
        (doc_for_llm, doc_for_charts)
    """
    chart_fields = set(doc.get("_chart_fields", []))

    doc_for_llm = {
        k: v
        for k, v in doc.items()
        if k not in chart_fields and k not in {"_id", "_chart_fields"}
    }

    doc_for_charts = {
        "source": doc.get("source", "unknown"),
        "country": doc.get("country", "BR"),
        "collected_at": doc.get("collected_at"),
        **{k: v for k, v in doc.items() if k in chart_fields},
    }

    return doc_for_llm, doc_for_charts
