"""
orchestrator.py — Grafo LangGraph principale per il sistema coffee intelligence Lavazza.

Struttura del grafo:
                      ┌─ environment_agent ─┐
  init_node ──────────┤  prices_agent       ├──► aggregation_node ──► chart_node
  (Send API fan-out)  │  crops_agent        │      (serial)             (serial)
                      └─ geo_agent         ─┘
                                                         │
                                                    rag_node
                                                    (serial)
                                                         │
                                                   report_node
                                                    (serial)
                                                         │
                                                    save_node
                                                    (serial)
                                                         │
                                                        END

La Send API permette ai 4 sub-agenti di girare in PARALLELO.
LangGraph raccoglie i loro aggiornamenti e applica i reducer di AgentState
(operator.add per le liste, _merge_dicts per i dict) prima di passare
il controllo ad aggregation_node.

Per eseguire il grafo:
    from agents.orchestrator import run_graph
    result = run_graph(report_type="daily", demo_mode=True)
"""

import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from langgraph.constants import Send
from langgraph.graph import END, START, StateGraph

from agents.crops_agent import crops_agent
from agents.environment_agent import environment_agent
from agents.geo_agent import geo_agent
from agents.prices_agent import prices_agent
from agents.report_node import report_node
from agents.state import AgentState
from utils.db import get_latest_doc, save_agent_run
from utils.qdrant import collection_exists, search

load_dotenv()

# ---------------------------------------------------------------------------
# Nodi di supporto
# ---------------------------------------------------------------------------

def init_node(state: AgentState) -> dict:
    """
    Nodo iniziale: imposta run_at se non già presente.
    Nessuna logica di business — solo inizializzazione.
    """
    if not state.get("run_at"):
        return {"run_at": datetime.now(timezone.utc).isoformat()}
    return {}


def aggregation_node(state: AgentState) -> dict:
    """
    Aggregazione dopo i 4 sub-agenti paralleli.

    Responsabilità:
      1. Estrae gli score per area dai segnali _score (prodotti da ogni agente)
      2. Calcola final_score con la formula pesata
      3. Produce la lista alerts (segnali critici: intensity=high + direction=negative)
    """
    signals = state.get("signals", [])

    # --- Estrai score per area dai segnali sintetici ----------------------
    area_scores: dict[str, float] = {}
    for sig in signals:
        if "_score" in sig and sig.get("area"):
            area = sig["area"]
            # se ci sono più _score per la stessa area, prendi l'ultimo
            area_scores[area] = float(sig["_score"])

    score_geo = area_scores.get("geo", 0.0)
    score_env = area_scores.get("environment", 0.0)
    score_crops = area_scores.get("crops", 0.0)
    score_prices = area_scores.get("prices", 0.0)

    # --- Formula pesata ---------------------------------------------------
    # geo×0.25 + environment×0.30 + crops×0.30 + prices×0.15
    final_score = round(
        score_geo * 0.25
        + score_env * 0.30
        + score_crops * 0.30
        + score_prices * 0.15,
        1,
    )

    # --- Alert: segnali critici -------------------------------------------
    alerts = [
        sig["fact"]
        for sig in signals
        if sig.get("intensity") == "high"
        and sig.get("direction") == "negative"
        and not sig.get("source", "").endswith("_AGENT")  # escludi segnali sintetici
    ]

    print(
        f"[aggregation_node] "
        f"geo={score_geo:.0f} env={score_env:.0f} "
        f"crops={score_crops:.0f} prices={score_prices:.0f} "
        f"→ final={final_score}"
    )

    return {
        "final_score": final_score,
        "alerts": alerts,
    }


def chart_node(state: AgentState) -> dict:
    """
    Decide quali grafici attivare in base ai docs_for_charts disponibili.

    Per ogni doc_for_charts con campi numerici rilevanti, crea una entry
    in charts con chart_id, title, active=True e interpretive_text.

    Logica semplice per il prototipo: attiva un grafico per ogni source
    che ha almeno un campo con dati numerici.
    """
    docs = state.get("docs_for_charts", [])
    signals = state.get("signals", [])
    area_scores = {
        sig["area"]: sig["_score"]
        for sig in signals
        if "_score" in sig and sig.get("area")
    }

    charts = []
    seen_sources = set()

    for doc in docs:
        source = doc.get("source", "UNKNOWN")
        if source in seen_sources:
            continue
        seen_sources.add(source)

        # verifica se ci sono campi dati (non solo metadati)
        data_fields = {
            k: v
            for k, v in doc.items()
            if k not in {"source", "country", "collected_at"}
            and v is not None
        }
        if not data_fields:
            continue

        chart_id = source.lower().replace("_", "-") + "-chart"
        charts.append({
            "chart_id": chart_id,
            "source": source,
            "title": _chart_title(source),
            "active": True,
            "interpretive_text": _chart_interpretation(source, doc, area_scores),
        })

    return {"charts": charts}


