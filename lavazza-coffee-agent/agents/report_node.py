"""
report_node — genera il report narrativo finale con Claude Sonnet.

Strategie:
  - daily  : 1 chiamata Sonnet, no RAG, 300-400 parole, lingua IT
  - weekly : 3 chiamate Sonnet in sequenza (Acquisti / Quality / Management)
             con RAG su daily precedenti, ciascuna con persona e focus diversi
  - monthly: 1 Sonnet deep analysis + RAG (stub — extend per il futuro)

report_json per daily:
  { headline, executive_summary, sections:[...], correlations, risk_score,
    alerts, outlook, report_type, country, run_at }

report_json per weekly:
  { report_type:"weekly", risk_score, run_at, country, alerts,
    acquisti: { headline, focus, sections, outlook, recommendations },
    quality:  { headline, focus, sections, outlook, recommendations },
    management: { headline, executive_summary, sections, correlations, outlook } }
"""

import json
import os
import re
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

from agents.state import AgentState

load_dotenv()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _risk_label(score: float) -> str:
    if score <= 40:
        return "verde — scenario normale"
    elif score <= 70:
        return "giallo — watch"
    else:
        return "rosso — alert immediato"


def _signals_by_area(signals: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {
        "geo": [], "environment": [], "crops": [], "prices": []
    }
    for sig in signals:
        area = sig.get("area", "")
        if sig.get("source", "").endswith("_AGENT"):
            continue
        if area in result:
            result[area].append(sig)
    return result


def _score_by_area(signals: list[dict]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for sig in signals:
        if "_score" in sig and sig.get("area"):
            scores[sig["area"]] = sig["_score"]
    return scores


def _format_signals(sigs: list[dict]) -> str:
    if not sigs:
        return "  (nessun segnale disponibile)"
    icons = {"positive": "↑", "negative": "↓", "neutral": "→"}
    badges = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    lines = [
        f"  {badges.get(s.get('intensity','low'))} {icons.get(s.get('direction','neutral'),'→')} "
        f"{s.get('fact','')}  [{s.get('source','')}]"
        for s in sigs
    ]
    return "\n".join(lines)


def _base_context(state: AgentState) -> dict:
    """Dati comuni a tutti i tipi di report."""
    final_score = state.get("final_score", 0.0)
    signals = state.get("signals", [])
    sba = _signals_by_area(signals)
    scores = _score_by_area(signals)
    return {
        "final_score": final_score,
        "risk_label": _risk_label(final_score),
        "score_geo": scores.get("geo", 0.0),
        "score_env": scores.get("environment", 0.0),
        "score_crops": scores.get("crops", 0.0),
        "score_prices": scores.get("prices", 0.0),
        "signals_geo": _format_signals(sba["geo"]),
        "signals_env": _format_signals(sba["environment"]),
        "signals_crops": _format_signals(sba["crops"]),
        "signals_prices": _format_signals(sba["prices"]),
        "summary_geo": state.get("summaries", {}).get("geo", "N/D"),
        "summary_env": state.get("summaries", {}).get("environment", "N/D"),
        "summary_crops": state.get("summaries", {}).get("crops", "N/D"),
        "summary_prices": state.get("summaries", {}).get("prices", "N/D"),
        "alerts": state.get("alerts", []),
        "alerts_str": ", ".join(state.get("alerts", [])) or "nessuno",
        "alerts_json": json.dumps(state.get("alerts", []), ensure_ascii=False),
        "run_at": state.get("run_at", datetime.now(timezone.utc).isoformat()),
        "rag_context": state.get("rag_context", ""),
    }


def _call_sonnet(system: str, user: str, max_tokens: int = 3000) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw


# ---------------------------------------------------------------------------
# Daily report
# ---------------------------------------------------------------------------

_DAILY_SYSTEM = """\
Sei l'esperto globale delle origini del caffè di Lavazza.
Produci report di intelligence giornalieri: concisi, precisi, orientati alla decisione.
Tono: professionale e diretto. Cita sempre valori numerici concreti.
Lunghezza sezioni: 60-80 parole ciascuna. Executive summary: 2-3 frasi.
Lingua: italiano. Rispondi SOLO con JSON valido.
"""

_DAILY_USER = """\
DATA: {run_at}
RISK SCORE FINALE: {final_score:.1f}/100 ({risk_label})
Score per area — Geo: {score_geo:.0f} | Ambiente: {score_env:.0f} | Colture: {score_crops:.0f} | Prezzi: {score_prices:.0f}

SEGNALI GEOPOLITICI:
{signals_geo}

SEGNALI AMBIENTE:
{signals_env}

SEGNALI COLTURE:
{signals_crops}

SEGNALI PREZZI:
{signals_prices}

SINTESI:
  Geo: {summary_geo}
  Ambiente: {summary_env}
  Colture: {summary_crops}
  Prezzi: {summary_prices}

ALERT ATTIVI: {alerts_str}
{rag_section}

Produci questo JSON:
{{
  "headline": "<titolo incisivo max 80 caratteri con dato numerico chiave>",
  "executive_summary": "<2-3 frasi che catturano il quadro completo con numeri>",
  "sections": [
    {{"area": "geo",         "score": {score_geo_int}, "text": "<60-80 parole>", "signals": ["<chiave 1>", "<chiave 2>"]}},
    {{"area": "environment", "score": {score_env_int}, "text": "<60-80 parole>", "signals": ["<chiave>"]}},
    {{"area": "crops",       "score": {score_crops_int}, "text": "<60-80 parole>", "signals": ["<chiave 1>", "<chiave 2>"]}},
    {{"area": "prices",      "score": {score_prices_int}, "text": "<60-80 parole>", "signals": ["<chiave>"]}}
  ],
  "correlations": ["<correlazione cross-area 1>", "<correlazione 2>"],
  "risk_score": {final_score_r},
  "alerts": {alerts_json},
  "outlook": "<cosa monitorare nelle prossime 24-48h, con indicatori specifici>",
  "report_type": "daily",
  "country": "BR",
  "run_at": "{run_at}"
}}
"""


def _generate_daily(state: AgentState) -> dict:
    ctx = _base_context(state)
    rag_section = ""
    if ctx["rag_context"]:
        rag_section = f"\nCONTESTO STORICO (report precedenti):\n{ctx['rag_context'][:1500]}"

    user = _DAILY_USER.format(
        **ctx,
        score_geo_int=int(ctx["score_geo"]),
        score_env_int=int(ctx["score_env"]),
        score_crops_int=int(ctx["score_crops"]),
        score_prices_int=int(ctx["score_prices"]),
        final_score_r=round(ctx["final_score"], 1),
        rag_section=rag_section,
    )
    raw = _call_sonnet(_DAILY_SYSTEM, user)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Weekly report — 3 chiamate Sonnet per team
# ---------------------------------------------------------------------------

_WEEKLY_BASE_USER = """\
PERIODO: settimana al {run_at}
RISK SCORE FINALE: {final_score:.1f}/100 ({risk_label})

Score per area:
  🌍 Geopolitico:  {score_geo:.0f}/100
  🌿 Ambiente:     {score_env:.0f}/100
  🌱 Colture:      {score_crops:.0f}/100
  💰 Prezzi:       {score_prices:.0f}/100

SEGNALI GEOPOLITICI:
{signals_geo}

SEGNALI AMBIENTE:
{signals_env}

SEGNALI COLTURE:
{signals_crops}

SEGNALI PREZZI:
{signals_prices}

SINTESI PER AREA:
  Geo:      {summary_geo}
  Ambiente: {summary_env}
  Colture:  {summary_crops}
  Prezzi:   {summary_prices}

ALERT ATTIVI: {alerts_str}
{rag_section}
"""

# --- Acquisti ---

_ACQUISTI_SYSTEM = """\
Sei il responsabile acquisti caffè verde di Lavazza con 15 anni di esperienza.
Hai accesso ai dati di intelligence. Produci un briefing operativo per decidere:
- Comprare / hedgiare / attendere questa settimana?
- Quali sono i prezzi di riferimento e le finestre di opportunità?
- Quali rischi di fornitura monitorare?
Tono: operativo, numerico, orientato alla decisione. Lingua: italiano. SOLO JSON valido.
"""

_ACQUISTI_USER = (
    _WEEKLY_BASE_USER
    + """
Produci questo JSON per il team Acquisti:
{{
  "headline": "<titolo orientato ai prezzi/acquisti, max 80 caratteri>",
  "focus": "acquisti",
  "price_outlook": "<analisi dettagliata prezzi arabica, trend, livelli target>",
  "fx_outlook": "<analisi BRL/EUR, impatto sul costo in euro>",
  "supply_risk": "<rischi fornitura da Brasile, probabilità disruption>",
  "recommendations": [
    "<azione concreta 1 con razionale numerico>",
    "<azione concreta 2>",
    "<azione concreta 3>"
  ],
  "hedge_window": "<finestra temporale e livello prezzo per eventuale hedging>",
  "outlook": "<cosa monitorare questa settimana per gli acquisti>"
}}
"""
)

# --- Quality ---

_QUALITY_SYSTEM = """\
Sei il responsabile qualità materia prima di Lavazza.
Analizzi i dati di origine per valutare la qualità attesa del caffè brasiliano:
- Condizioni colturali durante la maturazione dei chicchi
- Impatto di siccità, incendi, ENSO sulla qualità sensoriale
- Rischi defect rate e contaminazioni
Tono: tecnico-qualitativo, preciso. Lingua: italiano. SOLO JSON valido.
"""

_QUALITY_USER = (
    _WEEKLY_BASE_USER
    + """
Produci questo JSON per il team Quality:
{{
  "headline": "<titolo orientato alla qualità del raccolto, max 80 caratteri>",
  "focus": "quality",
  "crop_quality_outlook": "<analisi impatto condizioni ambientali sulla qualità del chicco>",
  "regional_analysis": "<differenze qualitative tra regioni (MG, ES, BA, SP, Rondônia)>",
  "risk_factors": [
    "<fattore di rischio qualità 1 con spiegazione>",
    "<fattore 2>",
    "<fattore 3>"
  ],
  "sensory_risk": "<rischio profili aromatici, acidità, corpo — impatto sul blend Lavazza>",
  "recommendations": [
    "<azione quality 1>",
    "<azione quality 2>"
  ],
  "outlook": "<cosa monitorare questa settimana per la qualità>"
}}
"""
)

# --- Management ---

_MGMT_SYSTEM = """\
Sei il direttore strategico di Lavazza. Produci una sintesi esecutiva settimanale
del rischio Brasile per il top management: panoramica strategica, correlazioni
tra aree di rischio, impatto sul business Lavazza, decisioni da prendere.
Tono: strategico, C-level, orientato al business. Lingua: italiano. SOLO JSON valido.
"""

_MGMT_USER = (
    _WEEKLY_BASE_USER
    + """
Produci questo JSON per il Management:
{{
  "headline": "<titolo strategico con risk score, max 80 caratteri>",
  "focus": "management",
  "executive_summary": "<3-4 frasi: quadro complessivo, trend, impatto business>",
  "sections": [
    {{"area": "geo",         "score": {score_geo_int}, "text": "<50-70 parole>", "signals": ["<chiave>"]}},
    {{"area": "environment", "score": {score_env_int}, "text": "<50-70 parole>", "signals": ["<chiave>"]}},
    {{"area": "crops",       "score": {score_crops_int}, "text": "<50-70 parole>", "signals": ["<chiave>"]}},
    {{"area": "prices",      "score": {score_prices_int}, "text": "<50-70 parole>", "signals": ["<chiave>"]}}
  ],
  "correlations": ["<correlazione strategica 1>", "<correlazione 2>"],
  "business_impact": "<impatto diretto sul P&L / supply chain Lavazza>",
  "strategic_actions": [
    "<decisione strategica 1>",
    "<decisione strategica 2>"
  ],
  "risk_score": {final_score_r},
  "alerts": {alerts_json},
  "outlook": "<outlook 7-14 giorni: eventi chiave da monitorare>"
}}
"""
)


def _generate_weekly(state: AgentState) -> dict:
    """3 chiamate Sonnet: Acquisti, Quality, Management."""
    ctx = _base_context(state)
    rag_section = ""
    if ctx["rag_context"]:
        rag_section = f"\nCONTESTO STORICO (ultimi 7 daily):\n{ctx['rag_context'][:2000]}"

    int_ctx = {
        **ctx,
        "rag_section": rag_section,
        "score_geo_int": int(ctx["score_geo"]),
        "score_env_int": int(ctx["score_env"]),
        "score_crops_int": int(ctx["score_crops"]),
        "score_prices_int": int(ctx["score_prices"]),
        "final_score_r": round(ctx["final_score"], 1),
    }

    # --- Acquisti ---
    try:
        acquisti_raw = _call_sonnet(_ACQUISTI_SYSTEM, _ACQUISTI_USER.format(**int_ctx), max_tokens=3500)
        acquisti = json.loads(acquisti_raw)
    except Exception as e:
        print(f"[report_node] Errore weekly acquisti: {e}")
        acquisti = {"headline": "Dati acquisti non disponibili", "focus": "acquisti"}

    # --- Quality ---
    try:
        quality_raw = _call_sonnet(_QUALITY_SYSTEM, _QUALITY_USER.format(**int_ctx), max_tokens=3500)
        quality = json.loads(quality_raw)
    except Exception as e:
        print(f"[report_node] Errore weekly quality: {e}")
        quality = {"headline": "Dati quality non disponibili", "focus": "quality"}

    # --- Management ---
    try:
        mgmt_raw = _call_sonnet(_MGMT_SYSTEM, _MGMT_USER.format(**int_ctx), max_tokens=3500)
        mgmt = json.loads(mgmt_raw)
    except Exception as e:
        print(f"[report_node] Errore weekly management: {e}")
        mgmt = {"headline": "Dati management non disponibili", "focus": "management"}

    return {
        "report_type": "weekly",
        "risk_score": round(ctx["final_score"], 1),
        "run_at": ctx["run_at"],
        "country": state.get("country", "BR"),
        "alerts": ctx["alerts"],
        "acquisti": acquisti,
        "quality": quality,
        "management": mgmt,
    }


# ---------------------------------------------------------------------------
# Nodo LangGraph principale
# ---------------------------------------------------------------------------

def report_node(state: AgentState) -> dict:
    """
    Nodo LangGraph: genera il report narrativo finale.

    - daily:   1 chiamata Sonnet → report_json flat
    - weekly:  3 chiamate Sonnet → report_json con sotto-chiavi per team
    - monthly: alias weekly per ora (extend in futuro con PDF WeasyPrint)
    """
    report_type = state.get("report_type", "daily")

    try:
        if report_type == "daily":
            report_json = _generate_daily(state)
        elif report_type in ("weekly", "monthly"):
            report_json = _generate_weekly(state)
            report_json["report_type"] = report_type
        else:
            report_json = _generate_daily(state)
            report_json["report_type"] = report_type

    except (anthropic.APIError, json.JSONDecodeError, KeyError) as e:
        print(f"[report_node] Errore generazione report: {e}")
        final_score = state.get("final_score", 0.0)
        report_json = {
            "headline": "Report non disponibile — errore generazione",
            "executive_summary": f"Errore: {e}",
            "sections": [],
            "correlations": [],
            "risk_score": final_score,
            "alerts": state.get("alerts", []),
            "outlook": "Verificare i log.",
            "report_type": report_type,
            "country": state.get("country", "BR"),
            "run_at": state.get("run_at", ""),
        }

    return {"report_json": report_json}
