from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st


RISK_COLORS = {
    "low": "#3E7B58",
    "medium": "#C6842D",
    "high": "#B23A2E",
}

STATE_COORDS = {
    "Minas Gerais": ("MG", -18.5, -44.5),
    "Espirito Santo": ("ES", -19.5, -40.3),
    "Sao Paulo": ("SP", -22.0, -47.5),
    "Bahia": ("BA", -12.5, -41.7),
    "Rondonia": ("RO", -11.0, -62.0),
    "Parana": ("PR", -24.5, -51.5),
    "Goias": ("GO", -16.0, -49.5),
    "Mato Grosso": ("MT", -13.0, -56.0),
}

IBGE_UF_GEOJSON_URL = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?"
    "intrarregiao=UF&formato=application/vnd.geo+json"
)
IBGE_UF_LOOKUP_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/estados"


@dataclass
class Snapshot:
    date: pd.Timestamp
    prices: pd.DataFrame
    climate: pd.DataFrame
    yields: pd.DataFrame
    states_history: pd.DataFrame
    states: pd.DataFrame
    ports_history: pd.DataFrame
    ports: pd.DataFrame
    merged_monthly: pd.DataFrame
    quality_monthly: pd.DataFrame
    analytics: dict[str, Any]
    kpis: dict[str, float]


def _clip(value: float, lo: float, hi: float) -> float:
    return float(np.clip(value, lo, hi))