def _chart_title(source: str) -> str:
    titles = {
        "WORLD_BANK_PINKSHEET": "Prezzo Arabica — World Bank Pink Sheet",
        "BCB_PTAX": "Tasso di cambio BRL/USD — BCB PTAX",
        "ECB_DATA_PORTAL": "Tasso EUR/BRL — BCE",
        "NOAA_ENSO": "Indice ENSO — NOAA",
        "NASA_FIRMS": "Incendi attivi — NASA FIRMS",
        "USDA_FAS_PSD": "Bilancio produzione/stock — USDA FAS",
        "IBGE_SIDRA": "Produzione agricola — IBGE SIDRA",
        "COMEX_STAT": "Export caffè Brasile — Comex Stat",
        "CONAB_PDF": "Previsioni raccolto — CONAB",
        "FAOSTAT": "Produzione storica — FAOSTAT",
    }
    return titles.get(source, f"Dati {source}")


def _chart_interpretation(source: str, doc: dict, area_scores: dict) -> str:
    """Genera testo interpretativo breve per ogni grafico."""
    # usa il movement_label se disponibile
    movement = str(doc.get("movement_label") or "").strip()
    summary = str(doc.get("summary_en") or "").strip()

    if summary:
        return summary[:200]

    # fallback generico per area
    area_map = {
        "WORLD_BANK_PINKSHEET": "prices",
        "BCB_PTAX": "prices",
        "ECB_DATA_PORTAL": "prices",
        "NOAA_ENSO": "environment",
        "NASA_FIRMS": "environment",
        "USDA_FAS_PSD": "crops",
        "IBGE_SIDRA": "crops",
        "COMEX_STAT": "crops",
        "CONAB_PDF": "crops",
        "FAOSTAT": "crops",
    }
    area = area_map.get(source, "")
    score = area_scores.get(area, 0.0)

    if movement:
        return f"Trend: {movement}. Score area {area}: {score:.0f}/100."
    return f"Dati aggiornati da {source}. Score area {area}: {score:.0f}/100."


def rag_node(state: AgentState) -> dict:
    """
    Recupera contesto storico da Qdrant reports_archive.

    Usato solo per weekly/monthly — per daily ritorna stringa vuota.
    """
    report_type = state.get("report_type", "daily")

    if report_type == "daily":
        return {"rag_context": ""}

    if not collection_exists("reports_archive"):
        return {"rag_context": ""}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        query = (
            f"Brazil coffee risk report {report_type} "
            f"arabica supply geopolitical environment"
        )
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=query,
        )
        embedding = response.data[0].embedding

        limit = 7 if report_type == "weekly" else 4
        hits = search(
            collection="reports_archive",
            query_vector=embedding,
            limit=limit,
            filters={"country": "BR"},
        )
        chunks = [
            h.get("text") or h.get("content") or h.get("executive_summary") or ""
            for h in hits
            if h
        ]
        rag_context = "\n\n---\n\n".join(c for c in chunks if c)[:4000]

    except Exception as e:
        print(f"[rag_node] Errore recupero RAG: {e}")
        rag_context = ""

    return {"rag_context": rag_context}


