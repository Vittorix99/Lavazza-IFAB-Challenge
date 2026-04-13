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


_INTENSITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_INTENSITY_COLOR = {
    "high":   ("#f8d7da", "#721c24", "🔴"),
    "medium": ("#fff3cd", "#856404", "🟡"),
    "low":    ("#d4edda", "#155724", "🟢"),
}
_DIRECTION_LABEL = {"positive": "↑ Positivo", "negative": "↓ Negativo", "neutral": "→ Neutro"}


def _render_signals_detail(signals: list[dict], area_filter: list[str]) -> None:
    """
    Mostra i segnali organizzati per area, ordinati per intensità.
    Layout leggibile: ogni segnale ha il fatto in primo piano e la spiegazione
    come dettaglio secondario.
    """
    # Filtra solo segnali delle aree selezionate, esclude segnali interni _AGENT
    visible = [
        s for s in signals
        if s.get("area") in area_filter
        and not s.get("source", "").endswith("_AGENT")
        and s.get("fact", "").strip()
    ]

    if not visible:
        st.info("Nessun segnale disponibile per le aree selezionate.")
        return

    # Raggruppa per area e mantieni solo le aree selezionate nell'ordine definito
    by_area: dict[str, list[dict]] = {}
    for area in area_filter:
        sigs = [s for s in visible if s.get("area") == area]
        # Ordina: prima per intensità (high → medium → low), poi per direction (neg first)
        sigs.sort(key=lambda s: (
            _INTENSITY_ORDER.get(s.get("intensity", "low"), 2),
            0 if s.get("direction") == "negative" else 1,
        ))
        if sigs:
            by_area[area] = sigs

    if not by_area:
        st.info("Nessun segnale disponibile.")
        return

    # Tabs per area (max 4)
    area_labels_present = [
        (area, AREA_LABELS.get(area, area))
        for area in area_filter
        if area in by_area
    ]
    if not area_labels_present:
        return

    tab_labels = [f"{label} ({len(by_area[area])})" for area, label in area_labels_present]
    tabs = st.tabs(tab_labels)

    for tab, (area, label) in zip(tabs, area_labels_present):
        with tab:
            area_sigs = by_area[area]
            n_neg = sum(1 for s in area_sigs if s.get("direction") == "negative")
            n_pos = sum(1 for s in area_sigs if s.get("direction") == "positive")
            n_high = sum(1 for s in area_sigs if s.get("intensity") == "high")

            # Sommario area in una riga
            parts = []
            if n_high:
                parts.append(f"🔴 {n_high} alta priorità")
            if n_neg:
                parts.append(f"↓ {n_neg} negativi")
            if n_pos:
                parts.append(f"↑ {n_pos} positivi")
            if parts:
                st.caption(" · ".join(parts))

            # Nota tensioni apparentemente contraddittorie
            if n_pos > 0 and n_neg > 0:
                st.info(
                    "💡 **Tensioni apparentemente contraddittorie:** la presenza di segnali positivi e negativi "
                    "nella stessa area è spesso economicamente coerente. Esempi comuni: "
                    "produzione in calo ma scorte in aumento (consumo calato ancora di più); "
                    "volume esportazioni in salita ma valore in calo (prezzi scesi — i compratori "
                    "acquistano di più prima di ulteriori riduzioni). "
                    "Queste tensioni indicano cambi strutturali nel mercato, non errori nei dati."
                )

            # Segnali come cards leggibili
            for sig in area_sigs:
                intensity = sig.get("intensity", "low")
                direction = sig.get("direction", "neutral")
                fact = sig.get("fact", "").strip()
                source = sig.get("source", "").replace("_", " ")
                explanation = sig.get("explanation", "").strip()

                bg, fg, dot = _INTENSITY_COLOR.get(intensity, _INTENSITY_COLOR["low"])
                dir_label = _DIRECTION_LABEL.get(direction, "→")

                # Card principale con fatto
                st.markdown(
                    f'<div style="background:{bg};border-radius:8px;padding:10px 14px;'
                    f'margin:4px 0;border-left:4px solid {fg};">'
                    f'<span style="font-size:0.78rem;color:{fg};font-weight:600;'
                    f'text-transform:uppercase;letter-spacing:0.04em;">'
                    f'{dot} {dir_label}</span><br>'
                    f'<span style="font-size:0.97rem;font-weight:600;color:#1a1a1a;">'
                    f'{fact}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                # Dettaglio fonte + spiegazione sotto la card
                if explanation or source:
                    detail_parts = []
                    if source:
                        detail_parts.append(f"**Fonte:** {source}")
                    if explanation:
                        detail_parts.append(explanation)
                    st.caption("  ·  ".join(detail_parts))


def _render_freshness_table(data_freshness: dict) -> None:
    if not data_freshness:
        st.caption("Nessun dato di freshness disponibile.")
        return
    rows = [
        {
            "Fonte": src,
            "Cadenza": info.get("cadenza") or "unknown",
            "Giorni fa": info["days_old"] if info.get("days_old") is not None else "N/A",
            "Status": "✅ Fresh" if info.get("is_fresh") else "⚠️ Stale",
        }
        for src, info in data_freshness.items()
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Chart section renderer
# ---------------------------------------------------------------------------

def _render_charts_section(
    charts_metadata: list[dict],
    country: str = "BR",
    use_api: bool = False,
    section_key: str = "report",
) -> None:
    """
    Mostra i grafici interattivi organizzati per area tematica.
    Usa gli stessi renderer della Dashboard Visiva (MongoDB-first, API fallback, simulated).
    section_key evita conflitti di ID Streamlit con la Dashboard Visiva.
    """
    from dashboard.charts import render_dashboard_tab, DASHBOARD_TABS

    tab_labels = [label for label, _ in DASHBOARD_TABS]
    tab_keys = [key for _, key in DASHBOARD_TABS]
    inner_tabs = st.tabs(tab_labels)

    for inner_tab, tab_key in zip(inner_tabs, tab_keys):
        with inner_tab:
            render_dashboard_tab(
                tab_key,
                country=country,
                use_api=use_api,
                key_prefix=f"{section_key}_{tab_key}",
            )


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

    sub_analisi, sub_grafici = st.tabs(["📋 Analisi", "📊 Grafici"])

    with sub_analisi:
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

        with st.expander("Segnali dettaglio per area", expanded=False):
            st.caption("Segnali raccolti dai 4 sub-agenti · ordinati per priorità · tab per area")
            _render_signals_detail(signals, list(AREA_LABELS.keys()))

        with st.expander("Data Freshness", expanded=False):
            _render_freshness_table(data_freshness)

        with st.expander("Raw JSON", expanded=False):
            st.json(report_json)

    with sub_grafici:
        _render_charts_section(
            charts_metadata=result.get("charts", []),
            country=result.get("country", "BR"),
            use_api=use_api_fallback,
            section_key="daily",
        )


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

    sub_analisi_w, sub_grafici_w = st.tabs(["📋 Analisi", "📊 Grafici"])

    with sub_analisi_w:
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

    with sub_grafici_w:
        _render_charts_section(
            charts_metadata=result.get("charts", []),
            country=result.get("country", "BR"),
            use_api=use_api_fallback,
            section_key="weekly",
        )


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


def _format_doc_snippet(doc: dict, max_summary: int = 350) -> str:
    """
    Converte un documento MongoDB in un testo leggibile da Claude.
    Schema-agnostico: funziona con qualsiasi sorgente presente o futura.
    Estrae: source, collected_at, summary_en, signals, movement_label
    + tutti i campi numerici scalari rilevanti (esclude array grandi e ObjectId).
    """
    src = doc.get("source", "?")
    collected = str(doc.get("collected_at", ""))[:10]
    lines = [f"[{src}] — {collected}"]

    # Summary testuale
    if summary := (doc.get("summary_en") or doc.get("summary") or ""):
        lines.append(summary[:max_summary])

    # Etichetta movimento (es. "supply_tightening", "bullish", ...)
    if ml := doc.get("movement_label"):
        lines.append(f"Trend: {ml}")

    # Segnali (lista di stringhe o lista di dict)
    raw_sigs = doc.get("signals", [])
    if raw_sigs:
        sig_texts = []
        for s in raw_sigs[:6]:
            if isinstance(s, str):
                sig_texts.append(s)
            elif isinstance(s, dict):
                fact = s.get("fact") or s.get("text") or s.get("signal") or ""
                if fact:
                    sig_texts.append(fact)
        if sig_texts:
            lines.append("Segnali: " + " · ".join(sig_texts))

    # Campi numerici scalari rilevanti (top 8 per valore informativo)
    _SKIP = {
        "_id", "source", "country", "macroarea", "collected_at", "collected_period",
        "summary_en", "summary", "movement_label", "signals", "embed_text",
        "pdf_excerpt", "report_text_excerpt", "source_url", "index_url",
        "pdf_url", "table_url", "source_format", "source_descriptor_url",
        "_chart_fields", "rule_based_signals", "fallback_summary_en",
        "rule_based_movement_label",
    }
    numeric_lines = []
    for k, v in doc.items():
        if k in _SKIP:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            numeric_lines.append(f"{k}: {v}")
        elif isinstance(v, str) and len(v) < 120 and k not in _SKIP:
            numeric_lines.append(f"{k}: {v}")
        elif isinstance(v, dict) and len(v) <= 8:
            # dizionari piccoli (es. latest_month, national_snapshot)
            inner = ", ".join(
                f"{ik}={iv}" for ik, iv in v.items()
                if isinstance(iv, (int, float, str)) and not isinstance(iv, bool)
            )
            if inner:
                numeric_lines.append(f"{k}: {{{inner}}}")
    if numeric_lines:
        lines.append("\n".join(numeric_lines[:12]))

    return "\n".join(lines)


def _build_chat_context(question: str) -> tuple[str, dict]:
    """
    Costruisce il contesto per il chatbot combinando:
    1. Ultimo agent_run (report + score)
    2. Ricerca semantica Qdrant (se OpenAI disponibile)
    3. Documento più recente per OGNI sorgente in MongoDB — schema-agnostico,
       include automaticamente qualsiasi nuova fonte aggiunta via n8n.
    """
    from utils.db import get_db
    from utils.qdrant import collection_exists, search

    parts: list[str] = []
    debug: dict = {"agent_run": None, "qdrant": {}, "mongodb": {}}

    db = get_db()

    # ── 1. Ultimo agent run ────────────────────────────────────────────────
    last_run = db["agent_runs"].find_one({}, sort=[("saved_at", -1)])
    if last_run:
        rj = last_run.get("report_json", {})
        run_date = last_run.get("run_at", "")[:10]
        score = last_run.get("final_score", 0)
        alerts = last_run.get("alerts", [])
        sections = rj.get("sections", [])
        sec_text = "\n".join(
            f"  {s.get('area','')}: {s.get('score',0)}/100 — {s.get('text','')[:200]}"
            for s in sections
        )
        parts.append(
            f"=== ULTIMO REPORT AGENTE ({run_date}, tipo={last_run.get('report_type','?')}) ===\n"
            f"Risk Score: {score:.1f}/100\n"
            f"Headline: {rj.get('headline', '')}\n"
            f"Executive Summary: {rj.get('executive_summary', rj.get('management', {}).get('executive_summary', ''))[:400]}\n"
            f"Alert: {', '.join(alerts) or 'nessuno'}\n"
            f"Aree:\n{sec_text}"
        )
        debug["agent_run"] = {"date": run_date, "score": score, "type": last_run.get("report_type", "?")}

    # ── 2. Ricerca semantica Qdrant ────────────────────────────────────────
    embedding = _get_embedding(question)
    if embedding:
        for coll in ["geo_texts", "crops_texts", "reports_archive"]:
            if not collection_exists(coll):
                debug["qdrant"][coll] = "non trovata"
                continue
            hits = search(collection=coll, query_vector=embedding, limit=3)
            debug["qdrant"][coll] = f"{len(hits)} hit"
            texts = [
                (h.get("text") or h.get("content") or h.get("summary_en")
                 or h.get("embed_text") or h.get("executive_summary") or "")[:400]
                for h in hits
            ]
            texts = [t for t in texts if t]
            if texts:
                parts.append(f"=== QDRANT {coll.upper()} ===\n" + "\n---\n".join(texts))
    else:
        debug["qdrant"]["_embedding"] = "errore"

    # ── 3. MongoDB — un doc per sorgente, tutte le collection raw_* ────────
    # Schema-agnostico: legge le sorgenti distinte dalla collection,
    # recupera l'ultimo documento per ognuna, la formatta genericamente.
    # Qualsiasi nuova sorgente inserita via n8n viene inclusa automaticamente.
    RAW_COLLECTIONS = ["raw_geo", "raw_prices", "raw_crops", "raw_environment"]

    for col_name in RAW_COLLECTIONS:
        try:
            # Trova tutte le sorgenti distinte per il Brasile
            sources = db[col_name].distinct("source", {"country": "BR"})
        except Exception:
            sources = []

        col_snippets = []
        for src in sorted(sources):
            try:
                doc = db[col_name].find_one(
                    {"source": src, "country": "BR"},
                    sort=[("collected_at", -1)],
                )
                if doc:
                    col_snippets.append(_format_doc_snippet(doc))
            except Exception:
                pass

        debug["mongodb"][col_name] = f"{len(col_snippets)} sorgenti"
        if col_snippets:
            parts.append(
                f"=== {col_name.upper().replace('_', ' ')} ===\n"
                + "\n\n".join(col_snippets)
            )

    context = "\n\n".join(parts) if parts else "Nessun dato di contesto disponibile."
    debug["total_chars"] = len(context)
    debug["sections_found"] = len(parts)
    return context, debug


def _stream_chat_response(question: str, context: str, history: list[dict]):
    """Generator che streamma la risposta di Claude Sonnet."""
    system = """\
Sei l'esperto globale delle origini del caffè di Lavazza.
Hai accesso in tempo reale a tutti i dati di intelligence sul Brasile: il contesto che ricevi
contiene l'ultimo documento per ogni sorgente attiva nel sistema (raw_geo, raw_prices,
raw_crops, raw_environment). Le sorgenti possono includere: GDELT, WTO News, Port Congestion,
CONAB, USDA FAS, IBGE SIDRA, Comex Stat, FAOSTAT, World Bank Pink Sheet, BCB PTAX, ECB,
NASA FIRMS, NOAA ENSO — e qualsiasi nuova sorgente aggiunta in futuro.

Regole:
- Rispondi SEMPRE in italiano.
- Cita numeri specifici e la fonte (es. "BCB PTAX: 5.42 BRL/USD al 2026-04-10").
- Usa i dati del contesto — non inventare cifre.
- Sii conciso (max 200 parole) a meno che l'utente chieda un approfondimento.
- Se una domanda riguarda una fonte non presente nel contesto, dillo esplicitamente.
- Se la domanda è fuori dal dominio caffè/Brasile/supply chain, reindirizza educatamente.
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
    chart_source = st.radio(
        "Sorgente dati grafici",
        options=["MongoDB", "API Diretta"],
        index=0,
        help="MongoDB: usa i dati già raccolti da n8n (veloce, offline). API Diretta: richiama le fonti esterne in tempo reale.",
    )
    use_api_fallback = (chart_source == "API Diretta")
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
tab_daily, tab_weekly, tab_chat, tab_dashboard = st.tabs([
    "Daily Report",
    "Weekly Reports",
    "Chat",
    "Dashboard Visiva",
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

# ============================================================================
# TAB 4 — DASHBOARD VISIVA
# ============================================================================
with tab_dashboard:
    from dashboard.charts import render_dashboard_tab, DASHBOARD_TABS

    st.markdown("## Dashboard Visiva — Brasile")
    st.markdown(
        "Visualizzazioni interattive dai dati più recenti. "
        "Disponibile sempre, indipendentemente dall'esecuzione del grafo LangGraph."
    )
    st.caption(
        "Sorgente: " + ("**API Diretta**" if use_api_fallback else "**MongoDB** (dati n8n)")
        + " · Modifica il toggle nella sidebar per cambiare sorgente."
    )
    st.divider()

    dash_tab_labels = [label for label, _ in DASHBOARD_TABS]
    dash_tab_keys   = [key   for _, key   in DASHBOARD_TABS]
    dash_tab_widgets = st.tabs(dash_tab_labels)

    for dash_tab_widget, tab_key in zip(dash_tab_widgets, dash_tab_keys):
        with dash_tab_widget:
            render_dashboard_tab(tab_key, country="BR", use_api=use_api_fallback,
                                 key_prefix=f"dash_{tab_key}")
