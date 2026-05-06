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
from utils.prompt_loader import load_prompt

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

_DAILY_SYSTEM = load_prompt(
    "report_daily.system.txt",
    "Sei l'esperto globale delle origini del caffè di Lavazza. Rispondi solo con JSON valido.",
)

_DAILY_USER = load_prompt(
    "report_daily.user.txt",
    "Genera un report daily JSON usando questo contesto: {run_at} {final_score}",
)


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

_WEEKLY_BASE_USER = load_prompt(
    "report_weekly.base_user.txt",
    "PERIODO: settimana al {run_at}\nRISK SCORE FINALE: {final_score:.1f}/100\n{rag_section}\n",
)

# --- Acquisti ---

_ACQUISTI_SYSTEM = load_prompt(
    "report_weekly_acquisti.system.txt",
    "Sei il responsabile acquisti caffè verde di Lavazza. Rispondi solo con JSON valido.",
)

_ACQUISTI_USER = (
    _WEEKLY_BASE_USER
    + load_prompt("report_weekly_acquisti.user_tail.txt", '\n{"focus":"acquisti"}')
)

# --- Quality ---

_QUALITY_SYSTEM = load_prompt(
    "report_weekly_quality.system.txt",
    "Sei il responsabile qualità materia prima di Lavazza. Rispondi solo con JSON valido.",
)

_QUALITY_USER = (
    _WEEKLY_BASE_USER
    + load_prompt("report_weekly_quality.user_tail.txt", '\n{"focus":"quality"}')
)

# --- Management ---

_MGMT_SYSTEM = load_prompt(
    "report_weekly_management.system.txt",
    "Sei il direttore strategico di Lavazza. Rispondi solo con JSON valido.",
)

_MGMT_USER = (
    _WEEKLY_BASE_USER
    + load_prompt("report_weekly_management.user_tail.txt", '\n{"focus":"management"}')
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
