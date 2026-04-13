"""
environment_agent — sub-agente LLM (Claude Haiku) per il rischio ambientale.

SCHEMA-AGNOSTICO: nessun campo MongoDB hardcodato.
Claude Haiku legge i documenti (qualsiasi fonte, qualsiasi schema) e decide
autonomamente cosa è rilevante per il rischio ambientale del caffè brasiliano.

Aggiungere una nuova fonte ambientale = aggiungere il connettore n8n.
Questo file non va modificato.

Fonti attuali (raw_environment): NOAA_ENSO, NASA_FIRMS
"""

from datetime import datetime, timezone

from agents.state import AgentState
from utils.db import get_recent_docs, get_db
from utils.llm_analyzer import analyze_with_haiku
from utils.split_doc import split_doc
from utils.geo_utils import tag_fires_with_coffee_zones


import re as _re

# Fallback cadenze per fonti che non memorizzano 'cadenza' nel documento raw
_SOURCE_CADENCE = {
    "NOAA_ENSO": "monthly",
    "NASA_FIRMS": "hourly",
}


def _compute_freshness(doc: dict, demo_mode: bool) -> dict:
    """
    Calcola freschezza usando il campo 'cadenza' del documento stesso,
    con fallback sulla mappa _SOURCE_CADENCE per fonti che non lo memorizzano.
    """
    cadence = str(doc.get("cadenza", "")).strip().lower()
    if not cadence or cadence == "unknown":
        source = str(doc.get("source", "")).upper()
        cadence = _SOURCE_CADENCE.get(source, "unknown")

    thresholds = {
        "hourly": 1,
        "daily": 2,
        "weekly": 10,
        "monthly": 35,
        "unknown": 30,
    }
    threshold = thresholds.get(cadence, 30)

    try:
        raw_ts = str(doc.get("collected_at", "")).strip()
        # Rimuove la parte millisecondo (es. .000) per compatibilità Python < 3.11
        raw_ts = _re.sub(r"\.\d+", "", raw_ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw_ts)
        days_old = (datetime.now(timezone.utc) - dt).days
    except Exception:
        days_old = None

    return {
        "days_old": days_old,
        "is_fresh": demo_mode or (days_old is not None and days_old <= threshold),
        "cadenza": cadence,
    }


def environment_agent(state: AgentState) -> dict:
    """
    Nodo LangGraph: analisi rischio ambientale Brasile via Claude Haiku.

    Legge tutti i documenti in raw_environment (macroarea=environment)
    e delega a Haiku l'interpretazione — nessun campo è hardcodato.

    Output (aggiornamento parziale state):
      signals         → segnali estratti da Haiku + segnale sintetico _score
      summaries       → chiave "environment"
      docs_for_charts → dati chart-ready (split_doc)
      data_freshness  → freschezza per ogni fonte trovata
    """
    demo_mode: bool = state.get("demo_mode", True)
    country: str = state.get("country", "BR")

    # --- Carica documenti (schema-agnostico: limit=10, qualsiasi fonte) ---
    docs = get_recent_docs("raw_environment", "environment", country=country, limit=10)

    if not docs:
        score_env = 0.0
        return {
            "signals": [{
                "source": "ENVIRONMENT_AGENT",
                "area": "environment",
                "fact": "Score ambiente: 0/100 — nessun dato disponibile",
                "direction": "neutral",
                "intensity": "low",
                "explanation": "Nessun documento trovato in raw_environment su MongoDB.",
                "_score": score_env,
            }],
            "summaries": {"environment": "Dati ambientali non disponibili in MongoDB."},
            "docs_for_charts": [],
            "data_freshness": {},
        }

    # --- split_doc: separa dati LLM da dati chart -------------------------
    docs_for_llm: list[dict] = []
    new_docs_for_charts: list[dict] = []
    freshness_updates: dict = {}

    db = get_db()
    for doc in docs:
        # Arricchisci fuochi NASA FIRMS con tagging zone caffè (L2 comuni)
        if doc.get("source") == "NASA_FIRMS":
            doc = tag_fires_with_coffee_zones(doc, db)

        llm_part, chart_part = split_doc(doc)
        docs_for_llm.append(llm_part)
        new_docs_for_charts.append(chart_part)
        source = doc.get("source", "unknown")
        freshness_updates[source] = _compute_freshness(doc, demo_mode)

    # --- Chiama Haiku (schema-agnostico) ----------------------------------
    result = analyze_with_haiku(docs_for_llm, "environment", country)

    if result is None:
        score_env = 30.0
        new_signals = [{
            "source": "ENVIRONMENT_AGENT",
            "area": "environment",
            "fact": f"Score ambiente: {score_env:.0f}/100 (fallback — LLM non disponibile)",
            "direction": "neutral",
            "intensity": "medium",
            "explanation": "Analisi LLM Haiku non riuscita. Usare score di default.",
            "_score": score_env,
        }]
        summary = "Analisi ambientale non disponibile per errore LLM."
    else:
        new_signals = result.get("signals", [])
        for sig in new_signals:
            sig["area"] = "environment"

        score_env = float(result.get("score", 30.0))
        score_env = max(0.0, min(100.0, score_env))
        summary = result.get("summary", "Analisi ambiente completata.")

        # segnale sintetico per aggregation_node
        new_signals.append({
            "source": "ENVIRONMENT_AGENT",
            "area": "environment",
            "fact": f"Score ambiente: {score_env:.0f}/100",
            "direction": "negative" if score_env > 50 else "neutral",
            "intensity": "high" if score_env > 70 else "medium" if score_env > 40 else "low",
            "explanation": (
                f"Haiku ha analizzato {len(docs)} documenti da "
                f"{', '.join(freshness_updates.keys())}."
            ),
            "_score": score_env,
        })

    return {
        "signals": new_signals,
        "summaries": {"environment": summary},
        "docs_for_charts": new_docs_for_charts,
        "data_freshness": freshness_updates,
    }
