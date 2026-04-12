"""
dashboard/app.py — Lavazza Coffee Intelligence Dashboard

3 sezioni principali:
  📊 Daily Report    — streaming LangGraph real-time + report giornaliero
  📈 Weekly Reports  — 3 report team (Acquisti / Quality / Management)
  💬 Chat            — chatbot RAG (Qdrant + MongoDB + Claude Sonnet)

Avvio:
    cd lavazza-coffee-agent
    streamlit run dashboard/app.py
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import streamlit as st
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Setup path
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

load_dotenv(_ROOT / ".env")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Lavazza Coffee Intelligence",
    page_icon="☕",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
  .risk-verde  {background:#d4edda;color:#155724;padding:16px 20px;border-radius:10px;
                text-align:center;}
  .risk-giallo {background:#fff3cd;color:#856404;padding:16px 20px;border-radius:10px;
                text-align:center;}
  .risk-rosso  {background:#f8d7da;color:#721c24;padding:16px 20px;border-radius:10px;
                text-align:center;}
  .score-num   {font-size:3rem;font-weight:800;line-height:1;}
  .score-label {font-size:0.85rem;margin-top:4px;opacity:0.8;}
  .sig-card    {border-left:4px solid #ccc;padding:8px 12px;margin:3px 0;
                background:#fafafa;border-radius:4px;font-size:0.9rem;}
  .sig-neg     {border-left-color:#dc3545;}
  .sig-pos     {border-left-color:#28a745;}
  .sig-neu     {border-left-color:#6c757d;}
  .team-badge  {display:inline-block;padding:4px 12px;border-radius:20px;
                font-size:0.8rem;font-weight:600;margin-bottom:8px;}
  .acquisti-badge {background:#cce5ff;color:#004085;}
  .quality-badge  {background:#d4edda;color:#155724;}
  .mgmt-badge     {background:#e2e3e5;color:#383d41;}
  div[data-testid="stChatMessage"] {border-radius:10px;margin:4px 0;}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Helpers UI
# ---------------------------------------------------------------------------

AREA_LABELS = {
    "geo": "Geopolitico",
    "environment": "Ambiente",
    "crops": "Colture",
    "prices": "Prezzi",
}
AREA_WEIGHTS = {"geo": 0.25, "environment": 0.30, "crops": 0.30, "prices": 0.15}


def risk_class(score: float) -> str:
    return "risk-verde" if score <= 40 else "risk-giallo" if score <= 70 else "risk-rosso"


def risk_emoji(score: float) -> str:
    return "🟢" if score <= 40 else "🟡" if score <= 70 else "🔴"


def direction_icon(d: str) -> str:
    return {"positive": "↑", "negative": "↓", "neutral": "→"}.get(d, "→")


def intensity_badge(i: str) -> str:
    return {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}.get(i, "")


def _score_from_signals(signals: list[dict]) -> dict[str, float]:
    return {
        sig["area"]: sig["_score"]
        for sig in signals
        if "_score" in sig and sig.get("area")
    }


def _render_score_gauge(final_score: float) -> None:
    css = risk_class(final_score)
    label = "NORMALE" if final_score <= 40 else "WATCH" if final_score <= 70 else "ALERT"
    st.markdown(
        f'<div class="{css}">'
        f'<div class="score-num">{final_score:.0f}</div>'
        f'<div class="score-label">/ 100 &nbsp;·&nbsp; {risk_emoji(final_score)} {label}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_area_scores(signals: list[dict]) -> None:
    scores = _score_from_signals(signals)
    cols = st.columns(4)
    for i, (area, label) in enumerate(AREA_LABELS.items()):
        s = scores.get(area, 0.0)
        w = AREA_WEIGHTS[area]
        with cols[i]:
            st.metric(f"{label}", f"{s:.0f}/100", help=f"Peso nel final score: {w:.0%}")
            st.progress(int(s) / 100)


def _render_signals_detail(signals: list[dict], area_filter: list[str]) -> None:
    for sig in signals:
        if sig.get("area") not in area_filter:
            continue
        if sig.get("source", "").endswith("_AGENT"):
            continue
        d = sig.get("direction", "neutral")
        css = f"sig-card sig-{'neg' if d=='negative' else 'pos' if d=='positive' else 'neu'}"
        st.markdown(
            f'<div class="{css}">'
            f'{intensity_badge(sig.get("intensity","low"))} {direction_icon(d)} '
            f'<strong>{sig.get("fact","")}</strong><br>'
            f'<small style="color:#666">{sig.get("source","")} — {sig.get("explanation","")}</small>'
            f'</div>',
            unsafe_allow_html=True,
        )


def _render_freshness_table(data_freshness: dict) -> None:
    if not data_freshness:
        st.caption("Nessun dato di freshness disponibile.")
        return
    rows = [
        {
            "Fonte": src,
            "Cadenza": info.get("cadenza", "?"),
            "Giorni fa": info.get("days_old", "?"),
            "Status": "✅ Fresh" if info.get("is_fresh") else "⚠️ Stale",
        }
        for src, info in data_freshness.items()
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# LangGraph streaming runner
# ---------------------------------------------------------------------------

_NODE_LABELS = {
    "init_node":           "Inizializzazione",
    "environment_agent":   "Agente Ambiente (Haiku)",
    "prices_agent":        "Agente Prezzi (Haiku)",
    "crops_agent":         "Agente Colture (Haiku)",
    "geo_agent":           "Agente Geopolitico (Haiku + Qdrant)",
    "aggregation_node":    "Aggregazione score",
    "chart_node":          "Preparazione grafici",
    "rag_node":            "RAG context (Qdrant)",
    "report_node":         "Generazione report (Sonnet)",
    "save_node":           "Salvataggio su MongoDB",
}


def run_graph_streaming(report_type: str, demo_mode: bool) -> dict:
    """
    Esegue il grafo LangGraph con streaming real-time.
    Mostra i nodi che completano nell'ordine in cui finiscono.
    Ritorna lo stato finale completo.
    """
    from agents.orchestrator import build_graph
    from agents.state import AgentState

    initial_state: AgentState = {
        "country": "BR",
        "report_type": report_type,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "delivery_targets": ["acquisti", "quality", "management"],
        "demo_mode": demo_mode,
        "signals": [],
        "summaries": {},
        "docs_for_charts": [],
        "data_freshness": {},
        "final_score": 0.0,
        "alerts": [],
        "charts": [],
        "rag_context": "",
        "report_json": {},
    }

    graph = build_graph()
    completed_nodes: list[str] = []
    final_state = initial_state

    with st.status("⚙️ Grafo LangGraph in esecuzione...", expanded=True) as status:
        # stream_mode="values" → ogni yield è lo STATO COMPLETO dopo ogni nodo/batch.
        # Confrontiamo snapshot consecutivi per capire quale nodo ha appena finito.
        prev_snapshot: dict = {}

        for state_snapshot in graph.stream(initial_state, stream_mode="values"):
            final_state = state_snapshot  # l'ultimo sarà lo stato finale completo

            # Rileva quali campi sono cambiati rispetto allo snapshot precedente
            for key, val in state_snapshot.items():
                old = prev_snapshot.get(key)
                if old != val:
                    # Mappa campi → nodi responsabili
                    field_to_node = {
                        "run_at": "init_node",
                        "final_score": "aggregation_node",
                        "charts": "chart_node",
                        "rag_context": "rag_node",
                        "report_json": "report_node",
                    }
                    if key in field_to_node:
                        node = field_to_node[key]
                        label = _NODE_LABELS.get(node, node)
                        extra = ""
                        if key == "final_score":
                            extra = f" → **{val:.1f}/100** {risk_emoji(val)}"
                        elif key == "report_json" and isinstance(val, dict):
                            extra = f" → '{val.get('headline','')[:50]}'"
                        status.write(f"✅ {label}{extra}")

            # Rileva completamento agenti da signals e summaries
            new_sigs = state_snapshot.get("signals", [])
            old_sigs = prev_snapshot.get("signals", [])
            if len(new_sigs) > len(old_sigs):
                new_areas = {s["area"] for s in new_sigs[len(old_sigs):] if not s.get("source","").endswith("_AGENT")}
                for area in new_areas:
                    agent_map = {
                        "environment": "environment_agent",
                        "prices": "prices_agent",
                        "crops": "crops_agent",
                        "geo": "geo_agent",
                    }
                    if node := agent_map.get(area):
                        label = _NODE_LABELS.get(node, node)
                        n_sigs = len([s for s in new_sigs if s.get("area") == area and not s.get("source","").endswith("_AGENT")])
                        status.write(f"✅ {label} → {n_sigs} segnali")

            prev_snapshot = dict(state_snapshot)

        status.update(label="✅ Analisi completata!", state="complete", expanded=False)

    return final_state


# ---------------------------------------------------------------------------
# Daily Report renderer
# ---------------------------------------------------------------------------

def _render_daily_report(result: dict) -> None:
    report_json = result.get("report_json", {})
    final_score = result.get("final_score", 0.0)
    signals = result.get("signals", [])
    alerts = result.get("alerts", [])
    data_freshness = result.get("data_freshness", {})

    headline = report_json.get("headline", "Report Caffè Brasile")
    exec_summary = report_json.get("executive_summary", "")
    sections = report_json.get("sections", [])
    correlations = report_json.get("correlations", [])
    outlook = report_json.get("outlook", "")
    run_at = result.get("run_at", "")

    st.markdown(f"### {headline}")
    st.caption(f"Generato: {run_at[:19].replace('T',' ')} UTC")

    if alerts:
        for a in alerts:
            st.error(a)

    col_gauge, col_summary = st.columns([1, 3])
    with col_gauge:
        _render_score_gauge(final_score)
    with col_summary:
        st.markdown("**Executive Summary**")
        st.markdown(exec_summary)

    st.divider()
    _render_area_scores(signals)
    st.divider()

    # Sezioni narrative
    st.markdown("#### Analisi per Area")
    for sec in sections:
        area = sec.get("area", "")
        label = AREA_LABELS.get(area, area)
        score = sec.get("score", 0.0)
        with st.expander(f"{label} — {risk_emoji(score)} {score}/100", expanded=True):
            st.markdown(sec.get("text", ""))
            key_sigs = sec.get("signals", [])
            if key_sigs:
                for ks in key_sigs:
                    st.markdown(f"• {ks}")

    # Correlazioni + Outlook
    col_c, col_o = st.columns(2)
    with col_c:
        if correlations:
            st.markdown("#### Correlazioni")
            for c in correlations:
                st.markdown(f"• {c}")
    with col_o:
        if outlook:
            st.markdown("#### Outlook 24-48h")
            st.info(outlook)

    st.divider()

    with st.expander("Segnali dettaglio", expanded=False):
        area_sel = st.multiselect(
            "Filtra area",
            options=list(AREA_LABELS.keys()),
            default=list(AREA_LABELS.keys()),
            format_func=lambda x: AREA_LABELS[x],
            key="daily_sig_filter",
        )
        _render_signals_detail(signals, area_sel)

    with st.expander("Data Freshness", expanded=False):
        _render_freshness_table(data_freshness)

    with st.expander("Raw JSON", expanded=False):
        st.json(report_json)


# ---------------------------------------------------------------------------
# Weekly Report renderer
# ---------------------------------------------------------------------------

def _render_team_section(team_data: dict, team_name: str) -> None:
    badge_class = f"{team_name}-badge"
    team_display = team_name.capitalize()

    st.markdown(
        f'<span class="team-badge {badge_class}">{team_display}</span>',
        unsafe_allow_html=True,
    )

    headline = team_data.get("headline", "")
    if headline:
        st.markdown(f"### {headline}")

    # campi specifici per team
    if team_name == "acquisti":
        col1, col2 = st.columns(2)
        with col1:
            if v := team_data.get("price_outlook"):
                st.markdown("**Outlook Prezzi**")
                st.markdown(v)
            if v := team_data.get("hedge_window"):
                st.info(f"**Finestra hedging:** {v}")
        with col2:
            if v := team_data.get("fx_outlook"):
                st.markdown("**Outlook FX (EUR/BRL)**")
                st.markdown(v)
            if v := team_data.get("supply_risk"):
                st.markdown("**Rischio fornitura**")
                st.markdown(v)
        if recs := team_data.get("recommendations", []):
            st.markdown("**Azioni raccomandate**")
            for r in recs:
                st.markdown(f"• {r}")
        if v := team_data.get("outlook"):
            st.info(v)

    elif team_name == "quality":
        if v := team_data.get("crop_quality_outlook"):
            st.markdown("**Qualità raccolto**")
            st.markdown(v)
        col1, col2 = st.columns(2)
        with col1:
            if v := team_data.get("regional_analysis"):
                st.markdown("**Analisi regionale**")
                st.markdown(v)
        with col2:
            if v := team_data.get("sensory_risk"):
                st.markdown("**Rischio sensoriale**")
                st.markdown(v)
        if risks := team_data.get("risk_factors", []):
            st.markdown("**Fattori di rischio qualità**")
            for r in risks:
                st.markdown(f"• {r}")
        if recs := team_data.get("recommendations", []):
            st.markdown("**Azioni raccomandate**")
            for r in recs:
                st.markdown(f"• {r}")
        if v := team_data.get("outlook"):
            st.info(v)

    elif team_name == "management":
        if v := team_data.get("executive_summary"):
            st.markdown("**Quadro strategico**")
            st.markdown(v)
        if secs := team_data.get("sections", []):
            for sec in secs:
                area = sec.get("area", "")
                label = AREA_LABELS.get(area, area)
                score = sec.get("score", 0)
                with st.expander(f"{label} — {risk_emoji(score)} {score}/100"):
                    st.markdown(sec.get("text", ""))
                    for ks in sec.get("signals", []):
                        st.markdown(f"• {ks}")
        col1, col2 = st.columns(2)
        with col1:
            if corrs := team_data.get("correlations", []):
                st.markdown("**Correlazioni strategiche**")
                for c in corrs:
                    st.markdown(f"• {c}")
        with col2:
            if v := team_data.get("business_impact"):
                st.markdown("**Impatto business**")
                st.warning(v)
        if actions := team_data.get("strategic_actions", []):
            st.markdown("**Decisioni strategiche**")
            for a in actions:
                st.markdown(f"• {a}")
        if v := team_data.get("outlook"):
            st.info(v)


def _render_weekly_report(result: dict) -> None:
    report_json = result.get("report_json", {})
    final_score = result.get("final_score", 0.0)
    signals = result.get("signals", [])
    alerts = result.get("alerts", [])
    data_freshness = result.get("data_freshness", {})
    run_at = result.get("run_at", "")

    st.markdown("### Report Settimanale — Brasile")
    st.caption(f"Periodo terminante: {run_at[:10]} · Score: {final_score:.1f}/100 {risk_emoji(final_score)}")

    if alerts:
        for a in alerts:
            st.error(a)

    _render_area_scores(signals)
    st.divider()

    # 3 tab per team
    tab_acq, tab_qual, tab_mgmt = st.tabs(
        ["Team Acquisti", "Team Quality", "Management"]
    )

    with tab_acq:
        if acquisti := report_json.get("acquisti"):
            _render_team_section(acquisti, "acquisti")
        else:
            st.info("Report Acquisti non disponibile.")

    with tab_qual:
        if quality := report_json.get("quality"):
            _render_team_section(quality, "quality")
        else:
            st.info("Report Quality non disponibile.")

    with tab_mgmt:
        if mgmt := report_json.get("management"):
            _render_team_section(mgmt, "management")
        else:
            st.info("Report Management non disponibile.")

    st.divider()

    with st.expander("Data Freshness", expanded=False):
        _render_freshness_table(data_freshness)

    with st.expander("Raw JSON", expanded=False):
        st.json(report_json)


# ---------------------------------------------------------------------------
# RAG debug renderer
# ---------------------------------------------------------------------------

def _render_rag_debug(question: str, debug: dict, context: str) -> None:
    """Mostra cosa è stato recuperato dal sistema RAG per una data domanda."""
    with st.expander(f"RAG context — '{question[:60]}'", expanded=False):
        col1, col2, col3 = st.columns(3)
        col1.metric("Sezioni trovate", debug.get("sections_found", 0))
        col2.metric("Caratteri contesto", debug.get("total_chars", 0))

        ar = debug.get("agent_run")
        if ar:
            col3.metric("Ultimo report", f"{ar.get('date','?')} · {ar.get('score',0):.0f}/100")
        else:
            col3.metric("Ultimo report", "nessuno")

        st.markdown("**Qdrant (ricerca semantica)**")
        qdrant_rows = [
            {"Collection": coll, "Risultato": res}
            for coll, res in debug.get("qdrant", {}).items()
        ]
        if qdrant_rows:
            st.dataframe(qdrant_rows, hide_index=True, use_container_width=True)
        else:
            st.caption("Nessuna query Qdrant (embedding non disponibile).")

        st.markdown("**MongoDB (dati raw)**")
        mongo_rows = [
            {"Collection": coll, "Documenti": res}
            for coll, res in debug.get("mongodb", {}).items()
        ]
        if mongo_rows:
            st.dataframe(mongo_rows, hide_index=True, use_container_width=True)

        with st.expander("Testo contesto completo inviato a Claude", expanded=False):
            st.text(context)


# ---------------------------------------------------------------------------
# Chatbot RAG
# ---------------------------------------------------------------------------

def _get_embedding(text: str) -> list[float] | None:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        resp = client.embeddings.create(model="text-embedding-3-small", input=text)
        return resp.data[0].embedding
    except Exception as e:
        print(f"[chat] Errore embedding: {e}")
        return None


def _build_chat_context(question: str) -> tuple[str, dict]:
    """
    Costruisce il contesto RAG per il chatbot.
    Ritorna (context_text, debug_info) dove debug_info descrive cosa è stato trovato.
    """
    from utils.db import get_db
    from utils.qdrant import collection_exists, search

    parts: list[str] = []
    debug: dict = {
        "agent_run": None,
        "qdrant": {},
        "mongodb": {},
    }

    # --- Ultimo run agente ---
    db = get_db()
    last_run = db["agent_runs"].find_one({}, sort=[("saved_at", -1)])
    if last_run:
        rj = last_run.get("report_json", {})
        run_date = last_run.get('run_at', '')[:10]
        score = last_run.get('final_score', 0)
        parts.append(
            f"=== ULTIMO REPORT ({run_date}) ===\n"
            f"Risk Score: {score:.1f}/100\n"
            f"Headline: {rj.get('headline', '')}\n"
            f"Executive Summary: {rj.get('executive_summary', rj.get('management', {}).get('executive_summary', ''))}\n"
            f"Alerts: {', '.join(last_run.get('alerts', [])) or 'nessuno'}"
        )
        debug["agent_run"] = {
            "date": run_date,
            "score": score,
            "type": last_run.get("report_type", "?"),
        }

    # --- Ricerca Qdrant ---
    embedding = _get_embedding(question)
    if embedding:
        for collection in ["geo_texts", "crops_texts", "reports_archive"]:
            if not collection_exists(collection):
                debug["qdrant"][collection] = "collection non trovata"
                continue
            hits = search(collection=collection, query_vector=embedding, limit=3)
            debug["qdrant"][collection] = f"{len(hits)} hit"
            if hits:
                texts = []
                for h in hits:
                    t = (
                        h.get("text") or h.get("content") or
                        h.get("summary_en") or h.get("embed_text") or
                        h.get("executive_summary") or ""
                    )
                    if t:
                        texts.append(t[:400])
                if texts:
                    parts.append(
                        f"=== DOCUMENTI RILEVANTI ({collection}) ===\n"
                        + "\n---\n".join(texts)
                    )
    else:
        debug["qdrant"]["_embedding"] = "errore generazione embedding"

    # --- Dati raw recenti MongoDB ---
    for col_name, macroarea in [
        ("raw_prices", "prices"),
        ("raw_crops", "crops"),
        ("raw_environment", "environment"),
    ]:
        docs = list(db[col_name].find(
            {"macroarea": macroarea, "country": "BR"},
            {"source": 1, "summary_en": 1, "movement_label": 1,
             "collected_at": 1, "signals": 1,
             "total_detections": 1, "coffee_zone_detections": 1,
             "coffee_zone_ratio": 1, "affected_municipalities": 1},
            sort=[("collected_at", -1)],
            limit=2,
        ))
        debug["mongodb"][col_name] = f"{len(docs)} doc"
        snippets = []
        for doc in docs:
            src = doc.get("source", "?")
            lines = []
            if summary := doc.get("summary_en"):
                lines.append(summary[:300])
            if doc.get("total_detections") is not None:
                cz = doc.get("coffee_zone_detections", 0)
                ratio = doc.get("coffee_zone_ratio", 0)
                munis = doc.get("affected_municipalities", [])
                lines.append(
                    f"Fuochi totali: {doc['total_detections']} | "
                    f"In coffee zones: {cz} ({ratio:.0%}) | "
                    f"Comuni: {', '.join(munis[:5]) if munis else 'n/d'}"
                )
            if lines:
                snippets.append(f"{src}: " + " — ".join(lines))
        if snippets:
            parts.append(f"=== RAW DATA {macroarea.upper()} ===\n" + "\n".join(snippets))

    # --- GDELT + WTO: articoli geo recenti da raw_geo ---
    geo_docs = list(db["raw_geo"].find(
        {"country": "BR"},
        {"source": 1, "title": 1, "summary_en": 1, "signals": 1,
         "sentiment": 1, "topic": 1, "collected_at": 1},
        sort=[("collected_at", -1)],
        limit=6,
    ))
    debug["mongodb"]["raw_geo"] = f"{len(geo_docs)} doc"
    geo_snippets = []
    for doc in geo_docs:
        src = doc.get("source", "?")
        title = doc.get("title") or ""
        summary = doc.get("summary_en") or ""
        topic = doc.get("topic") or ""
        sentiment = doc.get("sentiment") or ""
        sigs = doc.get("signals", [])
        line = f"[{src}] {title}"
        if summary:
            line += f" — {summary[:200]}"
        if sigs:
            line += f" | Segnali: {'; '.join(str(s) for s in sigs[:3])}"
        if topic or sentiment:
            line += f" ({topic}, {sentiment})"
        geo_snippets.append(line)
    if geo_snippets:
        parts.append("=== NEWS GEO (GDELT/WTO) — raw_geo ===\n" + "\n".join(geo_snippets))

    context = "\n\n".join(parts) if parts else "Nessun dato di contesto disponibile."
    debug["total_chars"] = len(context)
    debug["sections_found"] = len(parts)
    return context, debug


def _stream_chat_response(question: str, context: str, history: list[dict]):
    """Generator che streamma la risposta di Claude Sonnet."""
    system = """\
