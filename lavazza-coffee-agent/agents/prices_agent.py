"""
prices_agent — sub-agente LLM (Claude Haiku) per il rischio prezzi.

SCHEMA-AGNOSTICO: nessun campo MongoDB hardcodato.
Claude Haiku legge i documenti (World Bank, BCB, ECB, qualsiasi altra fonte prezzi)
e decide autonomamente cosa è rilevante per il costo di approvvigionamento caffè.

Aggiungere una nuova fonte prezzi = aggiungere il connettore n8n.
Questo file non va modificato.

Fonti attuali (raw_prices): WB_PINK_SHEET, BCB_PTAX, ECB_DATA_PORTAL
"""

from datetime import datetime, timezone

from agents.state import AgentState
from source_configs.sources import get_freshness_threshold_days, get_source_cadence
from utils.db import get_recent_docs
from utils.llm_analyzer import analyze_with_haiku
from utils.split_doc import split_doc


import re as _re


def _compute_freshness(doc: dict, demo_mode: bool) -> dict:
    cadence = str(doc.get("cadenza", "")).strip().lower()
    if not cadence or cadence == "unknown":
        cadence = get_source_cadence(str(doc.get("source", "")))

    threshold = get_freshness_threshold_days(cadence)

    try:
        raw_ts = str(doc.get("collected_at", "")).strip()
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


def prices_agent(state: AgentState) -> dict:
    """
    Nodo LangGraph: analisi rischio prezzi Brasile via Claude Haiku.

    Legge tutti i documenti in raw_prices (macroarea=prices)
    e delega a Haiku l'interpretazione. Nessun campo hardcodato.

    Output (aggiornamento parziale state):
      signals         → segnali estratti da Haiku + segnale sintetico _score
      summaries       → chiave "prices"
      docs_for_charts → dati chart-ready (split_doc)
      data_freshness  → freschezza per ogni fonte trovata
    """
    demo_mode: bool = state.get("demo_mode", True)
    country: str = state.get("country", "BR")

    # --- Carica documenti (schema-agnostico: qualsiasi fonte in raw_prices) ---
    docs = get_recent_docs("raw_prices", "prices", country=country, limit=10)

    if not docs:
        score_prices = 0.0
        return {
            "signals": [{
                "source": "PRICES_AGENT",
                "area": "prices",
                "fact": "Score prezzi: 0/100 — nessun dato disponibile",
                "direction": "neutral",
                "intensity": "low",
                "explanation": "Nessun documento trovato in raw_prices su MongoDB.",
                "_score": score_prices,
            }],
            "summaries": {"prices": "Dati prezzi non disponibili in MongoDB."},
            "docs_for_charts": [],
            "data_freshness": {},
        }

    # --- split_doc --------------------------------------------------------
    docs_for_llm: list[dict] = []
    new_docs_for_charts: list[dict] = []
    freshness_updates: dict = {}

    for doc in docs:
        llm_part, chart_part = split_doc(doc)
        docs_for_llm.append(llm_part)
        new_docs_for_charts.append(chart_part)
        source = doc.get("source", "unknown")
        freshness_updates[source] = _compute_freshness(doc, demo_mode)

    # --- Chiama Haiku (schema-agnostico) ----------------------------------
    result = analyze_with_haiku(docs_for_llm, "prices", country)

    if result is None:
        score_prices = 50.0
        new_signals = [{
            "source": "PRICES_AGENT",
            "area": "prices",
            "fact": f"Score prezzi: {score_prices:.0f}/100 (fallback — LLM non disponibile)",
            "direction": "neutral",
            "intensity": "medium",
            "explanation": "Analisi LLM Haiku non riuscita.",
            "_score": score_prices,
        }]
        summary = "Analisi prezzi non disponibile per errore LLM."
    else:
        new_signals = result.get("signals", [])
        for sig in new_signals:
            sig["area"] = "prices"

        score_prices = float(result.get("score", 50.0))
        score_prices = max(0.0, min(100.0, score_prices))
        summary = result.get("summary", "Analisi prezzi completata.")

        new_signals.append({
            "source": "PRICES_AGENT",
            "area": "prices",
            "fact": f"Score prezzi: {score_prices:.0f}/100",
            "direction": "negative" if score_prices > 50 else "neutral",
            "intensity": "high" if score_prices > 70 else "medium" if score_prices > 40 else "low",
            "explanation": (
                f"Haiku ha analizzato {len(docs)} documenti da "
                f"{', '.join(freshness_updates.keys())}."
            ),
            "_score": score_prices,
        })

    return {
        "signals": new_signals,
        "summaries": {"prices": summary},
        "docs_for_charts": new_docs_for_charts,
        "data_freshness": freshness_updates,
    }
