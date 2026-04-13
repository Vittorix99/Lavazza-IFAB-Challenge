"""
geo_agent — sub-agente LLM (Claude Haiku + Qdrant) per il rischio geopolitico.

Fonti:
  - Qdrant `geo_texts` : news GDELT + WTO RSS (embed da n8n con text-embedding-3-small)
  - MongoDB `raw_geo`  : documenti strutturati GDELT e WTO (backup/complemento)

Flusso:
  1. Genera embedding della query geo con OpenAI text-embedding-3-small
  2. Cerca in Qdrant geo_texts i chunk più rilevanti (limit=8)
  3. Carica anche i documenti raw_geo più recenti da MongoDB (fino a 3)
  4. Chiama Claude Haiku con tutto il contesto testuale
  5. Haiku risponde con JSON: {signals: [...], summary: str, score: float}
  6. Ritorna aggiornamento parziale di AgentState
"""

import json
import os
import re
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv
from openai import OpenAI

from agents.state import AgentState
from utils.db import get_recent_docs
from utils.qdrant import collection_exists, search

load_dotenv()

_GEO_QUERY = (
    "Brazil coffee geopolitical risk trade policy export sanctions tariffs "
    "political instability supply chain disruption"
)

_FRESHNESS_DAYS = {"hourly": 1, "daily": 2, "6h": 1}

_SYSTEM_PROMPT = """\
Sei un analista geopolitico specializzato in rischi per la supply chain del caffè \
arabica brasiliano. Analizzi news, comunicati WTO e segnali geopolitici per valutare \
il rischio operativo per un torrefattore europeo (Lavazza).

Rispondi SEMPRE e SOLO con JSON valido, senza testo aggiuntivo fuori dal JSON.
"""

_USER_TEMPLATE = """\
Analizza i seguenti segnali geopolitici recenti relativi al Brasile e al mercato del caffè:

{context_text}

Produci un JSON con questa struttura esatta:
{{
  "signals": [
    {{
      "source": "<GDELT|WTO_RSS|GEO_NEWS>",
      "area": "geo",
      "fact": "<fatto chiave in max 120 caratteri>",
      "direction": "<positive|negative|neutral>",
      "intensity": "<low|medium|high>",
      "explanation": "<spiegazione impatto su supply caffè in max 200 caratteri>"
    }}
  ],
  "summary": "<sintesi rischio geopolitico Brasile-caffè in 2-3 frasi>",
  "score": <numero float 0-100 che rappresenta il rischio geopolitico>
}}

Regole per score:
- 0-20: scenario stabile, nessun rischio commerciale
- 21-40: tensioni minori, impatto trascurabile
- 41-60: rischio moderato (dazi, tensioni diplomatiche, proteste)
- 61-80: rischio elevato (sanzioni, crisi politica, blocchi export)
- 81-100: emergenza (guerra commerciale, embargo, collasso istituzionale)

Genera 3-5 segnali significativi. Se le news sono irrilevanti al caffè, score ≤ 20.
"""


def _get_embedding(text: str) -> list[float] | None:
    """Genera embedding con OpenAI text-embedding-3-small (stesso modello di n8n)."""
    try:
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"[geo_agent] Errore embedding OpenAI: {e}")
        return None


def _build_context_text(
    qdrant_hits: list[dict],
    mongo_docs: list[dict],
) -> str:
    """Costruisce il testo di contesto per il prompt Haiku."""
    parts = []

    if qdrant_hits:
        parts.append("=== NEWS E COMUNICATI RECENTI (ricerca semantica) ===")
        for i, hit in enumerate(qdrant_hits, 1):
            title = hit.get("title") or hit.get("headline") or f"Articolo {i}"
            text = hit.get("text") or hit.get("content") or hit.get("summary") or ""
            source = hit.get("source") or hit.get("domain") or "web"
            date = hit.get("date") or hit.get("published_at") or hit.get("collected_at") or ""
            parts.append(f"[{i}] {title}\nFonte: {source} | Data: {date}\n{text[:500]}")

    if mongo_docs:
        parts.append("\n=== DOCUMENTI STRUTTURATI MONGODB (raw_geo) ===")
        for doc in mongo_docs:
            clean = {
                k: v
                for k, v in doc.items()
                if k not in {"_id", "_chart_fields", "country", "macroarea"}
                and not isinstance(v, (list, dict))
                and len(str(v)) < 500
            }
            if clean:
                parts.append(json.dumps(clean, ensure_ascii=False, indent=2))

    return "\n\n".join(parts) if parts else "Nessun dato geopolitico disponibile."