def save_node(state: AgentState) -> dict:
    """
    Salva il run completo in MongoDB collection agent_runs.
    Ritorna state invariato (nessun aggiornamento necessario).
    """
    run_doc = {
        "country": state.get("country", "BR"),
        "report_type": state.get("report_type", "daily"),
        "run_at": state.get("run_at"),
        "final_score": state.get("final_score"),
        "alerts": state.get("alerts", []),
        "signals_count": len(state.get("signals", [])),
        "summaries": state.get("summaries", {}),
        "report_json": state.get("report_json", {}),
        "data_freshness": state.get("data_freshness", {}),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    run_id = save_agent_run(run_doc)
    print(f"[save_node] Run salvato: {run_id}")
    return {}


# ---------------------------------------------------------------------------
# Fan-out: Send API per parallelismo
# ---------------------------------------------------------------------------

def _fan_out_to_agents(state: AgentState) -> list[Send]:
    """
    Questa funzione è il cuore del parallelismo LangGraph.

    Viene chiamata come conditional_edge da init_node.
    Ritorna una lista di Send objects — ognuno triggera un nodo
    con una copia dello stato corrente.

    LangGraph esegue tutti e 4 i nodi in parallelo (thread pool),
    poi raccoglie i risultati e applica i reducer di AgentState
    prima di passare il controllo ad aggregation_node.
    """
    return [
        Send("environment_agent", state),
        Send("prices_agent", state),
        Send("crops_agent", state),
        Send("geo_agent", state),
    ]


# ---------------------------------------------------------------------------
# Costruzione del grafo
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """
    Costruisce e compila il grafo LangGraph.

    I nodi vengono registrati per nome (string).
    Gli archi definiscono il flusso di controllo.
    """
    builder = StateGraph(AgentState)

    # --- Registra nodi ---------------------------------------------------
    builder.add_node("init_node", init_node)
    builder.add_node("environment_agent", environment_agent)
    builder.add_node("prices_agent", prices_agent)
    builder.add_node("crops_agent", crops_agent)
    builder.add_node("geo_agent", geo_agent)
    builder.add_node("aggregation_node", aggregation_node)
    builder.add_node("chart_node", chart_node)
    builder.add_node("rag_node", rag_node)
    builder.add_node("report_node", report_node)
    builder.add_node("save_node", save_node)

    # --- Archi -----------------------------------------------------------
    # START → init_node
    builder.add_edge(START, "init_node")

    # init_node → [4 agenti in parallelo] tramite Send API
    builder.add_conditional_edges(
        "init_node",
        _fan_out_to_agents,
        # Specifica i possibili nodi target (LangGraph 0.2+ richiede questo)
        ["environment_agent", "prices_agent", "crops_agent", "geo_agent"],
    )

    # [4 agenti] → aggregation_node (LangGraph aspetta che tutti finiscano)
    builder.add_edge("environment_agent", "aggregation_node")
    builder.add_edge("prices_agent", "aggregation_node")
    builder.add_edge("crops_agent", "aggregation_node")
    builder.add_edge("geo_agent", "aggregation_node")

    # aggregation → chart → rag → report → save → END (seriale)
    builder.add_edge("aggregation_node", "chart_node")
    builder.add_edge("chart_node", "rag_node")
    builder.add_edge("rag_node", "report_node")
    builder.add_edge("report_node", "save_node")
    builder.add_edge("save_node", END)

    return builder.compile()


# Cache del grafo compilato (costoso da ricostruire ogni volta)
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


# ---------------------------------------------------------------------------
# Entry point pubblico
# ---------------------------------------------------------------------------

def run_graph(
    report_type: str = "daily",
    demo_mode: bool = True,
    country: str = "BR",
    delivery_targets: list[str] | None = None,
) -> AgentState:
    """
    Esegue il grafo LangGraph completo e ritorna lo stato finale.

    Args:
        report_type:      "daily" | "weekly" | "monthly"
        demo_mode:        True = bypass freshness check (usare per demo/dev)
        country:          codice paese (fase 1: sempre "BR")
        delivery_targets: team destinatari (default: tutti)

    Returns:
        AgentState finale con report_json, final_score, signals, ecc.
    """
    if delivery_targets is None:
        delivery_targets = ["acquisti", "quality", "management"]

    initial_state: AgentState = {
        "country": country,
        "report_type": report_type,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "delivery_targets": delivery_targets,
        "demo_mode": demo_mode,
        # campi accumulati dai sub-agenti (inizializzati vuoti)
        "signals": [],
        "summaries": {},
        "docs_for_charts": [],
        "data_freshness": {},
        # campi prodotti dai nodi successivi
        "final_score": 0.0,
        "alerts": [],
        "charts": [],
        "rag_context": "",
        "report_json": {},
    }

    graph = get_graph()
    final_state = graph.invoke(initial_state)
    return final_state


# ---------------------------------------------------------------------------
# CLI quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json

    print("Avvio grafo LangGraph — demo_mode=True ...")
    result = run_graph(report_type="daily", demo_mode=True)

    print("\n=== REPORT FINALE ===")
    print(_json.dumps(result.get("report_json", {}), indent=2, ensure_ascii=False))
    print(f"\nFinal Score: {result.get('final_score')}/100")
    print(f"Alerts: {result.get('alerts')}")
    print(f"Segnali totali: {len(result.get('signals', []))}")
