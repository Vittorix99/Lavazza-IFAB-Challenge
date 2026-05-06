"""
crops_agent — sub-agente LLM (Claude Haiku) per l'analisi colture Brasile.

Fonti MongoDB (raw_crops):
  - USDA_FAS_PSD   : bilancio produzione/consumo/stock arabica (cadenza: settimanale)
  - IBGE_SIDRA     : produzione agricola brasiliana             (cadenza: settimanale)
  - COMEX_STAT     : export caffè Brasile per volume e valore   (cadenza: mensile)
  - CONAB_PDF      : report ufficiale previsioni raccolto CONAB  (cadenza: settimanale)
  - FAOSTAT        : dati storici produzione FAO                 (cadenza: mensile)

Flusso:
  1. Legge il documento più recente per ciascuna fonte da MongoDB
  2. Applica split_doc() → separa doc_for_llm (va a Haiku) da doc_for_charts (va al chart_node)
  3. Chiama Claude Haiku con un prompt strutturato che include tutti i doc_for_llm
  4. Haiku risponde con JSON: {signals: [...], summary: str, score: float}
  5. Ritorna aggiornamento parziale di AgentState
"""

import json
import os
import re
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

from agents.state import AgentState
from source_configs.sources import get_crops_sources, get_freshness_threshold_days
from utils.db import get_latest_doc
from utils.prompt_loader import load_prompt
from utils.split_doc import split_doc

load_dotenv()

_SYSTEM_PROMPT = load_prompt(
    "crops_agent.system.txt",
    "Sei un analista commodity caffè. Rispondi solo con JSON valido.",
)

_USER_TEMPLATE = load_prompt(
    "crops_agent.user.txt",
    "Analizza questi dati crops e rispondi con JSON valido: {docs_text}",
)


def _freshness(doc: dict, cadence: str, demo_mode: bool) -> dict:
    try:
        raw_ts = str(doc.get("collected_at", "")).strip()
        raw_ts = re.sub(r"\.\d+", "", raw_ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw_ts)
        days_old = (datetime.now(timezone.utc) - dt).days
    except Exception:
        days_old = None
    threshold = get_freshness_threshold_days(cadence)
    return {
        "days_old": days_old,
        "is_fresh": demo_mode or (days_old is not None and days_old <= threshold),
        "cadenza": cadence,
    }


def _build_docs_text(docs_for_llm: list[tuple[str, dict]]) -> str:
    """Converte i doc in testo formattato per il prompt."""
    parts = []
    for source, doc in docs_for_llm:
        # rimuovi campi tecnici non utili al LLM
        clean = {
            k: v
            for k, v in doc.items()
            if k not in {"_id", "_chart_fields", "country", "macroarea"}
            and not isinstance(v, (list, dict))  # no nested structures
        }
        parts.append(f"=== {source} ===\n{json.dumps(clean, ensure_ascii=False, indent=2)}")
    return "\n\n".join(parts)


def _fallback_signals(sources_found: list[str]) -> dict:
    """Risposta di fallback se Haiku non risponde correttamente."""
    signals = [
        {
            "source": src,
            "area": "crops",
            "fact": f"Dati {src} disponibili ma analisi LLM non riuscita",
            "direction": "neutral",
            "intensity": "low",
            "explanation": "Errore nella chiamata a Claude Haiku — usare dati grezzi.",
        }
        for src in sources_found
    ]
    signals.append({
        "source": "CROPS_AGENT",
        "area": "crops",
        "fact": "Score crops: 50/100 (fallback — LLM non disponibile)",
        "direction": "neutral",
        "intensity": "medium",
        "explanation": "Score di default per mancata risposta LLM.",
        "_score": 50.0,
    })
    return {
        "signals": signals,
        "summaries": {"crops": "Analisi colture non disponibile (errore LLM)."},
        "score": 50.0,
    }


def _call_haiku(docs_for_llm: list[tuple[str, dict]]) -> dict:
    """
    Chiama Claude Haiku con i dati colture e ritorna il JSON parsato.
    In caso di errore, ritorna None.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    docs_text = _build_docs_text(docs_for_llm)
    user_message = _USER_TEMPLATE.format(docs_text=docs_text)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()

        # pulizia: a volte il modello aggiunge ```json ... ```
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        return json.loads(raw)

    except (anthropic.APIError, json.JSONDecodeError, IndexError, KeyError) as e:
        print(f"[crops_agent] Errore Haiku: {e}")
        return None


# ---------------------------------------------------------------------------
# Nodo LangGraph principale
# ---------------------------------------------------------------------------

def crops_agent(state: AgentState) -> dict:
    """
    Nodo LangGraph: analisi rischio colture Brasile via Claude Haiku.

    Output (aggiornamento parziale state):
      signals          → segnali da Haiku + segnale _score
      summaries        → aggiunge chiave "crops"
      docs_for_charts  → dati chart-ready per tutte le fonti trovate
      data_freshness   → freschezza per ogni fonte
    """
    demo_mode: bool = state.get("demo_mode", True)

    docs_for_llm: list[tuple[str, dict]] = []
    new_docs_for_charts: list[dict] = []
    freshness_updates: dict = {}
    sources_found: list[str] = []

    # --- Carica documenti da MongoDB -------------------------------------
    for source, cadence in get_crops_sources():
        doc = get_latest_doc("raw_crops", source)
        if doc:
            llm_part, chart_part = split_doc(doc)
            docs_for_llm.append((source, llm_part))
            new_docs_for_charts.append(chart_part)
            freshness_updates[source] = _freshness(doc, cadence, demo_mode)
            sources_found.append(source)

    if not docs_for_llm:
        # nessun documento trovato — ritorna stato neutro
        return {
            "signals": [{
                "source": "CROPS_AGENT",
                "area": "crops",
                "fact": "Score crops: 0/100 (nessun dato disponibile)",
                "direction": "neutral",
                "intensity": "low",
                "explanation": "Nessun documento trovato in raw_crops su MongoDB.",
                "_score": 0.0,
            }],
            "summaries": {"crops": "Dati colture non disponibili in MongoDB."},
            "docs_for_charts": [],
            "data_freshness": {},
        }

    # --- Chiama Haiku ----------------------------------------------------
    result = _call_haiku(docs_for_llm)

    if result is None:
        fb = _fallback_signals(sources_found)
        new_signals = fb["signals"]
        summary = fb["summaries"]["crops"]
        score_crops = fb["score"]
    else:
        new_signals = result.get("signals", [])
        # assicura che tutti i segnali abbiano area=crops
        for sig in new_signals:
            sig["area"] = "crops"

        score_crops = float(result.get("score", 50.0))
        score_crops = max(0.0, min(100.0, score_crops))
        summary = result.get("summary", "Analisi colture completata.")

        # aggiungi segnale sintetico _score per aggregation_node
        new_signals.append({
            "source": "CROPS_AGENT",
            "area": "crops",
            "fact": f"Score crops: {score_crops:.0f}/100",
            "direction": "negative" if score_crops > 50 else "neutral",
            "intensity": "high" if score_crops > 70 else "medium" if score_crops > 40 else "low",
            "explanation": f"Score LLM Haiku su dati: {', '.join(sources_found)}",
            "_score": score_crops,
        })

    return {
        "signals": new_signals,
        "summaries": {"crops": summary},
        "docs_for_charts": new_docs_for_charts,
        "data_freshness": freshness_updates,
    }