def _call_haiku(context_text: str) -> dict | None:
    """Chiama Claude Haiku per l'analisi geopolitica."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_message = _USER_TEMPLATE.format(context_text=context_text)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)

    except (anthropic.APIError, json.JSONDecodeError, IndexError, KeyError) as e:
        print(f"[geo_agent] Errore Haiku: {e}")
        return None


def _fallback_result() -> dict:
    return {
        "signals": [{
            "source": "GEO_AGENT",
            "area": "geo",
            "fact": "Score geo: 20/100 (fallback — LLM o embedding non disponibile)",
            "direction": "neutral",
            "intensity": "low",
            "explanation": "Errore recupero dati geo o chiamata LLM fallita.",
            "_score": 20.0,
        }],
        "summary": "Analisi geopolitica non disponibile per errore tecnico.",
        "score": 20.0,
    }


# ---------------------------------------------------------------------------
# Nodo LangGraph principale
# ---------------------------------------------------------------------------

def geo_agent(state: AgentState) -> dict:
    """
    Nodo LangGraph: analisi rischio geopolitico Brasile via Claude Haiku + Qdrant.

    Output (aggiornamento parziale state):
      signals          → segnali da Haiku + segnale _score
      summaries        → aggiunge chiave "geo"
      docs_for_charts  → lista vuota (dati geo non sono plottabili come timeseries)
      data_freshness   → freschezza per GDELT e WTO_RSS
    """
    demo_mode: bool = state.get("demo_mode", True)

    qdrant_hits: list[dict] = []
    mongo_docs: list[dict] = []
    freshness_updates: dict = {}

    # --- Qdrant: ricerca semantica geo_texts ----------------------------
    if collection_exists("geo_texts"):
        embedding = _get_embedding(_GEO_QUERY)
        if embedding:
            qdrant_hits = search(
                collection="geo_texts",
                query_vector=embedding,
                limit=8,
                filters={"country": "BR"},
            )
            # fallback senza filtro paese se nessun risultato
            if not qdrant_hits:
                qdrant_hits = search(
                    collection="geo_texts",
                    query_vector=embedding,
                    limit=8,
                )
    else:
        print("[geo_agent] Collection geo_texts non trovata in Qdrant — uso solo MongoDB")

    # --- MongoDB: documenti raw_geo più recenti -------------------------
    raw_geo_docs = get_recent_docs("raw_geo", "geo", limit=5)
    if raw_geo_docs:
        mongo_docs = raw_geo_docs
        # freschezza basata sul documento più recente
        try:
            raw_ts = str(raw_geo_docs[0].get("collected_at", "")).strip()
            raw_ts = re.sub(r"\.\d+", "", raw_ts).replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw_ts)
            days_old = (datetime.now(timezone.utc) - dt).days
        except Exception:
            days_old = None

        freshness_updates["GDELT"] = {
            "days_old": days_old,
            "is_fresh": demo_mode or (days_old is not None and days_old <= 1),
            "cadenza": "hourly",
        }
        freshness_updates["WTO_RSS"] = {
            "days_old": days_old,
            "is_fresh": demo_mode or (days_old is not None and days_old <= 1),
            "cadenza": "6h",
        }

    # --- Nessun dato disponibile ----------------------------------------
    if not qdrant_hits and not mongo_docs:
        result = _fallback_result()
        return {
            "signals": result["signals"],
            "summaries": {"geo": result["summary"]},
            "docs_for_charts": [],
            "data_freshness": freshness_updates,
        }

    # --- Chiama Haiku ---------------------------------------------------
    context_text = _build_context_text(qdrant_hits, mongo_docs)
    result = _call_haiku(context_text)

    if result is None:
        result = _fallback_result()

    new_signals = result.get("signals", [])
    for sig in new_signals:
        sig["area"] = "geo"

    score_geo = float(result.get("score", 20.0))
    score_geo = max(0.0, min(100.0, score_geo))
    summary = result.get("summary", "Analisi geopolitica completata.")

    new_signals.append({
        "source": "GEO_AGENT",
        "area": "geo",
        "fact": f"Score geopolitico: {score_geo:.0f}/100",
        "direction": "negative" if score_geo > 40 else "neutral",
        "intensity": "high" if score_geo > 70 else "medium" if score_geo > 40 else "low",
        "explanation": (
            f"Analisi Haiku su {len(qdrant_hits)} chunk Qdrant + "
            f"{len(mongo_docs)} doc MongoDB."
        ),
        "_score": score_geo,
    })

    return {
        "signals": new_signals,
        "summaries": {"geo": summary},
        "docs_for_charts": [],  # dati geo non sono timeseries plottabili
        "data_freshness": freshness_updates,
    }