Sei l'esperto globale delle origini del caffè di Lavazza.
Hai accesso ai dati di intelligence più recenti sul Brasile provenienti da 13 fonti dati:
GDELT (news geopolitiche orarie), WTO News, Port Congestion (AIS), CONAB PDF (previsioni raccolto),
USDA FAS, IBGE SIDRA, Comex Stat, FAOSTAT (colture), World Bank Pink Sheet, BCB PTAX, ECB (prezzi/FX),
NASA FIRMS (incendi — arricchiti con coffee regions a livello municipale), NOAA ENSO (clima).

Per i fuochi NASA FIRMS: il sistema arricchisce ogni rilevamento con i confini GeoJSON dei comuni
produttori di caffè (MongoDB coffee_regions, 2 livelli: stati L1 e comuni L2). I campi
coffee_zone_detections e coffee_zone_ratio indicano quanti fuochi cadono nei comuni produttori.

Rispondi in italiano, cita sempre numeri specifici quando disponibili.
Sii conciso (max 200 parole) a meno che l'utente non chieda approfondimenti.
Se la domanda è fuori dal dominio caffè/Brasile/supply chain, reindirizza educatamente.
"""
    messages = []
    for msg in history[-6:]:  # ultimi 6 messaggi per contesto
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({
        "role": "user",
        "content": (
            f"Contesto dati aggiornati:\n{context}\n\n"
            f"Domanda: {question}"
        ),
    })

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## Coffee Intelligence")
    st.markdown("**Brasile** — Fase 1")
    st.divider()
    demo_mode = st.toggle("Demo mode (bypass freshness)", value=True,
                          help="In demo mode tutti i dati sono considerati freschi")
    rag_debug = st.toggle("Mostra RAG context", value=False,
                          help="Mostra le sorgenti e il contesto recuperato per ogni risposta del chatbot")
    st.divider()
    st.caption("Servizi attivi:")
    st.caption("• MongoDB localhost:27017")
    st.caption("• Qdrant localhost:6333")
    st.caption("• n8n localhost:5678")
    st.divider()
    st.caption("Agenti LangGraph:")
    st.caption("• env_agent → Haiku")
    st.caption("• prices_agent → Haiku")
    st.caption("• crops_agent → Haiku")
    st.caption("• geo_agent → Haiku + Qdrant")
    st.caption("• report_node → Sonnet")
    st.divider()
    st.caption("Dashboard ambiente:")
    st.caption("cd dashboard && streamlit run dashboard.py")


# ---------------------------------------------------------------------------
# Session state inizializzazione
# ---------------------------------------------------------------------------
for key in ["daily_result", "weekly_result"]:
    if key not in st.session_state:
        st.session_state[key] = None

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "rag_debug_history" not in st.session_state:
    st.session_state.rag_debug_history = []  # lista di (question, debug_info, context)

# ---------------------------------------------------------------------------
# Tabs principali
# ---------------------------------------------------------------------------
tab_daily, tab_weekly, tab_chat = st.tabs([
    "Daily Report",
    "Weekly Reports",
    "Chat",
])

# ============================================================================
# TAB 1 — DAILY REPORT
# ============================================================================
with tab_daily:
    st.markdown("## Report Giornaliero — Brasile")
    st.markdown(
        "Analisi completa del rischio supply chain caffè brasiliano. "
        "I 4 agenti girano in parallelo, poi Claude Sonnet genera il report."
    )

    col_run, col_info = st.columns([1, 3])
    with col_run:
        run_daily = st.button("Avvia analisi Daily", type="primary",
                              use_container_width=True, key="btn_daily")
    with col_info:
        st.info(
            "Real-time: vedrai ogni agente completare nell'ordine reale di esecuzione. "
            "I 4 sub-agenti (Haiku) girano in parallelo. Il report (Sonnet) arriva per ultimo."
        )

    if run_daily:
        with st.spinner(""):
            try:
                st.session_state.daily_result = run_graph_streaming("daily", demo_mode)
            except Exception as e:
                st.error(f"Errore: {e}")
                st.exception(e)

    if st.session_state.daily_result:
        _render_daily_report(st.session_state.daily_result)
    else:
        st.markdown("---")
        with st.expander("Come funziona il sistema", expanded=True):
            st.markdown("""
