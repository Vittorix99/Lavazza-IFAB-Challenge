"""
AgentState — stato condiviso tra tutti i nodi del grafo LangGraph.

Ogni nodo riceve l'intero stato e ritorna solo i campi che ha modificato.
LangGraph fa il merge automaticamente.

REDUCER: i campi scritti da più agenti in parallelo usano Annotated per
         definire come fondere i valori concorrenti:
         - list[dict] con operator.add  → concatenazione (append)
         - dict       con _merge_dicts  → {**a, **b} (union)

Campi per area di responsabilità:
- Input:       country, report_type, run_at, delivery_targets
- Sub-agenti:  signals, summaries, docs_for_charts, data_freshness
- Aggregation: (calcola final_score e alerts da signals)
- Chart node:  charts
- RAG node:    rag_context
- Report node: report_json
"""

import operator
from typing import Annotated, TypedDict


def _merge_dicts(a: dict, b: dict) -> dict:
    """Reducer per dict: unione semplice, b sovrascrive a in caso di conflitto."""
    return {**a, **b}


class AgentState(TypedDict):
    # --- Input (impostati al trigger) ------------------------------------
    country: str          # "BR"
    report_type: str      # "daily" | "weekly" | "monthly"
    run_at: str           # ISO 8601 — timestamp di avvio del grafo
    delivery_targets: list[str]  # ["acquisti", "quality", "management"]
    demo_mode: bool       # True = tutti i dati considerati freschi (per prototipo/demo)

    # --- Prodotti dai 4 sub-agenti (reducer per merge parallelo) --------
    signals: Annotated[list[dict], operator.add]
    # Forma di ogni segnale:
    # {
    #   "source":      "NOAA_ENSO",
    #   "area":        "environment",   # geo | environment | crops | prices
    #   "fact":        "ONI index -1.2, fase La Niña",
    #   "direction":   "negative",      # positive | negative | neutral
    #   "intensity":   "high",          # low | medium | high
    #   "explanation": "La Niña riduce le precipitazioni...",
    #   "_score":      65.0             # campo interno opzionale per aggregation_node
    # }

    summaries: Annotated[dict, _merge_dicts]
    # {"geo": str, "environment": str, "crops": str, "prices": str}

    docs_for_charts: Annotated[list[dict], operator.add]
    # Ogni elemento è il doc_for_charts prodotto da split_doc():
    # {"source": "COMEX_STAT", "country": "BR", "collected_at": "...", "series": [...], ...}

    data_freshness: Annotated[dict, _merge_dicts]
    # {
    #   "COMEX_STAT": {"days_old": 22, "is_fresh": False, "cadenza": "monthly"},
    #   "BCB_PTAX":   {"days_old": 0,  "is_fresh": True,  "cadenza": "daily"},
    # }

    # --- Prodotto dall'aggregation_node ---------------------------------
    final_score: float    # 0-100 pesato geo×0.25 + env×0.30 + crops×0.30 + prices×0.15
    alerts: list[str]     # segnali critici (intensity=high, direction=negative)

    # --- Prodotto dal chart_node ----------------------------------------
    charts: list[dict]
    # Ogni elemento:
    # {
    #   "chart_id":          "comex_export_volume",
    #   "title":             "Export volume arabica 6 mesi",
    #   "active":            True,
    #   "interpretive_text": "Le esportazioni sono calate del 12% MoM..."
    # }

    # --- Prodotto dal rag_node ------------------------------------------
    rag_context: str      # testo concatenato dai chunk Qdrant più rilevanti

    # --- Prodotto dal report_node ---------------------------------------
    report_json: dict     # JSON strutturato del report finale