def _coerce_dates(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
    out = out.dropna(subset=[date_col]).sort_values(date_col)
    return out


def _get_reference_date(bundle: dict[str, Any]) -> pd.Timestamp:
    candidates: list[pd.Timestamp] = []
    for key in ("prices", "climate", "yields", "states", "ports"):
        df = bundle.get(key, pd.DataFrame())
        if isinstance(df, pd.DataFrame) and not df.empty and "date" in df.columns:
            dt = pd.to_datetime(df["date"], errors="coerce").dropna()
            if not dt.empty:
                candidates.append(dt.max())
    if not candidates:
        return pd.Timestamp.utcnow().normalize()
    return max(candidates)


def _safe_latest(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    return df.sort_values("date").iloc[-1]


def _fit_beta(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    mask = x.notna() & y.notna()
    if mask.sum() < 5:
        return 0.0, 0.0
    beta, alpha = np.polyfit(x[mask], y[mask], 1)
    return float(beta), float(alpha)


def _dict_to_rows(data: dict[str, Any], prefix: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            rows.extend(_dict_to_rows(value, full_key))
        else:
            rows.append({"key": full_key, "value": value})
    return rows


def _humanize_age(fetched_at: Any) -> tuple[str, float]:
    ts = pd.to_datetime(fetched_at, utc=True, errors="coerce")
    if pd.isna(ts):
        return "unknown", 9999.0
    now = pd.Timestamp.utcnow()
    age = now - ts
    total_hours = age.total_seconds() / 3600
    if total_hours < 1:
        mins = max(1, int(age.total_seconds() // 60))
        return f"{mins}m ago", total_hours
    if total_hours < 24:
        return f"{int(total_hours)}h ago", total_hours
    days = int(total_hours // 24)
    return f"{days}d ago", total_hours


def _format_driver_name(name: str) -> str:
    mapping = {
        "rainfall_deficit": "Rainfall deficit",
        "wildfire_lag2": "Wildfire pressure (lag 2 months)",
        "oni": "ENSO ONI",
        "temp_anomaly": "Temperature anomaly",
    }
    return mapping.get(name, name.replace("_", " ").title())


def _top_drivers(analytics: dict[str, Any], top_n: int = 2) -> list[tuple[str, float]]:
    drivers = analytics.get("yield_drivers", {})
    if not isinstance(drivers, dict) or not drivers:
        return []
    items = [(str(name), float(value)) for name, value in drivers.items()]
    items.sort(key=lambda kv: abs(kv[1]), reverse=True)
    return items[:top_n]


@st.cache_data(ttl=60 * 60 * 24)
def _load_ibge_geojson() -> dict[str, Any]:
    response = requests.get(IBGE_UF_GEOJSON_URL, timeout=20)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=60 * 60 * 24)
def _load_ibge_state_lookup() -> dict[str, str]:
    response = requests.get(IBGE_UF_LOOKUP_URL, timeout=20)
    response.raise_for_status()
    payload = response.json()
    out: dict[str, str] = {}
    for item in payload:
        sigla = str(item.get("sigla", "")).upper()
        code = str(item.get("id", ""))
        if sigla and code:
            out[sigla] = code
    return out


def _load_ibge_assets() -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    try:
        geo = _load_ibge_geojson()
        lookup = _load_ibge_state_lookup()
        return geo, lookup
    except Exception:
        return None, None


def _build_monthly_merge(
    prices: pd.DataFrame,
    climate: pd.DataFrame,
    yields: pd.DataFrame,
    ports_history: pd.DataFrame,
) -> pd.DataFrame:
    px_df = prices.copy()
    cl_df = climate.copy()
    yl_df = yields.copy()
    pt_df = ports_history.copy()

    px_df["month"] = px_df["date"].dt.to_period("M").dt.to_timestamp()
    cl_df["month"] = cl_df["date"].dt.to_period("M").dt.to_timestamp()
    yl_df["month"] = yl_df["date"].dt.to_period("M").dt.to_timestamp()

    px_monthly = (
        px_df.groupby("month", as_index=False)
        .agg(
            arabica_eur_kg=("arabica_eur_kg", "mean"),
            robusta_eur_kg=("robusta_eur_kg", "mean"),
            spread=("spread", "mean"),
            fx_brl_per_eur=("fx_brl_per_eur", "mean"),
        )
        .sort_values("month")
    )
    cl_monthly = (
        cl_df.groupby("month", as_index=False)
        .agg(
            wildfire_count=("wildfire_count", "sum"),
            rainfall_deficit_pct=("rainfall_deficit_pct", "mean"),
            oni=("oni", "mean"),
            temperature_anomaly_c=("temperature_anomaly_c", "mean"),
        )
        .sort_values("month")
    )

    yield_aggs: dict[str, tuple[str, str]] = {}
    for col in [
        "yield_index",
        "production_index",
        "arabica_production_index",
        "canephora_production_index",
    ]:
        if col in yl_df.columns:
            yield_aggs[col] = (col, "mean")
    if yield_aggs:
        yl_monthly = yl_df.groupby("month", as_index=False).agg(**yield_aggs).sort_values("month")
    else:
        yl_monthly = pd.DataFrame({"month": px_monthly["month"].copy()})

    if not pt_df.empty and "congestion_index" in pt_df.columns:
        pt_df["month"] = pt_df["date"].dt.to_period("M").dt.to_timestamp()
        port_monthly = (
            pt_df.groupby("month", as_index=False)
            .agg(
                congestion_index=("congestion_index", "mean"),
                eta_delay_days=("eta_delay_days", "mean"),
            )
            .sort_values("month")
        )
    else:
        port_monthly = pd.DataFrame(columns=["month", "congestion_index", "eta_delay_days"])

    merged = px_monthly.merge(cl_monthly, on="month", how="outer")
    merged = merged.merge(yl_monthly, on="month", how="outer")
    merged = merged.merge(port_monthly, on="month", how="left")

    merged = merged.sort_values("month").reset_index(drop=True)
    for col in [
        "arabica_eur_kg",
        "robusta_eur_kg",
        "spread",
        "fx_brl_per_eur",
        "wildfire_count",
        "rainfall_deficit_pct",
        "oni",
        "temperature_anomaly_c",
        "yield_index",
        "production_index",
        "arabica_production_index",
        "canephora_production_index",
        "congestion_index",
        "eta_delay_days",
    ]:
        if col in merged.columns:
            merged[col] = merged[col].interpolate(limit_direction="both")
    return merged.dropna(subset=["month"])


def _quality_series(states: pd.DataFrame, climate: pd.DataFrame) -> pd.DataFrame:
    st_df = states.copy()
    cl_df = climate.copy()
    st_df["month"] = st_df["date"].dt.to_period("M").dt.to_timestamp()
    cl_df["month"] = cl_df["date"].dt.to_period("M").dt.to_timestamp()

    st_monthly = (
        st_df.groupby("month", as_index=False)
        .agg(
            quality_score=("quality_score", "mean"),
            state_fire_pressure=("wildfire_pressure", "mean"),
            state_rainfall_deficit=("rainfall_deficit_pct", "mean"),
        )
        .sort_values("month")
    )
    cl_monthly = (
        cl_df.groupby("month", as_index=False)
        .agg(
            wildfire_count=("wildfire_count", "sum"),
            rainfall_deficit_pct=("rainfall_deficit_pct", "mean"),
            temperature_anomaly_c=("temperature_anomaly_c", "mean"),
        )
        .sort_values("month")
    )
    out = st_monthly.merge(cl_monthly, on="month", how="left").fillna(0.0)
    wildfire_scaled = (
        out["wildfire_count"] / max(float(out["wildfire_count"].quantile(0.9)), 1.0)
    ) * 100.0
    out["quality_risk_index"] = (
        0.35 * wildfire_scaled
        + 0.40 * out["state_rainfall_deficit"].clip(lower=0)
        + 8.0 * out["temperature_anomaly_c"].clip(lower=0)
    ).clip(0, 100)
    out["expected_cup_score"] = (
        out["quality_score"]
        - 0.06 * out["quality_risk_index"]
        + 0.01 * out["state_rainfall_deficit"]
    ).clip(75, 87)
    return out


def _simple_chain_analytics(data: pd.DataFrame, quality: pd.DataFrame) -> dict[str, Any]:
    work = data.copy()
    work["yield_change_pct"] = work["yield_index"].pct_change() * 100
    work["arabica_change_pct"] = work["arabica_eur_kg"].pct_change() * 100
    work["wildfire_lag2"] = work["wildfire_count"].shift(2)

    fire_corr = float(
        work[["wildfire_lag2", "yield_change_pct"]].corr().iloc[0, 1]
    ) if work["wildfire_lag2"].notna().sum() > 4 else 0.0

    rain_beta, _ = _fit_beta(work["rainfall_deficit_pct"], work["yield_change_pct"])
    fire_beta, _ = _fit_beta(work["wildfire_lag2"], work["yield_change_pct"])
    oni_beta, _ = _fit_beta(work["oni"], work["yield_change_pct"])
    temp_beta, _ = _fit_beta(work["temperature_anomaly_c"], work["yield_change_pct"])
    price_beta, _ = _fit_beta(work["yield_change_pct"].shift(1), work["arabica_change_pct"])

    latest_deficit = float(work["rainfall_deficit_pct"].iloc[-1]) if not work.empty else 0.0
    predicted_yield_change = rain_beta * latest_deficit
    predicted_price_change = price_beta * predicted_yield_change

    quality_now = float(quality["quality_risk_index"].iloc[-1]) if not quality.empty else 0.0
    confidence = _clip(abs(fire_corr), 0.15, 0.95)

    drivers = {
        "rainfall_deficit": float(rain_beta),
        "wildfire_lag2": float(fire_beta),
        "oni": float(oni_beta),
        "temp_anomaly": float(temp_beta),
    }
    drivers = dict(sorted(drivers.items(), key=lambda kv: abs(kv[1]), reverse=True))

    return {
        "fit_method": "fallback_simple",
        "fire_to_yield_corr": fire_corr,
        "predicted_yield_change_pct": float(predicted_yield_change),
        "predicted_price_change_pct": float(predicted_price_change),
        "quality_risk_now": quality_now,
        "model_confidence": confidence,
        "yield_drivers": drivers,
    }


def _compute_analytics(merged: pd.DataFrame, quality: pd.DataFrame) -> dict[str, Any]:
    data = merged.copy().sort_values("month")
    if data.empty:
        return {
            "fit_method": "empty",
            "fire_to_yield_corr": 0.0,
            "predicted_yield_change_pct": 0.0,
            "predicted_price_change_pct": 0.0,
            "quality_risk_now": 0.0,
            "model_confidence": 0.15,
            "yield_drivers": {
                "rainfall_deficit": 0.0,
                "wildfire_lag2": 0.0,
                "oni": 0.0,
                "temp_anomaly": 0.0,
            },
        }

    data["wildfire_lag2"] = data["wildfire_count"].shift(2)
    data["yield_index_lag1"] = data["yield_index"].shift(1)

    fit1_cols = [
        "rainfall_deficit_pct",
        "wildfire_lag2",
        "oni",
        "temperature_anomaly_c",
        "yield_index",
    ]
    fit2_cols = [
        "yield_index_lag1",
        "fx_brl_per_eur",
        "congestion_index",
        "arabica_eur_kg",
    ]

    fit1 = data[fit1_cols].dropna()
    fit2 = data[fit2_cols].dropna()
    if len(fit1) < 8 or len(fit2) < 8:
        return _simple_chain_analytics(data, quality)

    x1 = fit1[
        ["rainfall_deficit_pct", "wildfire_lag2", "oni", "temperature_anomaly_c"]
    ].to_numpy(dtype=float)
    y1 = fit1["yield_index"].to_numpy(dtype=float)
    a1 = np.column_stack([np.ones(len(x1)), x1])
    coef1, *_ = np.linalg.lstsq(a1, y1, rcond=None)
    pred1 = a1 @ coef1
    sst1 = float(((y1 - y1.mean()) ** 2).sum())
    sse1 = float(((y1 - pred1) ** 2).sum())
    r2_1 = 0.0 if sst1 <= 0 else max(0.0, 1 - (sse1 / sst1))

    beta_rain = float(coef1[1])
    beta_fire = float(coef1[2])
    beta_oni = float(coef1[3])
    beta_temp = float(coef1[4])

    latest1 = data.iloc[-1][
        ["rainfall_deficit_pct", "wildfire_lag2", "oni", "temperature_anomaly_c"]
    ].copy()
    means1 = fit1[
        ["rainfall_deficit_pct", "wildfire_lag2", "oni", "temperature_anomaly_c"]
    ].mean()
    latest1 = latest1.fillna(means1)
    pred_yield_level = float(
        coef1[0]
        + beta_rain * latest1["rainfall_deficit_pct"]
        + beta_fire * latest1["wildfire_lag2"]
        + beta_oni * latest1["oni"]
        + beta_temp * latest1["temperature_anomaly_c"]
    )
    latest_yield_level = float(data["yield_index"].iloc[-1])
    predicted_yield_change_pct = (
        ((pred_yield_level - latest_yield_level) / latest_yield_level) * 100
        if latest_yield_level != 0
        else 0.0
    )

    x2 = fit2[["yield_index_lag1", "fx_brl_per_eur", "congestion_index"]].to_numpy(dtype=float)
    y2 = fit2["arabica_eur_kg"].to_numpy(dtype=float)
    a2 = np.column_stack([np.ones(len(x2)), x2])
    coef2, *_ = np.linalg.lstsq(a2, y2, rcond=None)
    pred2 = a2 @ coef2
    sst2 = float(((y2 - y2.mean()) ** 2).sum())
    sse2 = float(((y2 - pred2) ** 2).sum())
    r2_2 = 0.0 if sst2 <= 0 else max(0.0, 1 - (sse2 / sst2))

    latest2 = data.iloc[-1][["yield_index_lag1", "fx_brl_per_eur", "congestion_index"]].copy()
    means2 = fit2[["yield_index_lag1", "fx_brl_per_eur", "congestion_index"]].mean()
    latest2 = latest2.fillna(means2)
    pred_price_level = float(
        coef2[0]
        + float(coef2[1]) * latest2["yield_index_lag1"]
        + float(coef2[2]) * latest2["fx_brl_per_eur"]
        + float(coef2[3]) * latest2["congestion_index"]
    )
    latest_price_level = float(data["arabica_eur_kg"].iloc[-1])
    predicted_price_change_pct = (
        ((pred_price_level - latest_price_level) / latest_price_level) * 100
        if latest_price_level != 0
        else 0.0
    )

    fire_corr = float(
        data[["wildfire_lag2", "yield_index"]].corr().iloc[0, 1]
    ) if data["wildfire_lag2"].notna().sum() > 4 else 0.0

    quality_now = float(quality["quality_risk_index"].iloc[-1]) if not quality.empty else 0.0
    confidence = _clip((r2_1 + r2_2) / 2, 0.15, 0.95)

    drivers = {
        "rainfall_deficit": beta_rain,
        "wildfire_lag2": beta_fire,
        "oni": beta_oni,
        "temp_anomaly": beta_temp,
    }
    drivers = dict(sorted(drivers.items(), key=lambda kv: abs(kv[1]), reverse=True))

    return {
        "fit_method": "multivariate_ols",
        "fire_to_yield_corr": fire_corr,
        "predicted_yield_change_pct": float(predicted_yield_change_pct),
        "predicted_price_change_pct": float(predicted_price_change_pct),
        "quality_risk_now": quality_now,
        "model_confidence": confidence,
        "yield_drivers": drivers,
    }


def _slice_snapshot(bundle: dict[str, Any], snapshot_date: pd.Timestamp) -> Snapshot:
    prices = _coerce_dates(bundle.get("prices", pd.DataFrame()))
    climate = _coerce_dates(bundle.get("climate", pd.DataFrame()))
    yields = _coerce_dates(bundle.get("yields", pd.DataFrame()))
    states = _coerce_dates(bundle.get("states", pd.DataFrame()))
    ports = _coerce_dates(bundle.get("ports", pd.DataFrame()))

    prices = prices[prices["date"] <= snapshot_date].copy() if not prices.empty else prices
    climate = climate[climate["date"] <= snapshot_date].copy() if not climate.empty else climate
    yields = yields[yields["date"] <= snapshot_date].copy() if not yields.empty else yields
    states = states[states["date"] <= snapshot_date].copy() if not states.empty else states
    ports = ports[ports["date"] <= snapshot_date].copy() if not ports.empty else ports

    if prices.empty:
        prices = _coerce_dates(bundle.get("prices", pd.DataFrame()))
    if climate.empty:
        climate = _coerce_dates(bundle.get("climate", pd.DataFrame()))
    if yields.empty:
        yields = _coerce_dates(bundle.get("yields", pd.DataFrame()))
    if states.empty:
        states = _coerce_dates(bundle.get("states", pd.DataFrame()))
    if ports.empty:
        ports = _coerce_dates(bundle.get("ports", pd.DataFrame()))

    state_latest = (
        states.sort_values("date").groupby("state", as_index=False).tail(1)
        if not states.empty
        else states
    )
    port_latest = (
        ports.sort_values("date").groupby("port_name", as_index=False).tail(1)
        if not ports.empty
        else ports
    )

    merged = _build_monthly_merge(prices, climate, yields, ports)
    quality = _quality_series(states, climate) if not states.empty and not climate.empty else pd.DataFrame()
    analytics = _compute_analytics(merged, quality)

    px_last = _safe_latest(prices)
    cl_last = _safe_latest(climate)
    yl_last = _safe_latest(yields)
    qt_last = _safe_latest(quality.rename(columns={"month": "date"})) if not quality.empty else pd.Series(dtype=float)

    avg_delay_days = (
        float(port_latest["eta_delay_days"].mean())
        if not port_latest.empty and "eta_delay_days" in port_latest.columns
        else 0.0
    )
    congestion = (
        float(port_latest["congestion_index"].mean())
        if not port_latest.empty and "congestion_index" in port_latest.columns
        else 0.0
    )

    predicted_price_change_pct = float(analytics.get("predicted_price_change_pct", 0.0))
    quality_risk_index = float(qt_last.get("quality_risk_index", 0.0))
    rainfall_deficit = float(cl_last.get("rainfall_deficit_pct", 0.0))
    supply_chain_risk_score = _clip(
        0.30 * quality_risk_index
        + 0.25 * congestion
        + 0.25 * _clip(rainfall_deficit * 2, 0, 100)
        + 0.20 * _clip(abs(predicted_price_change_pct) * 3, 0, 100),
        0,
        100,
    )

    kpis = {
        "arabica_eur_kg": float(px_last.get("arabica_eur_kg", 0.0)),
        "robusta_eur_kg": float(px_last.get("robusta_eur_kg", 0.0)),
        "wildfire_count": float(cl_last.get("wildfire_count", 0.0)),
        "rainfall_deficit_pct": rainfall_deficit,
        "oni": float(cl_last.get("oni", 0.0)),
        "yield_index": float(yl_last.get("yield_index", 0.0)),
        "production_index": float(yl_last.get("production_index", 0.0)),
        "avg_delay_days": avg_delay_days,
        "congestion_index": congestion,
        "quality_risk_index": quality_risk_index,
        "expected_cup_score": float(qt_last.get("expected_cup_score", 0.0)),
        "predicted_yield_change_pct": float(analytics.get("predicted_yield_change_pct", 0.0)),
        "predicted_price_change_pct": predicted_price_change_pct,
        "supply_chain_risk_score": supply_chain_risk_score,
    }

    return Snapshot(
        date=snapshot_date,
        prices=prices,
        climate=climate,
        yields=yields,
        states_history=states,
        states=state_latest,
        ports_history=ports,
        ports=port_latest,
        merged_monthly=merged,
        quality_monthly=quality,
        analytics=analytics,
        kpis=kpis,
    )


def _delta(now: float, base: float) -> str:
    if pd.isna(base):
        return "n/a"
    if base == 0:
        return "n/a"
    return f"{((now / base) - 1) * 100:+.1f}%"


def _insight_logistics(snapshot: Snapshot) -> str:
    ports = snapshot.ports.sort_values("eta_delay_days", ascending=False) if not snapshot.ports.empty else snapshot.ports
    top = ports.iloc[0] if not ports.empty else {}
    port_name = top.get("port_name", "No port data")
    delay = float(top.get("eta_delay_days", 0.0))
    pred_price = snapshot.kpis["predicted_price_change_pct"]
    return (
        f"Top bottleneck is {port_name} with estimated delay {delay:.1f} days. "
        f"Model indicates a {pred_price:+.1f}% Arabica price move over the next cycle "
        f"if current climate and yield pressure persists."
    )


def _insight_rd(snapshot: Snapshot) -> str:
    corr = float(snapshot.analytics.get("fire_to_yield_corr", 0.0))
    pred_yield = snapshot.kpis["predicted_yield_change_pct"]
    drivers = _top_drivers(snapshot.analytics, top_n=1)
    if drivers:
        name, beta = drivers[0]
        lead_driver = f"{_format_driver_name(name)} currently dominates (beta={beta:+.2f})."
    else:
        lead_driver = "No dominant historical driver available."
    return (
        f"Fire-to-yield correlation is {corr:+.2f}. "
        f"Current model implies a {pred_yield:+.1f}% yield move. {lead_driver}"
    )


def _insight_quality(snapshot: Snapshot) -> str:
    risk = snapshot.kpis["quality_risk_index"]
    cup = snapshot.kpis["expected_cup_score"]
    confidence = float(snapshot.analytics.get("model_confidence", 0.0)) * 100
    return (
        f"Quality risk index is {risk:.1f}/100 with expected cup score {cup:.1f}. "
        f"Confidence in projected quality pressure is {confidence:.0f}%."
    )


def _render_predictive_outlook(department: str, snapshot: Snapshot) -> None:
    drivers = _top_drivers(snapshot.analytics, top_n=2)
    confidence = float(snapshot.analytics.get("model_confidence", 0.15))
    if confidence >= 0.75:
        confidence_line = "Model confidence is high based on historical fit stability."
    elif confidence >= 0.45:
        confidence_line = "Model confidence is moderate; use with supporting operational checks."
    else:
        confidence_line = "Model confidence is low; treat this as directional guidance only."

    driver_lines = []
    ordinals = ["dominant", "secondary"]
    for idx, (name, beta) in enumerate(drivers):
        label = _format_driver_name(name)
        rank_word = ordinals[idx] if idx < len(ordinals) else f"rank {idx + 1}"
        driver_lines.append(f"- {label} is the {rank_word} driver (β = {beta:+.2f})")
    if not driver_lines:
        driver_lines.append("- Yield drivers are not available for the current snapshot.")

    if department == "logistics":
        price_move = snapshot.kpis["predicted_price_change_pct"]
        delay = snapshot.kpis["avg_delay_days"]
        if delay > 3 or abs(price_move) > 5:
            action = "Pre-book export capacity and freight slots now to reduce disruption risk."
        else:
            action = "Maintain current routing plan and monitor congestion weekly."
        metric_lines = [
            f"- Predicted Arabica move: {price_move:+.1f}%",
            f"- Expected average delay: {delay:.1f} days",
        ]
    elif department == "rd":
        yield_shift = snapshot.kpis["predicted_yield_change_pct"]
        high_deficit = 0
        if not snapshot.states.empty and "rainfall_deficit_pct" in snapshot.states.columns:
            high_deficit = int((snapshot.states["rainfall_deficit_pct"] > 15).sum())
        action = (
            "Flag states above 15% rainfall deficit for immediate agronomic review."
            if high_deficit > 0
            else "Keep agronomic watchlist active; no state currently above the 15% deficit trigger."
        )
        metric_lines = [f"- Predicted yield shift: {yield_shift:+.1f}%"]
    else:
        cup = snapshot.kpis["expected_cup_score"]
        risk = snapshot.kpis["quality_risk_index"]
        action = (
            "Increase incoming lot inspection frequency and tighten defect screening."
            if risk > 60
            else "Maintain standard inspection cadence with targeted checks on high-risk origins."
        )
        metric_lines = [
            f"- Expected cup score: {cup:.1f}",
            f"- Current quality risk index: {risk:.1f}/100",
        ]

    with st.expander("📋 Predictive Outlook — next 3 months"):
        block = ["**Primary Forecast**", *metric_lines, "", "**Top Yield Drivers**", *driver_lines, "", "**Confidence**", f"- {confidence_line}", "", "**Recommended Action**", f"- {action}"]
        st.markdown("\n".join(block))


def apply_dashboard_theme() -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Literata:wght@600;700&display=swap');

html, body, [class*="css"] {
  font-family: 'Space Grotesk', sans-serif;
}
h1, h2, h3 {
  font-family: 'Literata', serif;
  letter-spacing: 0.01em;
}
.main {
  background: radial-gradient(1200px 500px at 10% -10%, #FFECCB 0%, rgba(255,236,203,0.0) 50%),
              radial-gradient(900px 300px at 85% -20%, #DCECF6 0%, rgba(220,236,246,0.0) 60%),
              #FAF7F1;
}
[data-testid="stMetricValue"] {
  font-size: 1.6rem;
}
div[data-testid="stTabs"] button {
  font-weight: 600;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _ports_map(ports: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for _, row in ports.iterrows():
        risk = str(row.get("risk_level", "low")).lower()
        color = RISK_COLORS.get(risk, "#C6842D")
        fig.add_trace(
            go.Scattergeo(
                lat=[row["lat"]],
                lon=[row["lon"]],
                mode="markers+text",
                text=[row["port_name"]],
                textposition="top center",
                marker=dict(
                    size=max(10, float(row["anchored_vessels"]) * 2.2 + 8),
                    color=color,
                    opacity=0.85,
                    line=dict(width=1, color="#3A2A1A"),
                ),
                hovertemplate=(
                    f"<b>{row['port_name']}</b><br>"
                    f"Anchored: {float(row['anchored_vessels']):.0f}<br>"
                    f"Delay: {float(row['eta_delay_days']):.1f} days<br>"
                    f"Risk: {risk.title()}<extra></extra>"
                ),
                showlegend=False,
            )
        )
    fig.update_geos(
        scope="south america",
        center=dict(lat=-17, lon=-47),
        projection_scale=2.4,
        showland=True,
        landcolor="#F8EEDC",
        showocean=True,
        oceancolor="#E7F1F7",
        showcountries=True,
        countrycolor="#CCB79B",
        showframe=False,
    )
    fig.update_layout(
        height=420,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _render_state_map(states_df: pd.DataFrame) -> go.Figure:
    geojson, lookup = _load_ibge_assets()
    if geojson is not None and lookup is not None:
        map_df = states_df.copy()
        map_df["code"] = map_df["code"].astype(str).str.upper()
        map_df["ibge_code"] = map_df["code"].map(lookup)
        map_df = map_df.dropna(subset=["ibge_code"])
        if not map_df.empty:
            fig = px.choropleth_mapbox(
                map_df,
                geojson=geojson,
                locations="ibge_code",
                featureidkey="properties.codarea",
                color="rainfall_deficit_pct",
                hover_name="state",
                hover_data={
                    "code": True,
                    "rainfall_deficit_pct": ":.1f",
                    "production_60kg_bags": ":,.0f",
                    "ibge_code": False,
                },
                color_continuous_scale="YlOrRd",
                mapbox_style="carto-positron",
                center={"lat": -15, "lon": -52},
                zoom=3,
                opacity=0.72,
            )
            fig.update_layout(
                height=390,
                margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
            )
            return fig

    fallback = px.scatter_geo(
        states_df,
        lat="lat",
        lon="lon",
        size="production_60kg_bags",
        color="rainfall_deficit_pct",
        hover_name="state",
        color_continuous_scale="YlOrRd",
        projection="natural earth",
    )
    fallback.update_geos(
        scope="south america",
        center=dict(lat=-17, lon=-47),
        projection_scale=2.2,
        showland=True,
        landcolor="#F8EEDC",
        showocean=True,
        oceancolor="#E7F1F7",
        showcountries=True,
        countrycolor="#CCB79B",
        showframe=False,
    )
    fallback.update_layout(
        height=390,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fallback


def render_dashboard(
    bundle: dict[str, Any],
    app_title: str,
    source_label: str,
    subtitle: str,
) -> None:
    apply_dashboard_theme()

    reference_date = _get_reference_date(bundle)
    earliest_date = reference_date - pd.DateOffset(months=36)

    with st.sidebar:
        st.markdown("### Time-lapse")
        selected_range = st.date_input(
            "Compare snapshots",
            value=(
                (reference_date - pd.DateOffset(months=1)).date(),
                reference_date.date(),
            ),
            min_value=earliest_date.date(),
            max_value=reference_date.date(),
        )
        if isinstance(selected_range, tuple) and len(selected_range) == 2:
            d0 = pd.Timestamp(selected_range[0])
            d1 = pd.Timestamp(selected_range[1])
        else:
            single = pd.Timestamp(selected_range)
            d0 = single
            d1 = single
        secondary_date = min(d0, d1)
        primary_date = max(d0, d1)
        compare = st.toggle("Show comparison vs alternate snapshot", value=True)
        st.markdown("### Source")
        st.caption(source_label)

        st.markdown("### 🔴 Latest Intelligence")
        news_df = bundle.get("news", pd.DataFrame())
        if isinstance(news_df, pd.DataFrame) and not news_df.empty:
            top_news = news_df.sort_values("relevance_score", ascending=False).head(5)
            for _, row in top_news.iterrows():
                sentiment = str(row.get("sentiment", "neutral")).lower()
                icon = "🔴" if sentiment == "negative" else "🟢" if sentiment == "positive" else "⚪"
                title = str(row.get("title", "Untitled"))[:110]
                with st.expander(f"{icon} {title}"):
                    summary = str(row.get("summary", "")).strip()
                    if summary:
                        st.write(summary)
                    topic = str(row.get("topic", "general"))
                    st.caption(f"Topic: {topic}")
                    url = str(row.get("url", "")).strip()
                    if url:
                        st.markdown(f"[Read source]({url})")
        else:
            st.caption("No news feed connected.")

        st.markdown("### 🕐 Data Sources")
        source_log = bundle.get("source_log", [])
        if isinstance(source_log, list) and source_log:
            for item in source_log:
                source = str(item.get("source", "Unknown source"))
                status = str(item.get("status", "unknown")).lower()
                age_text, age_hours = _humanize_age(item.get("fetched_at"))
                stale = age_hours > 48
                ok = status == "live" and not stale
                icon = "✅" if ok else "❌"
                if stale:
                    st.markdown(f"{icon} **{source}** · :red[{age_text}]")
                else:
                    st.markdown(f"{icon} **{source}** · {age_text}")
        else:
            st.caption("No source freshness log connected.")

    primary = _slice_snapshot(bundle, primary_date)
    secondary = _slice_snapshot(bundle, secondary_date)
    compare_label = f"vs {secondary.date.date()}"

    st.markdown(f"## {app_title}")
    st.caption(f"{subtitle} | Snapshot date: {primary.date.date()}")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric(
        "Arabica (EUR/kg)",
        f"{primary.kpis['arabica_eur_kg']:.2f}",
        _delta(primary.kpis["arabica_eur_kg"], secondary.kpis["arabica_eur_kg"]) if compare else None,
    )
    c2.metric(
        "Predicted yield shift",
        f"{primary.kpis['predicted_yield_change_pct']:+.1f}%",
        _delta(primary.kpis["predicted_yield_change_pct"], secondary.kpis["predicted_yield_change_pct"])
        if compare
        else None,
    )
    c3.metric(
        "Wildfire detections",
        f"{primary.kpis['wildfire_count']:.0f}",
        _delta(primary.kpis["wildfire_count"], secondary.kpis["wildfire_count"]) if compare else None,
    )
    c4.metric(
        "Avg delay (days)",
        f"{primary.kpis['avg_delay_days']:.1f}",
        _delta(primary.kpis["avg_delay_days"], secondary.kpis["avg_delay_days"]) if compare else None,
    )
    c5.metric(
        "Expected cup score",
        f"{primary.kpis['expected_cup_score']:.1f}",
        _delta(primary.kpis["expected_cup_score"], secondary.kpis["expected_cup_score"]) if compare else None,
    )
    c6.metric(
        "Supply Chain Risk",
        f"{primary.kpis['supply_chain_risk_score']:.0f} / 100",
        _delta(primary.kpis["supply_chain_risk_score"], secondary.kpis["supply_chain_risk_score"])
        if compare
        else None,
    )
    if compare:
        st.caption(f"Delta context: {compare_label}")

    logistics_tab, rd_tab, quality_tab = st.tabs(["Logistics", "R&D", "Quality"])

    with logistics_tab:
        lcol, rcol = st.columns([1.65, 1.0])
        with lcol:
            st.plotly_chart(_ports_map(primary.ports), use_container_width=True)
        with rcol:
            if not primary.ports.empty:
                port_rank = primary.ports.sort_values("eta_delay_days", ascending=False)[
                    ["port_name", "anchored_vessels", "eta_delay_days", "risk_level"]
                ].copy()
                st.dataframe(
                    port_rank.rename(
                        columns={
                            "port_name": "Port",
                            "anchored_vessels": "Anchored",
                            "eta_delay_days": "Delay (days)",
                            "risk_level": "Risk",
                        }
                    ),
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.caption("No port data available for selected snapshot.")

        monthly = primary.merged_monthly.copy()
        fig_log = make_subplots(specs=[[{"secondary_y": True}]])
        fig_log.add_trace(
            go.Scatter(
                x=monthly["month"],
                y=monthly["arabica_eur_kg"],
                name="Arabica EUR/kg",
                mode="lines+markers",
                line=dict(color="#1F5E8C", width=2.5),
            ),
            secondary_y=False,
        )
        fig_log.add_trace(
            go.Scatter(
                x=monthly["month"],
                y=monthly["fx_brl_per_eur"],
                name="BRL/EUR",
                mode="lines+markers",
                line=dict(color="#7A4EAB", width=2.0, dash="dot"),
            ),
            secondary_y=True,
        )
        fig_log.add_trace(
            go.Scatter(
                x=monthly["month"],
                y=monthly["congestion_index"],
                name="Congestion index",
                mode="lines",
                line=dict(color="#B23A2E", width=1.5),
                fill="tozeroy",
                fillcolor="rgba(178,58,46,0.12)",
            ),
            secondary_y=True,
        )
        fig_log.update_yaxes(title_text="Arabica (EUR/kg)", secondary_y=False)
        fig_log.update_yaxes(title_text="BRL/EUR & Congestion", secondary_y=True)
        fig_log.update_layout(
            height=330,
            margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=1.08, x=0.0),
        )
        st.plotly_chart(fig_log, use_container_width=True)
        st.info(_insight_logistics(primary))
        _render_predictive_outlook("logistics", primary)

    with rd_tab:
        rd_left, rd_right = st.columns(2)
        with rd_left:
            fig_rd = make_subplots(specs=[[{"secondary_y": True}]])
            fig_rd.add_trace(
                go.Bar(
                    x=primary.merged_monthly["month"],
                    y=primary.merged_monthly["rainfall_deficit_pct"],
                    name="Rainfall deficit %",
                    marker_color="#D9893A",
                ),
                secondary_y=False,
            )
            fig_rd.add_trace(
                go.Scatter(
                    x=primary.merged_monthly["month"],
                    y=primary.merged_monthly["yield_index"],
                    name="Yield index",
                    line=dict(color="#2F6E4D", width=2.5),
                    mode="lines+markers",
                ),
                secondary_y=True,
            )
            fig_rd.update_yaxes(title_text="Rainfall deficit %", secondary_y=False)
            fig_rd.update_yaxes(title_text="Yield index", secondary_y=True)
            fig_rd.update_layout(
                height=320,
                margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                legend=dict(orientation="h", y=1.08, x=0.0),
            )
            st.plotly_chart(fig_rd, use_container_width=True)

        with rd_right:
            scatter = primary.merged_monthly.copy()
            scatter["wildfire_lag2"] = scatter["wildfire_count"].shift(2)
            scatter["yield_next_change"] = scatter["yield_index"].pct_change() * 100
            scatter = scatter.dropna(subset=["wildfire_lag2", "yield_next_change"])
            fig_sc = px.scatter(
                scatter,
                x="wildfire_lag2",
                y="yield_next_change",
                labels={
                    "wildfire_lag2": "Wildfires (lagged 2 months)",
                    "yield_next_change": "Yield change %",
                },
                color_discrete_sequence=["#1F5E8C"],
            )
            if len(scatter) >= 2:
                slope, intercept = np.polyfit(
                    scatter["wildfire_lag2"], scatter["yield_next_change"], 1
                )
                x_line = np.linspace(scatter["wildfire_lag2"].min(), scatter["wildfire_lag2"].max(), 80)
                y_line = slope * x_line + intercept
                fig_sc.add_trace(
                    go.Scatter(
                        x=x_line,
                        y=y_line,
                        mode="lines",
                        line=dict(color="#B23A2E", width=2),
                        name="Trend",
                    )
                )
            fig_sc.update_layout(
                height=320,
                margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=len(scatter) >= 2,
            )
            st.plotly_chart(fig_sc, use_container_width=True)

        if (
            "arabica_production_index" in primary.merged_monthly.columns
            and "canephora_production_index" in primary.merged_monthly.columns
        ):
            prod_fig = go.Figure()
            prod_fig.add_trace(
                go.Bar(
                    x=primary.merged_monthly["month"],
                    y=primary.merged_monthly["arabica_production_index"],
                    name="Arabica production index",
                    marker_color="#EF9F27",
                )
            )
            prod_fig.add_trace(
                go.Bar(
                    x=primary.merged_monthly["month"],
                    y=primary.merged_monthly["canephora_production_index"],
                    name="Canephora production index",
                    marker_color="#1D9E75",
                )
            )
            prod_fig.update_layout(
                barmode="stack",
                height=320,
                margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                legend=dict(orientation="h", y=1.08, x=0.0),
                yaxis_title="Production index (baseline 2018–2022 = 100)",
            )
            st.plotly_chart(prod_fig, use_container_width=True)

        if not primary.states.empty:
            st.plotly_chart(_render_state_map(primary.states), use_container_width=True)
        st.info(_insight_rd(primary))
        _render_predictive_outlook("rd", primary)

    with quality_tab:
        q_left, q_right = st.columns([1.2, 1.0])
        with q_left:
            if not primary.quality_monthly.empty:
                fig_q = make_subplots(specs=[[{"secondary_y": True}]])
                fig_q.add_trace(
                    go.Scatter(
                        x=primary.quality_monthly["month"],
                        y=primary.quality_monthly["quality_risk_index"],
                        name="Quality risk index",
                        line=dict(color="#B23A2E", width=2.4),
                        mode="lines+markers",
                    ),
                    secondary_y=False,
                )
                fig_q.add_trace(
                    go.Scatter(
                        x=primary.quality_monthly["month"],
                        y=primary.quality_monthly["expected_cup_score"],
                        name="Expected cup score",
                        line=dict(color="#2F6E4D", width=2.2),
                        mode="lines+markers",
                    ),
                    secondary_y=True,
                )
                fig_q.update_yaxes(title_text="Risk (0-100)", secondary_y=False)
                fig_q.update_yaxes(title_text="Cup score", secondary_y=True)
                fig_q.update_layout(
                    height=340,
                    margin=dict(l=0, r=0, t=10, b=0),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    legend=dict(orientation="h", y=1.08, x=0.0),
                )
                st.plotly_chart(fig_q, use_container_width=True)
            else:
                st.caption("No quality history available for selected snapshot.")

        with q_right:
            latest_states = primary.states.copy()
            if not latest_states.empty:
                latest_states["defect_risk_pct"] = (
                    0.45 * latest_states["rainfall_deficit_pct"].clip(lower=0)
                    + 0.35 * latest_states["wildfire_pressure"].clip(lower=0)
                    + (85 - latest_states["quality_score"]).clip(lower=0) * 4
                ).clip(0, 100)
                fig_def = px.bar(
                    latest_states.sort_values("defect_risk_pct", ascending=True),
                    x="defect_risk_pct",
                    y="state",
                    orientation="h",
                    labels={"defect_risk_pct": "Estimated defect risk %", "state": ""},
                    color="defect_risk_pct",
                    color_continuous_scale="YlOrRd",
                )
                fig_def.update_layout(
                    height=340,
                    margin=dict(l=0, r=0, t=10, b=0),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    coloraxis_showscale=False,
                )
                st.plotly_chart(fig_def, use_container_width=True)
            else:
                st.caption("No state quality data available for selected snapshot.")

        if not primary.states_history.empty:
            heat_source = primary.states_history.copy().sort_values("date")
            heat_source["month"] = heat_source["date"].dt.to_period("M").dt.to_timestamp()
            heat = (
                heat_source.pivot_table(
                    index="state",
                    columns="month",
                    values="quality_score",
                    aggfunc="mean",
                )
                .sort_index()
                .iloc[:, -6:]
            )
            fig_heat = px.imshow(
                heat,
                aspect="auto",
                color_continuous_scale="YlGnBu",
                labels=dict(x="Month", y="State", color="Quality score"),
            )
            fig_heat.update_layout(
                height=320,
                margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_heat, use_container_width=True)
        st.info(_insight_quality(primary))
        _render_predictive_outlook("quality", primary)

    has_export_data = (
        not primary.prices.empty
        or not primary.climate.empty
        or not primary.ports.empty
        or not primary.states.empty
    )
    if has_export_data:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            primary.prices.to_excel(writer, index=False, sheet_name="Prices")
            primary.climate.to_excel(writer, index=False, sheet_name="Climate")
            primary.ports.to_excel(writer, index=False, sheet_name="Ports")
            primary.states.to_excel(writer, index=False, sheet_name="States")
            analytics_df = pd.DataFrame(_dict_to_rows(primary.analytics))
            analytics_df.to_excel(writer, index=False, sheet_name="Analytics")
        buffer.seek(0)
        st.download_button(
            "⬇ Export snapshot as Excel",
            data=buffer.getvalue(),
            file_name=f"lavazza_snapshot_{primary.date.date()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