**Layer 1 — Ingestion (n8n)**
13 connettori raccolgono dati ogni ora/giorno/settimana/mese:
GDELT · WTO News · Port Congestion · CONAB PDF · USDA FAS · IBGE SIDRA · Comex Stat
· FAOSTAT · World Bank · BCB PTAX · ECB · NASA FIRMS · NOAA ENSO

**Layer 2 — Agenti LangGraph (schema-agnostico)**
```
START → [env_agent  ─┐
          prices_agent├→ aggregation → chart → rag → report(Sonnet) → save → END
          crops_agent ┤
          geo_agent  ─┘]
            (parallelo — Send API)
```
**Formula Risk Score:**
`final = geo×0.25 + environment×0.30 + crops×0.30 + prices×0.15`

0-40 normale (verde) · 41-70 watch (giallo) · 71-100 alert (rosso)
            """)

# ============================================================================
# TAB 2 — WEEKLY REPORTS
# ============================================================================
with tab_weekly:
    st.markdown("## Report Settimanale — Brasile")
    st.markdown(
        "3 report dedicati generati da Claude Sonnet con focus specifico per team. "
        "Usa il contesto RAG degli ultimi 7 daily (se disponibili in Qdrant)."
    )

    col_run2, col_info2 = st.columns([1, 3])
    with col_run2:
        run_weekly = st.button("Avvia analisi Weekly", type="primary",
                               use_container_width=True, key="btn_weekly")
    with col_info2:
        st.info(
            "3 report paralleli: Acquisti (hedging/prezzi) · "
            "Quality (qualità raccolto/regionale) · Management (sintesi strategica). "
            "Ognuno è una chiamata separata a Claude Sonnet con sistema prompt dedicato."
        )

    if run_weekly:
        with st.spinner(""):
            try:
                st.session_state.weekly_result = run_graph_streaming("weekly", demo_mode)
            except Exception as e:
                st.error(f"Errore: {e}")
                st.exception(e)

    if st.session_state.weekly_result:
        _render_weekly_report(st.session_state.weekly_result)
    else:
        st.markdown("---")
        st.markdown("""
**Struttura report settimanale:**

| Team | Focus | Modello |
|------|-------|---------|
| **Acquisti** | Prezzi arabica · hedging · finestre acquisto · rischio fornitura | Sonnet |
| **Quality** | Qualità raccolto · analisi regionale · rischio sensoriale · defect rate | Sonnet |
| **Management** | Sintesi strategica · correlazioni · impatto P&L · decisioni top-level | Sonnet |
        """)

# ============================================================================
# TAB 3 — CHATBOT RAG
# ============================================================================
with tab_chat:
    st.markdown("## Coffee Intelligence Chat")
    st.markdown(
        "Chiedi qualsiasi cosa sui dati di intelligence Brasile. "
        "Il chatbot usa Qdrant + MongoDB + Claude Sonnet per rispondere."
    )

    # --- Mostra storia chat con RAG debug opzionale ---
    for i, msg in enumerate(st.session_state.chat_history):
        with st.chat_message(msg["role"], avatar="☕" if msg["role"] == "assistant" else None):
            st.markdown(msg["content"])
        # Mostra debug sotto ogni risposta assistant se abilitato
        if rag_debug and msg["role"] == "assistant":
            # trova il debug corrispondente (stesso indice turno)
            turn_idx = sum(1 for m in st.session_state.chat_history[:i+1] if m["role"] == "assistant") - 1
            if turn_idx < len(st.session_state.rag_debug_history):
                _q, _dbg, _ctx = st.session_state.rag_debug_history[turn_idx]
                _render_rag_debug(_q, _dbg, _ctx)

    # --- Input utente ---
    if prompt := st.chat_input("Es: Qual è il rischio attuale? Come stanno i prezzi arabica? Ci sono incendi?"):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # costruisci contesto RAG
        with st.spinner("Cercando nei dati..."):
            context, rag_debug_info = _build_chat_context(prompt)

        # stream risposta
        with st.chat_message("assistant", avatar="☕"):
            response = st.write_stream(
                _stream_chat_response(
                    prompt,
                    context,
                    st.session_state.chat_history[:-1],
                )
            )

        st.session_state.chat_history.append({"role": "assistant", "content": response})
        st.session_state.rag_debug_history.append((prompt, rag_debug_info, context))

        # Mostra debug immediatamente se toggle attivo
        if rag_debug:
            _render_rag_debug(prompt, rag_debug_info, context)

    # --- Bottoni utility ---
    col_clear, col_examples = st.columns([1, 3])
    with col_clear:
        if st.button("Cancella chat", use_container_width=True):
            st.session_state.chat_history = []
            st.session_state.rag_debug_history = []
            st.rerun()

    with col_examples:
        with st.expander("Domande di esempio"):
            examples = [
                "Qual è il risk score attuale per il Brasile?",
                "Come stanno i prezzi arabica? Conviene hedgiare?",
                "Ci sono incendi attivi nelle regioni produttrici?",
                "Qual è l'impatto dell'ENSO sulla produzione quest'anno?",
                "Dammi un briefing rapido per il meeting di acquisti di domani",
                "Com'è la qualità attesa del raccolto 2026?",
                "Quali sono gli alert più critici da monitorare?",
                "Qual è lo stato della logistica portuale brasiliana?",
            ]
            for ex in examples:
                st.code(ex, language=None)
