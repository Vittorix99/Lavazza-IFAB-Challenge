"""
charts.py — Grafici Plotly per Lavazza Coffee Intelligence Dashboard.

Struttura:
  - Estrattori MongoDB: leggono raw_* collections e restituiscono DataFrame
    nello stesso formato delle funzioni fetch_* della standalone app.
  - Dati simulati: fallback numpy+pandas, identici alla standalone app.
  - Funzioni API: fetch da NOAA/NASA/WB/USDA (opzionali, richiedono
    yfinance/faostat se installati).
  - render_enso_tab / render_fires_tab / render_prices_tab /
    render_yields_tab / render_climate_tab:
    Plotly chart identici alle render_tab_* della standalone app
    (il choropleth matplotlib/geopandas è sostituito con scatter_mapbox).

Punto d'ingresso per app.py:
  render_dashboard_tab(tab, country, use_api, simulated)
"""

import io
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from utils.db import get_latest_doc, get_recent_docs

# ============================================================================
# Costanti (speculari alla standalone app)
# ============================================================================

COLORS = {
    "arabica":   "#4A2F1D",
    "robusta":   "#C6842D",
    "highlight": "#1A5EA8",
    "danger":    "#B23A2E",
    "warning":   "#C6842D",
    "safe":      "#3E7B58",
}

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

COFFEE_STATE_PROD = {
    "MG": {"Arabica": 28.0, "Robusta": 0.3},
    "ES": {"Arabica": 3.0,  "Robusta": 10.5},
    "SP": {"Arabica": 5.4,  "Robusta": 0.0},
    "BA": {"Arabica": 1.2,  "Robusta": 2.2},
    "RO": {"Arabica": 0.0,  "Robusta": 2.8},
    "PR": {"Arabica": 0.5,  "Robusta": 0.0},
    "RJ": {"Arabica": 0.3,  "Robusta": 0.0},
    "GO": {"Arabica": 0.2,  "Robusta": 0.0},
    "MT": {"Arabica": 0.0,  "Robusta": 0.2},
}

STATE_COORDS = {
    "Minas Gerais":   ("MG", -18.5, -44.5),
    "Espirito Santo": ("ES", -19.5, -40.3),
    "Sao Paulo":      ("SP", -22.0, -47.5),
    "Bahia":          ("BA", -12.5, -41.7),
    "Rondonia":       ("RO", -11.0, -62.0),
    "Parana":         ("PR", -24.5, -51.5),
    "Goias":          ("GO", -16.0, -49.5),
    "Mato Grosso":    ("MT", -13.0, -56.0),
}

PORTS = [
    ("Santos",         -23.95, -46.33, 62.0),
    ("Vitoria",        -20.32, -40.34, 38.0),
    ("Paranagua",      -25.52, -48.50, 45.0),
    ("Rio de Janeiro", -22.90, -43.17, 26.0),
    ("Salvador",       -12.90, -38.51, 18.0),
]

NOAA_ONI_URL = "https://psl.noaa.gov/data/correlation/oni.data"
NOAA_SOI_URL = "https://psl.noaa.gov/data/correlation/soi.data"
FIRMS_MAP_KEY = os.environ.get("NASA_FIRMS_KEY", "63fb02bde23144ea120a3123f959bf4c")
USDA_BASE_URL = "https://api.fas.usda.gov/api/psd"
USDA_COMMODITY = "0711100"
USDA_COUNTRY = "BR"
USDA_TARGET_ATTRS = {
    "Production":           "production_mt",
    "Exports":              "exports_mt",
    "Ending Stocks":        "ending_stocks_mt",
    "Beginning Stocks":     "beginning_stocks_mt",
    "Domestic Consumption": "consumption_mt",
}
WB_MONTHLY_URL = "https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx"

_SEED = 42


# ============================================================================
# DATI SIMULATI (numpy+pandas — fallback sempre disponibile)
# ============================================================================

def _sim_oni() -> pd.Series:
    rng = np.random.default_rng(_SEED)
    dates = pd.date_range(start="2014-01-01", periods=120, freq="ME")
    vals = 0.8 * np.sin(np.linspace(0, 4 * np.pi, 120)) + rng.normal(0, 0.2, 120)
    idx = pd.MultiIndex.from_arrays(
        [dates.year.tolist(), dates.month.tolist()], names=["Year", "Month"]
    )
    return pd.Series(vals, index=idx).dropna()


def _sim_soi() -> pd.Series:
    rng = np.random.default_rng(_SEED + 1)
    dates = pd.date_range(start="2014-01-01", periods=120, freq="ME")
    vals = -10.0 * np.sin(np.linspace(0, 4 * np.pi, 120)) + rng.normal(0, 3.0, 120)
    idx = pd.MultiIndex.from_arrays(
        [dates.year.tolist(), dates.month.tolist()], names=["Year", "Month"]
    )
    return pd.Series(vals, index=idx).dropna()


def _sim_fires() -> pd.DataFrame:
    rng = np.random.default_rng(_SEED)
    rows = []
    for _ in range(150):
        rows.append({"latitude": rng.normal(-13, 2), "longitude": rng.normal(-56, 3),
                     "frp": float(rng.uniform(20, 80))})
    for _ in range(100):
        rows.append({"latitude": rng.normal(-19, 1.5), "longitude": rng.normal(-43, 2),
                     "frp": float(rng.uniform(10, 60))})
    for _ in range(50):
        rows.append({"latitude": float(rng.uniform(-30, -5)),
                     "longitude": float(rng.uniform(-70, -35)),
                     "frp": float(rng.uniform(5, 50))})
    return pd.DataFrame(rows)


def _sim_prices() -> pd.DataFrame:
    rng = np.random.default_rng(_SEED)
    dates = pd.date_range(end=pd.Timestamp.today() + pd.offsets.MonthEnd(0),
                          periods=120, freq="ME")
    n = len(dates)
    eur = 4.5 + np.cumsum(rng.normal(0, 0.1, n))
    fx = 5.2 + np.cumsum(rng.normal(0, 0.05, n))
    return pd.DataFrame({
        "date":           dates,
        "arabica_eur_kg": eur,
        "robusta_eur_kg": 2.2 + np.cumsum(rng.normal(0, 0.05, n)),
        "fx_brl_per_eur": fx,
        "arabica_brl_kg": eur * fx,
    })


def _sim_usda() -> pd.DataFrame:
    rng = np.random.default_rng(_SEED)
    yrs = np.arange(2000, pd.Timestamp.today().year + 1)
    bi = np.sin(np.arange(len(yrs)) * np.pi)
    ara = np.clip(52_000_000 + 3_000_000 * bi + rng.normal(0, 1_000_000, len(yrs)),
                  38_000_000, 68_000_000)
    rob = np.clip(18_000_000 + 1_200_000 * np.sin(np.arange(len(yrs)) / 2)
                  + rng.normal(0, 500_000, len(yrs)), 10_000_000, 25_000_000)
    return pd.DataFrame({
        "year":          yrs,
        "arabica_bags":  ara,
        "robusta_bags":  rob,
        "yield_ara":     np.clip(1200 + 50 * bi + rng.normal(0, 20, len(yrs)), 800, 1800),
        "yield_rob":     np.clip(1600 + 40 * np.sin(np.arange(len(yrs)) / 2)
                                 + rng.normal(0, 10, len(yrs)), 1200, 2100),
        "export_ara":    ara * 0.80 + rng.normal(0, 800_000, len(yrs)),
        "export_rob":    rob * 0.65 + rng.normal(0, 400_000, len(yrs)),
        "inventory_ara": ara * 0.18 + rng.normal(0, 300_000, len(yrs)),
        "inventory_rob": rob * 0.12 + rng.normal(0, 150_000, len(yrs)),
    })


def _sim_faostat() -> pd.DataFrame:
    rng = np.random.default_rng(_SEED)
    years = list(range(1990, pd.Timestamp.today().year))
    n = len(years)
    return pd.DataFrame({
        "Year":           years,
        "Area harvested": np.clip(2_200_000 + np.cumsum(rng.normal(0, 15_000, n)),
                                  1_800_000, 3_100_000),
        "Production":     np.clip(3_200_000 + np.cumsum(rng.normal(0, 80_000, n)),
                                  2_000_000, 6_500_000),
        "Yield":          np.clip(14_000 + rng.normal(0, 800, n), 9_000, 22_000),
    })


def _sim_conab() -> pd.DataFrame:
    base = [
        ("Minas Gerais", 32_000_000, 29.5),
        ("Espirito Santo", 15_500_000, 31.0),
        ("Sao Paulo", 5_600_000, 27.0),
        ("Bahia", 5_200_000, 30.5),
        ("Rondonia", 3_800_000, 33.5),
        ("Parana", 2_100_000, 23.0),
        ("Goias", 1_800_000, 26.0),
        ("Mato Grosso", 1_400_000, 24.0),
    ]
    df = pd.DataFrame([{
        "state": s, "code": STATE_COORDS[s][0],
        "lat": STATE_COORDS[s][1], "lon": STATE_COORDS[s][2],
        "production_bags": p, "yield": y,
    } for s, p, y in base])
    df["log_production"] = np.log1p(df["production_bags"])
    return df


def _make_climate(dates: pd.Series, oni_vals: pd.Series | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(_SEED)
    n = len(dates)
    if oni_vals is not None and len(oni_vals) >= n:
        oni_arr = oni_vals.values[-n:]
    else:
        oni_arr = 0.25 * np.sin(np.linspace(0, 2.5 * np.pi, n)) + rng.normal(0, 0.07, n)
    month = pd.Series(dates).dt.month
    dry = month.isin([6, 7, 8, 9]).astype(float).values
    deficit = np.clip(6 + 9 * dry + 10 * np.clip(-oni_arr, 0, None)
                      + rng.normal(0, 2, n), 0, 30)
    wildfire = np.clip(250 + 70 * dry + 36 * deficit + rng.normal(0, 50, n),
                       50, 4500).round()
    return pd.DataFrame({
        "date":                 dates.values,
        "oni":                  oni_arr,
        "rainfall_deficit_pct": deficit,
        "wildfire_count":       wildfire,
    })


def _states_prod_df() -> pd.DataFrame:
    rows = []
    for sigla, vals in COFFEE_STATE_PROD.items():
        rows.append({"state": sigla,
                     "arabica_bags": vals["Arabica"],
                     "robusta_bags": vals["Robusta"]})
    return pd.DataFrame(rows)


# ============================================================================
# ESTRATTORI MONGODB — restituiscono DataFrame nello stesso formato dei
# fetch simulati, oppure None se non ci sono dati.
# ============================================================================

@st.cache_data(ttl=3600, show_spinner=False)
def _mongo_oni(country: str = "BR") -> pd.Series | None:
    """Estrae serie ONI da raw_environment.NOAA_ENSO.recent_series."""
    doc = get_latest_doc("raw_environment", "NOAA_ENSO", country)
    if not doc:
        return None
    series = doc.get("recent_series", [])
    if not series:
        return None
    rows = []
    for r in series:
        year = r.get("year")
        month = r.get("month_number") or r.get("month")
        oni = r.get("oni_value")
        if year and month is not None and oni is not None:
            try:
                rows.append((int(year), int(month), float(oni)))
            except (TypeError, ValueError):
                pass
    if not rows:
        return None
    idx = pd.MultiIndex.from_tuples([(y, m) for y, m, _ in rows],
                                    names=["Year", "Month"])
    return pd.Series([v for _, _, v in rows], index=idx)


@st.cache_data(ttl=3600, show_spinner=False)
def _mongo_fires(country: str = "BR") -> pd.DataFrame | None:
    """Estrae fire records da raw_environment.NASA_FIRMS."""
    doc = get_latest_doc("raw_environment", "NASA_FIRMS", country)
    if not doc:
        return None
    # Trova il campo array tramite _chart_fields o prova nomi comuni
    for field in doc.get("_chart_fields", []) + ["fires", "fire_records", "detections"]:
        val = doc.get(field)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            df = pd.DataFrame(val)
            if "latitude" in df.columns or "lat" in df.columns:
                df = df.rename(columns={"lat": "latitude", "lng": "longitude",
                                        "lon": "longitude"})
                df["frp"] = pd.to_numeric(df.get("frp", 10), errors="coerce").fillna(10)
                return df
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def _mongo_prices(country: str = "BR") -> pd.DataFrame | None:
    """
    Tenta di costruire un DataFrame prezzi dal WB_PINK_SHEET + BCB_PTAX in MongoDB.
    recent_series contiene: {period_raw, report_month, report_date,
                              coffee_arabica_price, coffee_robusta_price, arabica_robusta_spread}
    """
    wb = (get_latest_doc("raw_prices", "WB_PINK_SHEET", country)
          or get_latest_doc("raw_prices", "WORLD_BANK_PINKSHEET", country))
    bcb = get_latest_doc("raw_prices", "BCB_PTAX", country)
    ecb = get_latest_doc("raw_prices", "ECB_DATA_PORTAL", country)

    # FX: entrambi i tassi devono essere reali da MongoDB — nessun valore hardcodato
    brl_usd = float(bcb["cotacaoVenda"]) if bcb and bcb.get("cotacaoVenda") else None
    fx_brl_eur = float(ecb["fx_rate_brl_per_eur"]) if ecb and ecb.get("fx_rate_brl_per_eur") else None
    if brl_usd is None or fx_brl_eur is None:
        return None
    usd_per_eur = fx_brl_eur / brl_usd

    if wb:
        fields_to_try = list(wb.get("_chart_fields", []))
        if "recent_series" not in fields_to_try:
            fields_to_try.append("recent_series")

        for field in fields_to_try:
            val = wb.get(field)
            if not (isinstance(val, list) and len(val) > 1):
                continue
            df = pd.DataFrame(val)
            date_col = next((c for c in ["report_date", "report_month"] if c in df.columns), None)
            if date_col is None:
                date_col = next((c for c in df.columns
                                 if "date" in c.lower() or "month" in c.lower()), None)
            ara_col = next((c for c in ["coffee_arabica_price"] if c in df.columns), None)
            if ara_col is None:
                ara_col = next((c for c in df.columns
                                if "arabica" in c.lower() or "coffee" in c.lower()), None)
            rob_col = next((c for c in ["coffee_robusta_price"] if c in df.columns), None)
            if rob_col is None:
                rob_col = next((c for c in df.columns if "robusta" in c.lower()), None)
            if not (date_col and ara_col):
                continue
            df["date"] = pd.to_datetime(df[date_col], errors="coerce")
            # WB prices in USD/kg → EUR/kg via tasso ECB live; BRL/kg via BCB live
            arabica_usd = pd.to_numeric(df[ara_col], errors="coerce")
            df["arabica_eur_kg"] = arabica_usd / usd_per_eur
            df["robusta_eur_kg"] = ((pd.to_numeric(df[rob_col], errors="coerce") / usd_per_eur)
                                    if rob_col else df["arabica_eur_kg"] * 0.45)
            df["fx_brl_per_eur"] = fx_brl_eur
            df["arabica_brl_kg"] = arabica_usd * brl_usd
            result = (df[["date", "arabica_eur_kg", "robusta_eur_kg",
                           "fx_brl_per_eur", "arabica_brl_kg"]]
                      .dropna(subset=["date", "arabica_eur_kg"])
                      .sort_values("date")
                      .reset_index(drop=True))
            if not result.empty:
                return result
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def _mongo_fertilizers(country: str = "BR") -> pd.DataFrame | None:
    """
    Legge fertilizer_series dal documento WB_PINK_SHEET.
    Struttura: [{report_date, report_month, dap_usd_t, urea_usd_t, potash_usd_t}]
    """
    doc = (get_latest_doc("raw_prices", "WB_PINK_SHEET", country)
           or get_latest_doc("raw_prices", "WORLD_BANK_PINKSHEET", country))
    if not doc:
        return None
    series = doc.get("fertilizer_series", [])
    if not (isinstance(series, list) and len(series) > 1):
        return None
    df = pd.DataFrame(series)
    date_col = next((c for c in ["report_date", "report_month"] if c in df.columns), None)
    if not date_col:
        return None
    df["date"] = pd.to_datetime(df[date_col], errors="coerce")
    for col in ["dap_usd_t", "urea_usd_t", "potash_usd_t"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    result = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    # verifica che almeno una colonna fertilizzante abbia dati
    fert_cols = [c for c in ["dap_usd_t", "urea_usd_t", "potash_usd_t"] if c in result.columns]
    if not fert_cols or result[fert_cols].dropna(how="all").empty:
        return None
    return result


@st.cache_data(ttl=3600, show_spinner=False)
def _mongo_usda(country: str = "BR") -> pd.DataFrame | None:
    doc = get_latest_doc("raw_crops", "USDA_FAS_PSD", country)
    if not doc:
        return None
    for field in doc.get("_chart_fields", []):
        val = doc.get(field)
        if isinstance(val, list) and val:
            df = pd.DataFrame(val)
            year_col = next((c for c in df.columns if "year" in c.lower()), None)
            ara_col = next((c for c in df.columns
                            if "arabica" in c.lower() or "bags" in c.lower()), None)
            if year_col and ara_col:
                df = df.rename(columns={year_col: "year", ara_col: "arabica_bags"})
                if "robusta_bags" not in df.columns:
                    df["robusta_bags"] = df["arabica_bags"] * 0.28
                for col in ["export_ara", "export_rob", "inventory_ara", "inventory_rob"]:
                    if col not in df.columns:
                        df[col] = np.nan
                return df[["year", "arabica_bags", "robusta_bags",
                            "export_ara", "export_rob",
                            "inventory_ara", "inventory_rob"]].dropna(subset=["arabica_bags"])
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def _mongo_faostat(country: str = "BR") -> pd.DataFrame | None:
    doc = (get_latest_doc("raw_crops", "FAOSTAT", country)
           or get_latest_doc("raw_crops", "FAOSTAT_QCL", country))
    if not doc:
        return None
    # Prioritize yearly_series (full history after workflow fix)
    for field in ["yearly_series"] + [f for f in doc.get("_chart_fields", []) if f != "yearly_series"]:
        val = doc.get(field)
        if not (isinstance(val, list) and len(val) >= 2):
            continue
        df = pd.DataFrame(val)
        year_col = next((c for c in df.columns if "year" in c.lower()), None)
        prod_col = next((c for c in df.columns if "production" in c.lower()), None)
        area_col = next((c for c in df.columns if "area" in c.lower()), None)
        if year_col and prod_col:
            df = df.rename(columns={year_col: "Year", prod_col: "Production"})
            if area_col:
                df = df.rename(columns={area_col: "Area harvested"})
            return df
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def _mongo_conab(country: str = "BR") -> pd.DataFrame | None:
    """
    Estrae dati CONAB da MongoDB.
    Il documento CONAB_CAFE_SAFRA contiene top_states_by_production con
    {uf, state, production_mt, share_of_total_pct, yield_kgha}.
    """
    doc = (get_latest_doc("raw_crops", "CONAB_CAFE_SAFRA", country)
           or get_latest_doc("raw_crops", "CONAB_PDF", country)
           or get_latest_doc("raw_crops", "CONAB", country))
    if not doc:
        return None

    # STATE_COORDS usa nomi interi come chiavi: {"Minas Gerais": ("MG", lat, lon)}
    # UF_MAP inverte: "MG" → "Minas Gerais"
    _uf_to_name = {v[0]: k for k, v in STATE_COORDS.items()}

    for field in ["top_states_by_production", "all_states", "focus_states"]:
        states = doc.get(field)
        if not (isinstance(states, list) and len(states) >= 2):
            continue
        df = pd.DataFrame(states)
        cols = list(df.columns)

        # --- Trova colonna produzione ---
        prod_col = next(
            (c for c in cols if "production" in str(c).lower() and "mt" in str(c).lower()),
            next((c for c in cols if "production" in str(c).lower()), None)
        )
        if not prod_col:
            continue

        # --- Trova colonna yield ---
        yield_col = next((c for c in cols if "yield" in str(c).lower()), None)

        # --- Costruisci colonna "state" (nome per intero) ---
        # Priorità: colonna "state" se ha nomi interi, altrimenti "uf" mappato a nomi interi
        if "state" in cols and "uf" in cols:
            # CONAB ha ENTRAMBI: "uf" = codice, "state" = nome — usiamo "state" direttamente
            state_series = df["state"].astype(str)
        elif "state" in cols:
            state_series = df["state"].astype(str)
        elif "uf" in cols:
            state_series = df["uf"].astype(str).map(lambda u: _uf_to_name.get(u, u))
        else:
            continue

        # --- Costruisci DataFrame pulito ---
        out = pd.DataFrame()
        out["state"] = state_series
        out["production_bags"] = pd.to_numeric(df[prod_col], errors="coerce").fillna(0)
        out["yield"] = pd.to_numeric(df[yield_col], errors="coerce").fillna(0) if yield_col else 0.0

        # Coordinate per bubble chart: STATE_COORDS ha nomi interi come chiavi
        out["lat"]  = out["state"].map(lambda s: STATE_COORDS.get(s, ("", 0.0, 0.0))[1])
        out["lon"]  = out["state"].map(lambda s: STATE_COORDS.get(s, ("", 0.0, 0.0))[2])
        out["code"] = out["state"].map(lambda s: STATE_COORDS.get(s, (s, 0.0, 0.0))[0])
        out["log_production"] = np.log1p(out["production_bags"])

        result = out[out["production_bags"] > 0].reset_index(drop=True)
        if not result.empty:
            return result

    return None


@st.cache_data(ttl=3600, show_spinner=False)
def _mongo_ibge(country: str = "BR") -> pd.DataFrame | None:
    """
    Estrae dati IBGE SIDRA da MongoDB.
    state_focus_latest è una LISTA di {geo_code, geo_name, arabica, canephora, total_production_tons}.
    Restituisce DataFrame con [code, state, arabica_t, canephora_t, total_t,
    arabica_yield, canephora_yield] per i 4 stati focus + Brasile.
    """
    doc = get_latest_doc("raw_crops", "IBGE_SIDRA_LSPA", country)
    if not doc:
        return None

    # state_focus_latest = lista [{geo_code, geo_name, arabica:{production_tons, yield_kg_per_ha,...}, canephora:{...}}]
    state_focus_list = doc.get("state_focus_latest") or []
    national = doc.get("national_latest") or {}
    period_label = doc.get("latest_period_label") or "Latest"

    rows = []

    # Itera la lista degli stati focus
    for entry in state_focus_list:
        if not isinstance(entry, dict):
            continue
        geo_code = str(entry.get("geo_code", ""))
        geo_name = entry.get("geo_name") or geo_code
        ara = entry.get("arabica") or {}
        can = entry.get("canephora") or {}
        rows.append({
            "code": geo_code,
            "state": geo_name,
            "arabica_t":       float(ara.get("production_tons",  0) or 0),
            "canephora_t":     float(can.get("production_tons",  0) or 0),
            "arabica_yield":   float(ara.get("yield_kg_per_ha",  0) or 0),
            "canephora_yield": float(can.get("yield_kg_per_ha",  0) or 0),
        })

    # Brasile totale (da national_latest)
    if isinstance(national, dict):
        ara_br = national.get("arabica") or {}
        can_br = national.get("canephora") or {}
        rows.append({
            "code": "BR", "state": "Brasil",
            "arabica_t":       float(ara_br.get("production_tons", 0) or 0),
            "canephora_t":     float(can_br.get("production_tons", 0) or 0),
            "arabica_yield":   float(ara_br.get("yield_kg_per_ha", 0) or 0),
            "canephora_yield": float(can_br.get("yield_kg_per_ha", 0) or 0),
        })

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["total_t"] = df["arabica_t"] + df["canephora_t"]
    df["period_label"] = str(period_label)
    return df if df["total_t"].sum() > 0 else None


@st.cache_data(ttl=3600, show_spinner=False)
def _mongo_comex(country: str = "BR") -> dict | None:
    """
    Estrae serie storiche Comex Stat da MongoDB.
    Restituisce dict con chiavi: recent_series, destinations, transport_modes.
    """
    doc = get_latest_doc("raw_crops", "COMEX_STAT", country)
    if not doc:
        return None

    result: dict = {}

    # Serie mensile export
    recent = doc.get("recent_series", [])
    if recent:
        df = pd.DataFrame(recent)
        if "period" in df.columns:
            df["period"] = df["period"].astype(str)
            for col in ["total_exports_fob_usd", "total_exports_kg", "avg_fob_usd_per_kg"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            result["recent_series"] = df

    # Destinazioni
    dest_raw = doc.get("top_destinations", []) or doc.get("destinations_series", [])
    if dest_raw:
        result["destinations"] = dest_raw

    # Mix prodotto (grezzo/tostato/solubile)
    pm = doc.get("product_mix", {})
    if pm:
        result["product_mix"] = pm

    # Metriche derivate
    result["derived_metrics"] = doc.get("derived_metrics", {})
    result["latest_month"] = doc.get("latest_month", {})
    result["previous_month"] = doc.get("previous_month", {})
    result["summary_en"] = doc.get("summary_en", "")

    return result if result else None


def _sim_ibge() -> pd.DataFrame:
    """Dati simulati IBGE (4 stati focus + Brasil)."""
    rows = [
        {"code": "31", "state": "Minas Gerais",   "arabica_t": 1_750_000, "canephora_t":    15_000, "arabica_yield": 1_650, "canephora_yield": 900},
        {"code": "32", "state": "Espírito Santo",  "arabica_t":   185_000, "canephora_t":   630_000, "arabica_yield": 1_300, "canephora_yield": 1_800},
        {"code": "29", "state": "Bahia",           "arabica_t":   200_000, "canephora_t":   130_000, "arabica_yield": 1_450, "canephora_yield": 1_200},
        {"code": "11", "state": "Rondônia",        "arabica_t":     8_000, "canephora_t":   170_000, "arabica_yield":   900, "canephora_yield": 1_550},
        {"code": "BR", "state": "Brasil",          "arabica_t": 2_550_000, "canephora_t": 1_080_000, "arabica_yield": 1_530, "canephora_yield": 1_620},
    ]
    df = pd.DataFrame(rows)
    df["total_t"] = df["arabica_t"] + df["canephora_t"]
    df["period_label"] = "Simulato"
    return df


def _sim_comex() -> dict:
    """Dati simulati Comex (export mensili ultimi 18 mesi)."""
    rng = np.random.default_rng(_SEED)
    dates = pd.date_range(end=pd.Timestamp.today(), periods=18, freq="ME")
    base_fob = 280_000_000
    base_kg = 35_000_000
    fob = base_fob + rng.normal(0, 15_000_000, 18).cumsum() * 0.3
    kg = base_kg + rng.normal(0, 2_000_000, 18).cumsum() * 0.2
    df = pd.DataFrame({
        "period": [d.strftime("%Y-%m") for d in dates],
        "total_exports_fob_usd": np.clip(fob, 180_000_000, 450_000_000),
        "total_exports_kg": np.clip(kg, 22_000_000, 55_000_000),
        "avg_fob_usd_per_kg": fob / np.clip(kg, 1, None),
    })
    return {
        "recent_series": df,
        "destinations": [
            {"country": "USA",     "fob_usd": 45_000_000, "kg": 5_500_000},
            {"country": "Germany", "fob_usd": 38_000_000, "kg": 4_800_000},
            {"country": "Italy",   "fob_usd": 32_000_000, "kg": 4_100_000},
            {"country": "Japan",   "fob_usd": 28_000_000, "kg": 3_600_000},
            {"country": "Belgium", "fob_usd": 22_000_000, "kg": 2_900_000},
        ],
        "product_mix": {"green": 78.0, "roasted": 8.0, "soluble": 14.0},
        "derived_metrics": {
            "mom_exports_kg_pct": 2.4,
            "yoy_exports_kg_pct": -3.1,
            "avg_price_yoy_pct": 5.8,
        },
        "latest_month": {"period": dates[-1].strftime("%Y-%m"),
                         "total_exports_fob_usd": float(fob[-1]),
                         "total_exports_kg": float(kg[-1])},
        "previous_month": {"period": dates[-2].strftime("%Y-%m"),
                           "total_exports_fob_usd": float(fob[-2]),
                           "total_exports_kg": float(kg[-2])},
        "summary_en": "Dati Comex simulati.",
    }


# ============================================================================
# FETCH API (opzionali — richiedono yfinance/faostat)
# ============================================================================

@st.cache_data(ttl=86400, show_spinner=False)
def _api_oni() -> pd.Series | None:
    try:
        import requests
        res = requests.get(NOAA_ONI_URL, timeout=12)
        res.raise_for_status()
        lines = res.text.split("\n")
        data_lines = [l for l in lines if len(l.split()) >= 13
                      and l.split()[0].isdigit() and int(l.split()[0]) >= 1950]
        cols = ["Year"] + MONTH_NAMES
        df = pd.DataFrame([l.split()[:13] for l in data_lines],
                          columns=cols).set_index("Year").astype(float)
        df[df < -90] = np.nan
        df[df > 90] = np.nan
        stacked = df.stack()
        month_map = {m: i + 1 for i, m in enumerate(MONTH_NAMES)}
        idx = pd.MultiIndex.from_tuples(
            [(int(y), month_map[m]) for y, m in stacked.index],
            names=["Year", "Month"],
        )
        return pd.Series(stacked.values, index=idx).dropna()
    except Exception:
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def _api_soi() -> pd.Series | None:
    try:
        import requests
        res = requests.get(NOAA_SOI_URL, timeout=12)
        res.raise_for_status()
        lines = res.text.split("\n")
        data_lines = [l for l in lines if len(l.split()) >= 13
                      and l.split()[0].isdigit() and int(l.split()[0]) >= 1950]
        cols = ["Year"] + MONTH_NAMES
        df = pd.DataFrame([l.split()[:13] for l in data_lines],
                          columns=cols).set_index("Year").astype(float)
        df[df < -90] = np.nan
        df[df > 90] = np.nan
        stacked = df.stack()
        month_map = {m: i + 1 for i, m in enumerate(MONTH_NAMES)}
        idx = pd.MultiIndex.from_tuples(
            [(int(y), month_map[m]) for y, m in stacked.index],
            names=["Year", "Month"],
        )
        return pd.Series(stacked.values, index=idx).dropna()
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def _api_fires() -> pd.DataFrame | None:
    if not FIRMS_MAP_KEY:
        return None
    try:
        import requests
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{FIRMS_MAP_KEY}/VIIRS_SNPP_NRT/-75,-35,-33,6/5"
        res = requests.get(url, timeout=20)
        res.raise_for_status()
        df = pd.read_csv(io.StringIO(res.text))
        if df.empty or "latitude" not in df.columns:
            return None
        df["frp"] = pd.to_numeric(df.get("frp", 10), errors="coerce").fillna(10)
        return df
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def _api_prices() -> pd.DataFrame | None:
    try:
        import yfinance as yf
        raw_fx = yf.download("EURBRL=X", period="12y", interval="1mo",
                             auto_adjust=True, progress=False)
        if isinstance(raw_fx.columns, pd.MultiIndex):
            raw_fx.columns = raw_fx.columns.get_level_values(0)
        raw_fx = raw_fx[["Close"]].rename(columns={"Close": "fx_brl_per_eur"})
        raw_fx.index = pd.to_datetime(raw_fx.index).to_period("M").to_timestamp("M")
        raw_fx = raw_fx.reset_index().rename(columns={"index": "date", "Date": "date"})
        raw_fx["date"] = pd.to_datetime(raw_fx["date"])
        raw_fx = raw_fx.dropna(subset=["fx_brl_per_eur"])
    except Exception:
        raw_fx = pd.DataFrame(columns=["date", "fx_brl_per_eur"])

    try:
        import requests
        wb_res = requests.get(WB_MONTHLY_URL, timeout=20)
        wb_res.raise_for_status()
        content = io.BytesIO(wb_res.content)
        sheet_names = pd.ExcelFile(content).sheet_names
        raw = pd.read_excel(content, sheet_name=sheet_names[1], header=[3, 4])
        date_col = raw.columns[0]
        coffee_cols = [c for c in raw.columns
                       if "coffee" in str(c[0]).lower() or "coffee" in str(c[1]).lower()]
        coffee = raw[[date_col] + coffee_cols].copy().iloc[:, :3]
        coffee.columns = ["date_raw", "arabica_usd_kg", "robusta_usd_kg"]
        coffee["date"] = pd.to_datetime(
            coffee["date_raw"].astype(str).str.replace("M", "-", regex=False), errors="coerce")
        coffee = coffee.dropna(subset=["date"]).sort_values("date")
        coffee["date"] = coffee["date"] + pd.offsets.MonthEnd(0)
        USD_EUR = 0.93
        coffee["arabica_eur_kg"] = coffee["arabica_usd_kg"] * USD_EUR
        coffee["robusta_eur_kg"] = coffee["robusta_usd_kg"] * USD_EUR
        if not raw_fx.empty:
            raw_fx["date"] = raw_fx["date"] + pd.offsets.MonthEnd(0)
            coffee = pd.merge_asof(coffee.sort_values("date"), raw_fx.sort_values("date"),
                                   on="date", direction="nearest",
                                   tolerance=pd.Timedelta(days=45))
            coffee["fx_brl_per_eur"] = coffee["fx_brl_per_eur"].ffill(limit=3)
        else:
            coffee["fx_brl_per_eur"] = 5.5
        coffee = coffee.dropna(subset=["arabica_eur_kg", "fx_brl_per_eur"])
        coffee["arabica_brl_kg"] = coffee["arabica_usd_kg"] * (coffee["fx_brl_per_eur"] * USD_EUR)
        return coffee.tail(120).reset_index(drop=True)
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def _api_usda() -> pd.DataFrame | None:
    try:
        import requests
        api_key = os.getenv("USDA_API_KEY", "fweuVK6WJVHfLp95h2yYFd6sbHnL631RcY0OkGoG")
        headers = {"accept": "application/json", "X-Api-Key": api_key}
        attr_resp = requests.get(f"{USDA_BASE_URL}/commodityAttributes", headers=headers, timeout=10)
        attr_resp.raise_for_status()
        attr_map = {item["attributeId"]: item["attributeName"].strip() for item in attr_resp.json()}
        rows = []
        for year in range(2000, pd.Timestamp.today().year + 1):
            try:
                r = requests.get(
                    f"{USDA_BASE_URL}/commodity/{USDA_COMMODITY}/country/{USDA_COUNTRY}/year/{year}",
                    headers=headers, timeout=10)
                r.raise_for_status()
                for rec in r.json():
                    attr_name = attr_map.get(rec.get("attributeId"), "")
                    if attr_name in USDA_TARGET_ATTRS:
                        rows.append({"year": year, "attr_name": attr_name,
                                     "value": rec.get("value", 0), "month": rec.get("month", 0)})
            except Exception:
                continue
        if not rows:
            return None
        df_all = pd.DataFrame(rows)
        df_last = (df_all.sort_values("month")
                   .groupby(["year", "attr_name"])["value"].last()
                   .unstack("attr_name").reset_index())
        df_last = df_last.rename(columns=USDA_TARGET_ATTRS).sort_values("year").reset_index(drop=True)
        MT_TO_BAGS, ARA, ROB = 16.667, 0.72, 0.28
        for col_mt, ara_col, rob_col in [
            ("production_mt",    "arabica_bags",  "robusta_bags"),
            ("exports_mt",       "export_ara",    "export_rob"),
            ("ending_stocks_mt", "inventory_ara", "inventory_rob"),
        ]:
            if col_mt in df_last.columns:
                df_last[ara_col] = df_last[col_mt] * MT_TO_BAGS * ARA
                df_last[rob_col] = df_last[col_mt] * MT_TO_BAGS * ROB
            else:
                df_last[ara_col] = np.nan
                df_last[rob_col] = np.nan
        return df_last.dropna(subset=["arabica_bags"])
    except Exception:
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def _api_faostat() -> pd.DataFrame | None:
    try:
        import faostat as faostat_pkg
        df_raw = None
        for pars in [{"area": "21", "item": "656", "element": "2312,2413,2510"},
                     {"area": "21", "item": "656"}]:
            try:
                df_raw = faostat_pkg.get_data_df("QCL", pars=pars)
                if df_raw is not None and not df_raw.empty:
                    break
            except Exception:
                continue
        if df_raw is None or df_raw.empty:
            return None
        df_pivot = df_raw.pivot_table(
            index="Year", columns="Element", values="Value", aggfunc="first"
        ).reset_index()
        df_pivot.columns = [str(c).strip() for c in df_pivot.columns]
        return df_pivot
    except Exception:
        return None


# ============================================================================
# FUNZIONE DI CARICAMENTO DATI
# ============================================================================

def _load(name: str, country: str = "BR", use_api: bool = False):
    """
    Carica dati per 'name' con due modalità distinte:

    use_api=False (MongoDB):  MongoDB → Simulato
    use_api=True  (API):      API     → Simulato

    La modalità API NON usa MongoDB: mostra sempre dati live dalle fonti esterne.
    Fonti senza API diretta (conab, ibge, comex) usano sempre MongoDB → Simulato.
    """
    def _first(*fns):
        """Chiama le funzioni in ordine e restituisce il primo risultato non-None."""
        for fn in fns:
            result = fn()
            if result is not None:
                return result
        return None

    if name == "oni":
        if use_api:
            data = _first(_api_oni, _sim_oni)
        else:
            data = _first(lambda: _mongo_oni(country), _sim_oni)
        return data

    if name == "soi":
        # SOI non è in MongoDB — API o simulato
        if use_api:
            data = _first(_api_soi, _sim_soi)
        else:
            data = _sim_soi()
        return data

    if name == "fires":
        if use_api:
            data = _first(_api_fires, _sim_fires)
        else:
            data = _first(lambda: _mongo_fires(country), _sim_fires)
        return data

    if name == "prices":
        if use_api:
            data = _first(_api_prices, _sim_prices)
        else:
            data = _first(lambda: _mongo_prices(country), _sim_prices)
        return data

    if name == "usda":
        if use_api:
            data = _first(_api_usda, _sim_usda)
        else:
            data = _first(lambda: _mongo_usda(country), _sim_usda)
        return data

    if name == "faostat":
        if use_api:
            data = _first(_api_faostat, _sim_faostat)
        else:
            data = _first(lambda: _mongo_faostat(country), _sim_faostat)
        return data

    if name == "fertilizers":
        if use_api:
            data = _first(_api_fertilizers, _sim_fertilizers)
        else:
            # MongoDB ha fertilizer_series nel documento WB_PINK_SHEET
            data = _first(lambda: _mongo_fertilizers(country), _sim_fertilizers)
        return data

    # Le fonti seguenti non hanno API diretta: sempre MongoDB → Simulato
    if name == "conab":
        return _first(lambda: _mongo_conab(country), _sim_conab)

    if name == "ibge":
        return _first(lambda: _mongo_ibge(country), _sim_ibge)

    if name == "comex":
        return _first(lambda: _mongo_comex(country), _sim_comex)

    raise ValueError(f"Dataset sconosciuto: {name}")


# ============================================================================
# RENDER TAB 1 — ENSO (= render_tab_1 della standalone app)
# ============================================================================

def render_enso_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """Replica di render_tab_1: ONI + SOI + heatmap."""
    oni_series = _load("oni", country, use_api)
    soi_series = _load("soi", country, use_api)

    def _safe_delta(s):
        return s.iloc[-1] - s.iloc[-2] if len(s) >= 2 else None

    latest_oni = oni_series.iloc[-1]
    latest_soi = soi_series.iloc[-1]
    oni_delta = _safe_delta(oni_series)
    soi_delta = _safe_delta(soi_series)

    if latest_oni >= 0.5:
        phase, color = "🔴 EL NIÑO", "red"
        advice = "Rischio siccità al Nord/Amazzonia; Piogge eccessive al Sud."
        if latest_soi <= -7:
            advice += " (⚠️ EVENTO ACCOPPIATO CONFERMATO)"
    elif latest_oni <= -0.5:
        phase, color = "🔵 LA NIÑA", "blue"
        advice = "Rischio siccità al Sud; Forti piogge al Nord."
        if latest_soi >= 7:
            advice += " (⚠️ EVENTO ACCOPPIATO CONFERMATO)"
    else:
        phase, color = "🟢 NEUTRALE", "green"
        advice = "Nessuna anomalia ENSO grave attiva."

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ONI (Indice Oceanico)", f"{latest_oni:.2f} °C",
              f"{oni_delta:+.2f} °C" if oni_delta is not None else None, delta_color="inverse")
    c2.metric("SOI (Indice Atmosferico)", f"{latest_soi:.2f}",
              f"{soi_delta:+.2f}" if soi_delta is not None else None)
    c3.markdown(
        f"**Fase Attuale:**<br><span style='color:{color}; font-size:1.4em; font-weight:bold;'>{phase}</span>",
        unsafe_allow_html=True,
    )
    c4.info(f"**Impatto Agronomico:** {advice}")

    # SOI note — not stored in MongoDB, always from NOAA API or simulated
    if not use_api:
        st.info(
            "ℹ️ **SOI (Indice Atmosferico):** non è memorizzato nel database MongoDB. "
            "In modalità MongoDB viene mostrato un valore stimato/simulato. "
            "Per dati SOI reali, seleziona **API Diretta** nella barra laterale."
        )

    colA, colB = st.columns(2)
    try:
        with colA:
            st.markdown("#### Indice ONI (Oceanico)")
            oni_recent = oni_series.tail(36)
            x_vals = [f"{idx[0]}-{str(idx[1]).zfill(2)}" for idx in oni_recent.index]
            y_vals = oni_recent.values.tolist()

            fig_oni = go.Figure()
            fig_oni.add_trace(go.Scatter(
                x=x_vals + x_vals[::-1],
                y=[max(v, 0.5) for v in y_vals] + [0.5] * len(x_vals),
                fill="toself", fillcolor="rgba(220,50,50,0.25)",
                line=dict(width=0), hoverinfo="skip", showlegend=False,
            ))
            fig_oni.add_trace(go.Scatter(
                x=x_vals + x_vals[::-1],
                y=[min(v, -0.5) for v in y_vals] + [-0.5] * len(x_vals),
                fill="toself", fillcolor="rgba(50,100,220,0.25)",
                line=dict(width=0), hoverinfo="skip", showlegend=False,
            ))
            fig_oni.add_trace(go.Scatter(x=x_vals, y=y_vals, mode="lines+markers", name="ONI",
                                         line=dict(color="black", width=1.5), marker=dict(size=4)))
            fig_oni.add_hline(y=0.5, line_dash="dash", line_color="red",
                              annotation_text="El Niño (+0.5)")
            fig_oni.add_hline(y=-0.5, line_dash="dash", line_color="blue",
                              annotation_text="La Niña (-0.5)")
            fig_oni.update_yaxes(title_text="Anomalia Termica (°C)")
            fig_oni.update_xaxes(title_text="Periodo")
            fig_oni.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_oni, use_container_width=True, key=f"{key_prefix}_pc_1")
            st.caption("L'Oceanic Niño Index (ONI) misura le anomalie della temperatura superficiale del mare nel Pacifico centrale. Valori sopra +0.5°C indicano condizioni El Niño; sotto -0.5°C indicano La Niña.")

        with colB:
            st.markdown("#### Indice SOI (Atmosferico)")
            soi_recent = soi_series.tail(36)
            x_soi = [f"{idx[0]}-{str(idx[1]).zfill(2)}" for idx in soi_recent.index]
            bar_colors = ["blue" if val >= 0 else "red" for val in soi_recent.values]
            fig_soi = go.Figure(data=[go.Bar(x=x_soi, y=soi_recent.values,
                                             marker_color=bar_colors)])
            fig_soi.add_hline(y=7,  line_dash="dash", line_color="blue",
                              annotation_text="La Niña (+7)")
            fig_soi.add_hline(y=-7, line_dash="dash", line_color="red",
                              annotation_text="El Niño (-7)")
            fig_soi.update_yaxes(title_text="Indice SOI (adimensionale)")
            fig_soi.update_xaxes(title_text="Periodo")
            fig_soi.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_soi, use_container_width=True, key=f"{key_prefix}_pc_2")
            st.caption("Il Southern Oscillation Index (SOI) misura le differenze di pressione atmosferica nel Pacifico. Valori fortemente positivi confermano La Niña; valori fortemente negativi confermano El Niño.")

        st.markdown("#### Mappa Termica ONI Storica (10 Anni)")
        oni_10yr = oni_series.tail(120).reset_index()
        oni_10yr.columns = ["Year", "Month", "ONI"]
        oni_10yr["Year"] = oni_10yr["Year"].astype(int)
        oni_10yr["Month"] = oni_10yr["Month"].astype(int)
        pivot_oni = oni_10yr.pivot_table(index="Month", columns="Year", values="ONI", aggfunc="mean")
        pivot_oni = pivot_oni.sort_index(axis=1).reindex(range(1, 13))
        pivot_oni.index = [MONTH_NAMES[i - 1] for i in pivot_oni.index]
        fig_heat = px.imshow(pivot_oni, text_auto=".1f", aspect="auto",
                             color_continuous_scale="RdBu_r", color_continuous_midpoint=0)
        fig_heat.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0),
                               coloraxis_colorbar=dict(title="ONI (°C)"))
        st.plotly_chart(fig_heat, use_container_width=True, key=f"{key_prefix}_pc_3")
        st.caption("Valori ONI mensili su 10 anni. Celle rosse = mesi El Niño; celle blu = La Niña.")

    except Exception as e:
        st.warning(f"Errore visualizzazione ENSO: {e}")


# ============================================================================
# RENDER TAB 2 — INCENDI (= render_tab_2, con scatter_mapbox invece di geopandas)
# ============================================================================

def render_fires_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """
    Replica di render_tab_2.
    Il choropleth matplotlib/geopandas è sostituito con Plotly scatter_mapbox
    (non richiede geopandas).
    """
    fires = _load("fires", country, use_api)
    states_prod = _states_prod_df()

    # --- Mappa scatter_mapbox (sostituisce choropleth matplotlib) ---
    try:
        st.markdown("#### Rilevamenti Incendi NASA FIRMS — Ultimi 5 Giorni")
        if not fires.empty and "latitude" in fires.columns:
            fires_map = fires.copy()
            fires_map["frp"] = pd.to_numeric(fires_map.get("frp", 10), errors="coerce").fillna(10)
            fires_map["Intensità"] = fires_map["frp"].apply(
                lambda v: "Alta (>50 MW)" if v > 50 else "Media (10–50 MW)" if v >= 10 else "Bassa (<10 MW)"
            )
            color_map = {
                "Alta (>50 MW)":    "#B23A2E",
                "Media (10–50 MW)": "#C6842D",
                "Bassa (<10 MW)":   "#888888",
            }
            fig_map = px.scatter_mapbox(
                fires_map,
                lat="latitude", lon="longitude",
                color="Intensità",
                size="frp",
                size_max=18,
                opacity=0.80,
                color_discrete_map=color_map,
                mapbox_style="carto-positron",
                zoom=3,
                center={"lat": -15, "lon": -52},
                hover_data={"frp": True, "latitude": False, "longitude": False},
            )
            fig_map.update_layout(height=460, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_map, use_container_width=True, key=f"{key_prefix}_pc_4")
            st.caption(
                "Rilevamenti incendi satellite NASA VIIRS degli ultimi 5 giorni. "
                "Punti colorati per intensità FRP (Fire Radiative Power in MW). "
                "Ingrandisci per vedere le sovrapposizioni con le zone produttrici."
            )

            with st.expander("📖 Come leggere la mappa - Legenda FRP", expanded=False):
                col_l1, col_l2, col_l3 = st.columns(3)
                with col_l1:
                    st.markdown("**Punti Grigi (FRP < 10 MW)**")
                    st.caption("Focolai di bassa intensità: fuochi agricoli controllati. Impatto agronomico limitato.")
                with col_l2:
                    st.markdown("**Punti Arancio (FRP 10–50 MW)**")
                    st.caption("Incendi significativi. Rischio per le piantagioni nelle vicinanze.")
                with col_l3:
                    st.markdown("**Punti Rossi (FRP > 50 MW)**")
                    st.caption("Incendi di alta intensità. Impatto diretto certo sul raccolto in corso.")
        else:
            st.info("Nessun dato di incendio disponibile.")
    except Exception as e:
        st.warning(f"Errore mappa incendi: {e}")

    # --- Grafico mensile e per macro-regione (identico alla standalone) ---
    # Derive climate for wildfire_count trend
    oni = _load("oni", country, use_api)
    dates = pd.date_range(end=pd.Timestamp.today() + pd.offsets.MonthEnd(0),
                          periods=24, freq="ME")
    climate = _make_climate(pd.Series(dates), oni)

    try:
        colA, colB = st.columns(2)
        with colA:
            st.markdown("#### Conteggio Mensile Incendi (Ultimi 24 Mesi)")
            fig_ts = px.line(
                climate, x="date", y="wildfire_count",
                markers=True,
                color_discrete_sequence=[COLORS["danger"]],
                labels={"wildfire_count": "Numero Incendi (focolai/mese)", "date": "Data"},
            )
            fig_ts.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_ts, use_container_width=True, key=f"{key_prefix}_pc_5")
            st.caption("Conteggio mensile stimato dei focolari. I picchi si verificano nella stagione secca (giugno–settembre).")

        with colB:
            st.markdown("#### Hotspot per Macro-Regione")
            if not fires.empty and "latitude" in fires.columns:
                fires_c = fires.copy()

                def _lat_region(row):
                    lat, lon = row["latitude"], row["longitude"]
                    if lat > -4:             return "Nord"
                    elif lat > -15 and lon > -44: return "Nord-Est"
                    elif lat > -20 and lon < -52: return "Centro-Ovest"
                    elif lat > -25:          return "Sud-Est"
                    else:                    return "Sud"

                fires_c["macro_region"] = fires_c.apply(_lat_region, axis=1)
                reg_counts = fires_c["macro_region"].value_counts().reset_index()
                reg_counts.columns = ["Regione", "Conteggio"]
                fig_bar = px.bar(reg_counts, x="Regione", y="Conteggio", color="Regione",
                                 color_discrete_sequence=px.colors.qualitative.Pastel)
                fig_bar.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
                st.plotly_chart(fig_bar, use_container_width=True, key=f"{key_prefix}_pc_6")
                st.caption("Rilevamenti incendi aggregati per macro-regione geografica del Brasile.")
            else:
                st.info("Nessun incendio disponibile per aggregazione regionale.")
    except Exception as e:
        st.warning(f"Errore grafico incendi: {e}")


# ============================================================================
# RENDER TAB 4 — PREZZI (= render_tab_4 della standalone app)
# ============================================================================

def render_prices_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """Replica di render_tab_4: arabica/robusta, spread, base-100+FX z-score, annuale."""
    prices = _load("prices", country, use_api)
    if prices.empty:
        st.warning("Dati prezzi non disponibili.")
        return

    try:
        fx_now = float(prices["fx_brl_per_eur"].iloc[-1]) if not prices.empty else 0.0
        st.metric("Tasso di Cambio Attuale BRL/EUR", f"R$ {fx_now:.2f}",
                  help="BRL per 1 EUR (da BCB PTAX / yfinance).")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Prezzi Arabica & Robusta (EUR/kg)")
            figA = make_subplots(specs=[[{"secondary_y": True}]])
            figA.add_trace(go.Scatter(x=prices["date"], y=prices["arabica_eur_kg"],
                                      name="Arabica (€)", line=dict(color=COLORS["arabica"])),
                           secondary_y=False)
            figA.add_trace(go.Scatter(x=prices["date"], y=prices["robusta_eur_kg"],
                                      name="Robusta (€)", line=dict(color=COLORS["robusta"])),
                           secondary_y=True)
            figA.update_yaxes(title_text="Arabica (EUR/kg)", secondary_y=False)
            figA.update_yaxes(title_text="Robusta (EUR/kg)", secondary_y=True)
            figA.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(figA, use_container_width=True, key=f"{key_prefix}_pc_7")
            st.caption("Prezzi storici Arabica e Robusta in EUR/kg. Fonte: World Bank Pink Sheet / simulato.")

        with c2:
            st.markdown("#### Spread Arabica vs Robusta con Media Mobile a 3 Mesi")
            pc = prices.copy()
            pc["spread"] = pc["arabica_eur_kg"] - pc["robusta_eur_kg"]
            pc["ma_3"] = pc["spread"].rolling(window=3).mean()
            figS = go.Figure()
            figS.add_trace(go.Bar(x=pc["date"], y=pc["spread"],
                                  name="Differenziale Prezzi",
                                  marker_color="#8c564b", opacity=0.6))
            figS.add_trace(go.Scatter(x=pc["date"], y=pc["ma_3"],
                                      mode="lines", name="Media Mobile 3 Mesi",
                                      line=dict(color="red", width=2)))
            figS.update_yaxes(title_text="Differenziale (EUR/kg)")
            figS.update_xaxes(title_text="Data")
            figS.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(figS, use_container_width=True, key=f"{key_prefix}_pc_8")
            st.caption("Premio di prezzo dell'Arabica sull'Robusta in EUR/kg. Barre = differenziale mensile; linea rossa = media mobile 3 mesi.")

        # Base-100 normalizzato + Z-score FX
        st.markdown("#### Prezzo Arabica: BRL/kg vs EUR/kg a Confronto")
        px_c = prices[["date", "arabica_brl_kg", "arabica_eur_kg", "fx_brl_per_eur"]].copy().reset_index(drop=True)
        px_c["brl_idx"] = (px_c["arabica_brl_kg"] / px_c["arabica_brl_kg"].iloc[0]) * 100
        px_c["eur_idx"] = (px_c["arabica_eur_kg"] / px_c["arabica_eur_kg"].iloc[0]) * 100
        px_c["fx_roll_mean"] = px_c["fx_brl_per_eur"].rolling(12, min_periods=3).mean()
        px_c["fx_roll_std"]  = px_c["fx_brl_per_eur"].rolling(12, min_periods=3).std()
        px_c["fx_zscore"] = (px_c["fx_brl_per_eur"] - px_c["fx_roll_mean"]) \
                            / px_c["fx_roll_std"].replace(0, np.nan)
        bar_colors_fx = ["#3E7B58" if (z == z and z > 1) else "#BDBDBD"
                         for z in px_c["fx_zscore"].fillna(0)]

        figFX = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.65, 0.35], vertical_spacing=0.08,
            subplot_titles=("Andamento Prezzi Normalizzati (Base 100)",
                            "Z-Score FX BRL/EUR - Rolling 12 Mesi"),
        )
        dates_list = px_c["date"].tolist()
        brl_vals   = px_c["brl_idx"].tolist()
        eur_vals   = px_c["eur_idx"].tolist()

        for i in range(len(dates_list) - 1):
            eur_adv = eur_vals[i] < brl_vals[i]
            fill_col = "rgba(62,123,88,0.18)" if eur_adv else "rgba(178,58,46,0.12)"
            figFX.add_trace(go.Scatter(
                x=[dates_list[i], dates_list[i + 1], dates_list[i + 1], dates_list[i]],
                y=[brl_vals[i],   brl_vals[i + 1],   eur_vals[i + 1],   eur_vals[i]],
                fill="toself", fillcolor=fill_col,
                mode="lines", line=dict(width=0, color=fill_col),
                hoverinfo="skip", showlegend=False,
            ), row=1, col=1)

        figFX.add_trace(go.Scatter(
            x=px_c["date"], y=px_c["brl_idx"],
            name="Arabica BRL/kg (Base 100)",
            line=dict(color="#1A5EA8", width=2),
        ), row=1, col=1)
        figFX.add_trace(go.Scatter(
            x=px_c["date"], y=px_c["eur_idx"],
            name="Arabica EUR/kg (Base 100)",
            line=dict(color="#4A2F1D", width=2, dash="dot"),
        ), row=1, col=1)
        figFX.add_trace(go.Bar(
            x=px_c["date"], y=px_c["fx_zscore"],
            marker_color=bar_colors_fx, name="Z-Score FX BRL/EUR",
        ), row=2, col=1)
        figFX.add_hline(y=1,  line_dash="dash", line_color="#3E7B58",
                        annotation_text="+1σ EUR forte", row=2, col=1)
        figFX.add_hline(y=0,  line_dash="dot",  line_color="#AAAAAA", row=2, col=1)
        figFX.add_hline(y=-1, line_dash="dash", line_color="#B23A2E",
                        annotation_text="−1σ", row=2, col=1)
        figFX.update_yaxes(title_text="Indice (Base 100)", row=1, col=1)
        figFX.update_yaxes(title_text="Z-Score",           row=2, col=1)
        figFX.update_xaxes(title_text="Data",              row=2, col=1)
        figFX.update_layout(height=560, margin=dict(l=0, r=0, t=50, b=0),
                            plot_bgcolor="rgba(0,0,0,0)",
                            legend=dict(orientation="h", y=1.06, x=0),
                            hovermode="x unified")
        st.plotly_chart(figFX, use_container_width=True, key=f"{key_prefix}_pc_9")
        st.caption(
            "📊 Pannello superiore: andamento normalizzato (Base 100) del prezzo Arabica in BRL/kg (blu) "
            "e EUR/kg (marrone tratteggiato). 🟢 Zone verdi = EUR forte sul BRL (favorevole all'acquisto europeo). "
            "Pannello inferiore: Z-score rolling 12 mesi del cambio BRL/EUR. Barre verdi (Z > +1σ) = finestre storicamente favorevoli."
        )

        st.markdown("#### Prezzo Medio Annuo Arabica vs Media Decennale")
        pr_annual = prices.copy()
        pr_annual["year"] = pd.to_datetime(pr_annual["date"]).dt.year
        annual_avg = pr_annual.groupby("year")["arabica_eur_kg"].mean().reset_index()
        annual_avg.columns = ["year", "avg_price"]
        overall_mean = annual_avg["avg_price"].mean()
        fig_ann = go.Figure()
        fig_ann.add_trace(go.Bar(x=annual_avg["year"], y=annual_avg["avg_price"],
                                 name="Prezzo Medio Annuo", marker_color=COLORS["arabica"]))
        fig_ann.add_hline(y=overall_mean, line_dash="dash", line_color="grey",
                          annotation_text=f"Media 10 anni: {overall_mean:.2f} €/kg")
        fig_ann.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0),
                               yaxis_title="EUR/kg", xaxis_title="Anno")
        st.plotly_chart(fig_ann, use_container_width=True, key=f"{key_prefix}_pc_10")
        st.caption("Prezzo medio annuo Arabica per anno vs. media del periodo. Gli anni sopra la media seguono spesso shock di offerta (siccità, gelate).")

    except Exception as e:
        st.warning(f"Errore grafici prezzi: {e}")


# ============================================================================
# RENDER TAB 5 — PRODUTTIVITÀ (= render_tab_5 della standalone app)
# ============================================================================

def render_yields_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """Replica di render_tab_5: USDA stacked bars, esportazioni/scorte, bubble chart, FAOSTAT, pie."""
    usda = _load("usda", country, use_api)
    faostat_df = _load("faostat", country, use_api)
    states_mock = _load("conab", country, use_api)

    if states_mock is not None:
        st.caption("📋 Dati CONAB: tabella stati da ultimo report CONAB (MongoDB). "
                   "Per dati aggiornati ri-eseguire il workflow n8n CONAB.")

    # FAOSTAT storico
    with st.expander("📊 FAOSTAT Dati Storici a Lungo Termine (1990–presente)"):
        if faostat_df is not None and not faostat_df.empty and "Year" in faostat_df.columns:
            try:
                fao_plot = faostat_df.copy()
                area_col = (next((c for c in fao_plot.columns
                                  if "area" in c.lower() and "harvest" in c.lower()), None)
                            or next((c for c in fao_plot.columns if "area" in c.lower()), None))
                prod_col = next((c for c in fao_plot.columns if "production" in c.lower()), None)
                year_col = "Year" if "Year" in fao_plot.columns else fao_plot.columns[0]
                if prod_col:
                    fig_fao = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_fao.add_trace(go.Bar(x=fao_plot[year_col], y=fao_plot[prod_col],
                                             name="Produzione (t)",
                                             marker_color="#4A2F1D", opacity=0.75),
                                      secondary_y=False)
                    if area_col:
                        fig_fao.add_trace(go.Scatter(x=fao_plot[year_col], y=fao_plot[area_col],
                                                     name="Superficie Raccolta (ha)",
                                                     line=dict(color="#3E7B58", width=2.5)),
                                          secondary_y=True)
                    fig_fao.update_yaxes(title_text="Produzione (t)", secondary_y=False)
                    fig_fao.update_yaxes(title_text="Superficie Raccolta (ha)", secondary_y=True)
                    fig_fao.update_xaxes(title_text="Anno")
                    fig_fao.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0),
                                          plot_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig_fao, use_container_width=True, key=f"{key_prefix}_pc_11")
                    st.caption("Fonte: FAOSTAT QCL, Brasile (area=21), Caffè verde (item=656). "
                               "I cicli lunghi riflettono il pattern biennale anni-on/off.")
            except Exception as e:
                st.warning(f"Errore grafico FAOSTAT: {e}")
        else:
            st.info("Dati FAOSTAT non disponibili.")

    try:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Produzione Totale Brasiliana di Caffè per Anno")
            figP = go.Figure()
            figP.add_trace(go.Bar(x=usda["year"], y=usda["arabica_bags"],
                                  name="Arabica", marker_color=COLORS["arabica"]))
            figP.add_trace(go.Bar(x=usda["year"], y=usda["robusta_bags"],
                                  name="Robusta", marker_color=COLORS["robusta"]))
            figP.update_layout(barmode="stack", height=380,
                               margin=dict(l=0, r=0, t=10, b=0),
                               yaxis=dict(title="Sacchi da 60 kg", tickformat=".2s"))
            st.plotly_chart(figP, use_container_width=True, key=f"{key_prefix}_pc_12")
            st.caption("Produzione totale in sacchi da 60 kg, suddivisa Arabica/Robusta. Il Brasile alterna anni di alta e bassa produzione in un ciclo biennale. Fonte: USDA PSD.")

        with c2:
            st.markdown("#### Volumi Annui Esportazioni vs Scorte Finali")
            figE = make_subplots(specs=[[{"secondary_y": True}]])
            total_exp = usda["export_ara"].fillna(0) + usda["export_rob"].fillna(0)
            total_inv = usda["inventory_ara"].fillna(0) + usda["inventory_rob"].fillna(0)
            figE.add_trace(go.Scatter(x=usda["year"], y=total_exp, name="Esportazioni Totali",
                                      mode="lines+markers",
                                      line=dict(color="#2ca02c")), secondary_y=False)
            figE.add_trace(go.Scatter(x=usda["year"], y=total_inv, name="Scorte",
                                      mode="lines",
                                      line=dict(color="#1f77b4", dash="dash")), secondary_y=True)
            figE.update_yaxes(title_text="Esportazioni (sacchi 60 kg)", secondary_y=False,
                              tickformat=".2s")
            figE.update_yaxes(title_text="Scorte Finali (sacchi 60 kg)", secondary_y=True,
                              tickformat=".2s")
            figE.update_xaxes(title_text="Anno")
            figE.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(figE, use_container_width=True, key=f"{key_prefix}_pc_13")
            st.caption("Quando le esportazioni aumentano mentre le scorte scendono, la filiera logistica si assottiglia — indicatore anticipatore della pressione sui prezzi.")

        c3, c4 = st.columns(2)
        with c3:
            st.markdown("#### Efficienza Resa vs Volume Produzione — Top 10 Regioni")
            if states_mock is not None and not states_mock.empty:
                top10 = states_mock.nlargest(10, "production_bags").copy()
                figS = px.scatter(
                    top10, x="yield", y="production_bags",
                    color="state", size="production_bags", size_max=55,
                    text="state",
                    labels={"yield": "Resa (sacchi/ettaro)",
                            "production_bags": "Produzione Totale (sacchi da 60 kg)",
                            "state": "Stato"},
                    color_discrete_sequence=px.colors.qualitative.Bold,
                )
                figS.update_traces(textposition="top center", textfont=dict(size=10),
                                   marker=dict(opacity=0.85, line=dict(width=1, color="white")))
                figS.update_layout(height=480, margin=dict(l=0, r=0, t=20, b=0),
                                   plot_bgcolor="rgba(0,0,0,0)", showlegend=False,
                                   yaxis=dict(tickformat=".2s",
                                              title="Produzione Totale (sacchi da 60 kg)"),
                                   xaxis=dict(title="Resa (sacchi/ettaro)"))
                st.plotly_chart(figS, use_container_width=True, key=f"{key_prefix}_pc_14")
                st.caption("Le 10 principali regioni produttrici brasiliane. Ogni bolla = uno stato; dimensione = volume; asse X = resa per ettaro.")

        with c4:
            st.markdown("#### Quota di Mercato Arabica / Robusta (Ultimo Anno)")
            latest = usda.iloc[-1]
            figD = px.pie(
                values=[latest["arabica_bags"], latest["robusta_bags"]],
                names=["Arabica", "Robusta"], hole=0.5,
                color_discrete_sequence=[COLORS["arabica"], COLORS["robusta"]],
            )
            figD.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(figD, use_container_width=True, key=f"{key_prefix}_pc_15")
            st.caption("Quota Arabica vs Robusta nell'ultimo anno. Il Brasile è storicamente ~70-75% Arabica, ma la quota Robusta cresce per la sua resistenza alla siccità.")

    except Exception as e:
        st.warning(f"Errore grafici produttività: {e}")


# ============================================================================
# RENDER TAB 6 — PRECIPITAZIONI (= render_tab_6 della standalone app)
# ============================================================================

def render_climate_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """Replica di render_tab_6: deficit pluviometrico mensile + per stato."""
    states_mock = _load("conab", country, use_api)
    oni = _load("oni", country, use_api)
    dates = pd.date_range(end=pd.Timestamp.today() + pd.offsets.MonthEnd(0),
                          periods=24, freq="ME")
    climate = _make_climate(pd.Series(dates), oni)

    with st.expander("📖 Cos'è il Deficit Pluviometrico?", expanded=True):
        st.markdown("""
**Formula:**
> Deficit (%) = ((Pioggia_media_storica − Pioggia_osservata) / Pioggia_media_storica) × 100

| Deficit | Impatto |
|---------|---------|
| < 10%  | 🟢 Normale |
| 10–20% | 🟠 Stress moderato |
| > 20%  | 🔴 Stress severo — rischio calo resa |

**Periodi critici:** ottobre–novembre (fioritura) e dicembre–gennaio (sviluppo frutto).
        """)

    try:
        colA, colB = st.columns(2)
        with colA:
            st.markdown("#### Deficit Pluviometrico Mensile (Ultimi 24 Mesi)")
            recent = climate.tail(24).copy()

            def _color(v):
                return COLORS["safe"] if v < 10 else COLORS["warning"] if v <= 20 else COLORS["danger"]

            bar_colors = recent["rainfall_deficit_pct"].apply(_color).tolist()
            recent["rolling_12"] = recent["rainfall_deficit_pct"].rolling(12, min_periods=1).mean()
            fig = go.Figure()
            fig.add_trace(go.Bar(x=recent["date"], y=recent["rainfall_deficit_pct"],
                                 marker_color=bar_colors, name="Deficit %"))
            fig.add_trace(go.Scatter(x=recent["date"], y=recent["rolling_12"],
                                     mode="lines", line=dict(color="black", width=3),
                                     name="Media Mobile 12 Mesi"))
            fig.add_hline(y=10, line_dash="dot", line_color=COLORS["warning"],
                          annotation_text="Soglia stress moderato (10%)",
                          annotation_position="top left")
            fig.add_hline(y=20, line_dash="dot", line_color=COLORS["danger"],
                          annotation_text="Soglia stress severo (20%)",
                          annotation_position="top left")
            fig.update_layout(
                height=420, margin=dict(l=0, r=0, t=30, b=0),
                yaxis=dict(title="Deficit Pluviometrico (%)", ticksuffix="%",
                           range=[0, max(recent["rainfall_deficit_pct"].max() * 1.15, 25)]),
                xaxis=dict(title="Mese"),
                legend=dict(orientation="h", y=1.05, x=0),
            )
            st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_pc_16")
            st.caption("Verde < 10% = normale; arancio 10–20% = stress moderato; rosso > 20% = stress severo. Valori derivati dal modello ENSO-ONI.")

        with colB:
            st.markdown("#### Deficit Pluviometrico Medio per Stato")
            if states_mock is not None and not states_mock.empty:
                rng = np.random.default_rng(_SEED + 10)
                sp = states_mock.copy()
                sp["avg_deficit"] = rng.uniform(4.0, 25.0, len(sp))
                sp = sp.sort_values("avg_deficit", ascending=True)
                figH = px.bar(sp, x="avg_deficit", y="state", orientation="h",
                              color="avg_deficit", color_continuous_scale="RdYlGn_r",
                              hover_data={"avg_deficit": ":.1f"},
                              labels={"avg_deficit": "Deficit (%)", "state": "Stato"})
                figH.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0),
                                   xaxis=dict(title="Deficit Annuo Medio (%)", ticksuffix="%"),
                                   coloraxis_colorbar=dict(title="Deficit (%)"))
                st.plotly_chart(figH, use_container_width=True, key=f"{key_prefix}_pc_17")
                st.caption("Deficit pluviometrico annuo medio (%) per stato produttore. Rosso = più critico.")
    except Exception as e:
        st.warning(f"Errore grafico precipitazioni: {e}")


# ============================================================================
# RENDER TAB 7 — IBGE + COMEX EXPORT
# ============================================================================

def render_ibge_comex_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """Produzione per stato (IBGE) + export Brasile (Comex Stat)."""
    ibge = _load("ibge", country, use_api)
    comex = _load("comex", country, use_api)

    # ---- IBGE ----
    st.markdown("### IBGE SIDRA — Produzione per Stato")
    if ibge is not None and not ibge.empty:
        period = ibge["period_label"].iloc[0] if "period_label" in ibge.columns else ""
        if period:
            st.caption(f"Periodo di riferimento: **{period}**")

        try:
            # Escludi il totale Brasil per il grafico a barre per stato
            states_only = ibge[ibge["code"] != "BR"].copy()
            brasil_row = ibge[ibge["code"] == "BR"]

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### Produzione per Stato — Arabica vs Robusta (Canephora)")
                fig_bar = go.Figure()
                fig_bar.add_trace(go.Bar(
                    x=states_only["state"], y=states_only["arabica_t"],
                    name="Arabica", marker_color=COLORS["arabica"],
                ))
                fig_bar.add_trace(go.Bar(
                    x=states_only["state"], y=states_only["canephora_t"],
                    name="Canephora (Robusta)", marker_color=COLORS["robusta"],
                ))
                fig_bar.update_layout(
                    barmode="group", height=360,
                    margin=dict(l=0, r=0, t=20, b=0),
                    yaxis=dict(title="Produzione (tonnellate)", tickformat=".2s"),
                    legend=dict(orientation="h", y=1.05),
                )
                st.plotly_chart(fig_bar, use_container_width=True, key=f"{key_prefix}_pc_18")
                st.caption("Fonte IBGE SIDRA LSPA, tavola 6588. MG domina arabica; ES è il principale produttore di canephora.")

            with col2:
                st.markdown("#### Resa Media per Stato (kg/ha)")
                fig_yield = go.Figure()
                fig_yield.add_trace(go.Bar(
                    x=states_only["state"], y=states_only["arabica_yield"],
                    name="Arabica kg/ha", marker_color=COLORS["arabica"], opacity=0.85,
                ))
                fig_yield.add_trace(go.Bar(
                    x=states_only["state"], y=states_only["canephora_yield"],
                    name="Canephora kg/ha", marker_color=COLORS["robusta"], opacity=0.85,
                ))
                fig_yield.update_layout(
                    barmode="group", height=360,
                    margin=dict(l=0, r=0, t=20, b=0),
                    yaxis=dict(title="Resa (kg/ha)"),
                    legend=dict(orientation="h", y=1.05),
                )
                st.plotly_chart(fig_yield, use_container_width=True, key=f"{key_prefix}_pc_19")
                st.caption("Resa media in kg per ettaro. ES ha la resa canephora più alta; RO ha bassa resa arabica ma volumi canephora in crescita.")

            # Totale Brasil
            if not brasil_row.empty:
                ara_tot = float(brasil_row["arabica_t"].iloc[0])
                can_tot = float(brasil_row["canephora_t"].iloc[0])
                total_tot = ara_tot + can_tot
                col3, col4 = st.columns(2)
                with col3:
                    st.markdown("#### Mix Arabica / Canephora — Brasile")
                    fig_pie = px.pie(
                        values=[ara_tot, can_tot],
                        names=["Arabica", "Canephora"],
                        hole=0.5,
                        color_discrete_sequence=[COLORS["arabica"], COLORS["robusta"]],
                    )
                    fig_pie.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0))
                    st.plotly_chart(fig_pie, use_container_width=True, key=f"{key_prefix}_pc_20")
                    st.caption(f"Totale Brasile: {total_tot:,.0f} t  "
                               f"({ara_tot/total_tot*100:.0f}% Arabica, "
                               f"{can_tot/total_tot*100:.0f}% Canephora)")
        except Exception as e:
            st.warning(f"Errore grafici IBGE: {e}")
    else:
        st.info("Dati IBGE non disponibili in MongoDB. Avviare il workflow n8n IBGE SIDRA.")

    st.divider()

    # ---- COMEX ----
    st.markdown("### Comex Stat — Export Caffè Brasile")
    if comex:
        try:
            recent_df = comex.get("recent_series")
            dest_list = comex.get("destinations", [])
            pm = comex.get("product_mix", {})
            dm = comex.get("derived_metrics", {})

            # Metriche rapide
            if dm:
                m1, m2, m3 = st.columns(3)
                mom_kg = dm.get("mom_exports_kg_pct", 0)
                yoy_kg = dm.get("yoy_exports_kg_pct", 0)
                price_yoy = dm.get("avg_price_yoy_pct", 0) or dm.get("avg_price_mom_pct", 0)
                m1.metric("Export kg MoM", f"{mom_kg:+.1f}%",
                          delta_color="normal" if mom_kg >= 0 else "inverse")
                m2.metric("Export kg YoY", f"{yoy_kg:+.1f}%",
                          delta_color="normal" if yoy_kg >= 0 else "inverse")
                m3.metric("Prezzo medio YoY", f"{price_yoy:+.1f}%",
                          delta_color="normal" if price_yoy >= 0 else "inverse")

            col1, col2 = st.columns(2)
            with col1:
                if recent_df is not None and not recent_df.empty and "total_exports_fob_usd" in recent_df.columns:
                    st.markdown("#### Valore Export Mensile (USD FOB)")
                    fig_exp = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_exp.add_trace(
                        go.Bar(x=recent_df["period"], y=recent_df["total_exports_fob_usd"],
                               name="FOB USD", marker_color=COLORS["highlight"], opacity=0.8),
                        secondary_y=False,
                    )
                    if "total_exports_kg" in recent_df.columns:
                        fig_exp.add_trace(
                            go.Scatter(x=recent_df["period"], y=recent_df["total_exports_kg"],
                                       name="Kg", mode="lines+markers",
                                       line=dict(color=COLORS["arabica"], width=2)),
                            secondary_y=True,
                        )
                    fig_exp.update_yaxes(title_text="USD FOB", secondary_y=False, tickformat=".2s")
                    fig_exp.update_yaxes(title_text="Kg esportati", secondary_y=True, tickformat=".2s")
                    fig_exp.update_xaxes(tickangle=-45)
                    fig_exp.update_layout(height=380, margin=dict(l=0, r=0, t=20, b=40),
                                          legend=dict(orientation="h", y=1.05))
                    st.plotly_chart(fig_exp, use_container_width=True, key=f"{key_prefix}_pc_21")
                    st.caption("Export mensile caffè brasiliano in valore (barre, USD FOB) e volume (linea, kg). Fonte: Comex Stat.")

            with col2:
                if dest_list:
                    st.markdown("#### Top Destinazioni Export (Ultimo Mese)")
                    dest_df = pd.DataFrame(dest_list[:8])
                    val_col = next((c for c in dest_df.columns if "fob" in c.lower() or "value" in c.lower()), None)
                    name_col = next((c for c in dest_df.columns if "country" in c.lower() or "destination" in c.lower() or "dest" in c.lower()), None)
                    if val_col and name_col:
                        dest_df = dest_df.sort_values(val_col, ascending=True)
                        fig_dest = px.bar(dest_df, x=val_col, y=name_col, orientation="h",
                                          color_discrete_sequence=[COLORS["arabica"]],
                                          labels={val_col: "USD FOB", name_col: "Paese"})
                        fig_dest.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
                        st.plotly_chart(fig_dest, use_container_width=True, key=f"{key_prefix}_pc_22")
                        st.caption("Principali mercati di destinazione del caffè brasiliano. USA e Germania guidano storicamente le importazioni.")

            # Mix prodotto — MongoDB stores nested dicts {green: {share_kg_pct, kg, ...}}
            if pm:
                def _extract_mix_share(val) -> float:
                    """Extract a numeric share from either a plain number or nested dict."""
                    if isinstance(val, dict):
                        return float(val.get("share_kg_pct") or val.get("kg") or 0)
                    try:
                        return float(val or 0)
                    except (TypeError, ValueError):
                        return 0.0

                green_v  = _extract_mix_share(pm.get("green",   0))
                roasted_v = _extract_mix_share(pm.get("roasted", 0))
                soluble_v = _extract_mix_share(pm.get("soluble", 0))

                if green_v + roasted_v + soluble_v > 0:
                    st.markdown("#### Mix Prodotto Esportato")
                    labels = ["Caffè Verde", "Tostato", "Solubile"]
                    values = [green_v, roasted_v, soluble_v]
                    fig_pm = px.pie(values=values, names=labels, hole=0.4,
                                    color_discrete_sequence=["#4A2F1D", "#C6842D", "#3E7B58"])
                    fig_pm.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
                    st.plotly_chart(fig_pm, use_container_width=True, key=f"{key_prefix}_pc_23")
                    st.caption("Il caffè verde (non tostato) domina le esportazioni brasiliane — ~78%. La quota solubile è in lenta crescita.")

        except Exception as e:
            st.warning(f"Errore grafici Comex: {e}")
    else:
        st.info("Dati Comex non disponibili in MongoDB. Avviare il workflow n8n Comex Stat.")


# ============================================================================
# RENDER TAB 8 — PORTI (congestione AIS + Comex transport modes)
# ============================================================================

@st.cache_data(ttl=3600, show_spinner=False)
def _mongo_ports(country: str = "BR") -> dict | None:
    """Legge AISSTREAM_PORT_CONGESTION da raw_geo."""
    doc = get_latest_doc("raw_geo", "AISSTREAM_PORT_CONGESTION", country)
    if not doc:
        return None
    ports = doc.get("ports", [])
    if not isinstance(ports, list):
        ports = []
    return {
        "ports": ports,
        "total_anchored": int(doc.get("total_anchored_vessels", 0)),
        "congested_count": int(doc.get("congested_ports_count", 0)),
        "top_congested_port": doc.get("top_congested_port"),
        "snapshot_seconds": doc.get("snapshot_seconds", 0),
        "collected_at": doc.get("collected_at", ""),
        "signals": doc.get("signals", []),
        "summary_en": doc.get("summary_en", ""),
    }


def _sim_ports() -> dict:
    """Dati simulati per demo quando AIS non è disponibile."""
    rng = np.random.default_rng(_SEED + 5)
    port_names = [p[0] for p in PORTS]
    anchored = [int(rng.integers(0, 5)) for _ in port_names]
    ports_list = [
        {"port_name": name, "anchored_vessels_count": anc,
         "average_sog": round(float(rng.uniform(0, 1.5)), 2)}
        for name, anc in zip(port_names, anchored)
    ]
    total = sum(anchored)
    top = max(ports_list, key=lambda p: p["anchored_vessels_count"])
    signals = []
    if total == 0:
        signals = ["no_port_queue_detected"]
    elif total >= 8:
        signals = ["port_queue_detected", "regional_export_delay_risk"]
    elif total > 0:
        signals = ["port_queue_detected"]
    return {
        "ports": ports_list,
        "total_anchored": total,
        "congested_count": sum(1 for p in ports_list if p["anchored_vessels_count"] > 0),
        "top_congested_port": top if top["anchored_vessels_count"] > 0 else None,
        "snapshot_seconds": 300,
        "collected_at": "",
        "signals": signals,
        "summary_en": f"Simulazione: {total} navi ancorate nelle zone portuali monitorate.",
    }


def render_ports_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """Tab congestione portuale: AIS snapshot + Comex transport modes."""
    port_data = _mongo_ports(country)
    is_simulated = port_data is None
    if is_simulated:
        port_data = _sim_ports()
        st.info("ℹ️ Dati AIS non disponibili in MongoDB — dati simulati. "
                "Avvia il workflow n8n **Port Congestion** per dati reali.")

    # Comex transport modes (solo MongoDB)
    comex = _mongo_comex(country)

    total = port_data["total_anchored"]
    congested = port_data["congested_count"]
    top = port_data.get("top_congested_port")

    # KPI row
    col1, col2, col3 = st.columns(3)
    risk_color = "#B23A2E" if total >= 8 else "#C6842D" if total >= 3 else "#3E7B58"
    col1.metric("Navi Ancorate Totali", total,
                help="Numero di navi ferme/ancorate nelle zone di attesa portuali (AIS snapshot).")
    col2.metric("Porti con Code", congested)
    if top and top.get("anchored_vessels_count", 0) > 0:
        col3.metric("Porto Più Congestionato",
                    top.get("port_name", "—"),
                    f"{top.get('anchored_vessels_count', 0)} navi")
    else:
        col3.metric("Congestione Porto Più Alto", "—", "Nessuna coda rilevata")

    # Severity banner
    if total == 0:
        st.success("✅ Nessuna coda rilevata nei porti monitorati.")
    elif total < 3:
        st.warning(f"⚠️ Leggera congestione: {total} navi ancorate.")
    elif total < 8:
        st.warning(f"⚠️ Congestione moderata: {total} navi ancorate in {congested} porto/i.")
    else:
        st.error(f"🔴 Congestione elevata: {total} navi ancorate — rischio ritardo esportazioni.")

    # Grafico barre per porto
    try:
        ports_list = port_data.get("ports", [])
        if ports_list:
            df_ports = pd.DataFrame(ports_list)
            name_col = next((c for c in ["port_name", "port", "name"] if c in df_ports.columns), None)
            anc_col = next((c for c in ["anchored_vessels_count", "anchored", "vessels"] if c in df_ports.columns), None)
            if name_col and anc_col:
                df_ports[anc_col] = pd.to_numeric(df_ports[anc_col], errors="coerce").fillna(0)
                df_ports = df_ports.sort_values(anc_col, ascending=False)
                bar_colors = [COLORS["danger"] if v >= 6 else COLORS["warning"] if v >= 3
                              else COLORS["safe"] if v > 0 else "#CCCCCC"
                              for v in df_ports[anc_col]]
                fig_ports = go.Figure(go.Bar(
                    x=df_ports[name_col], y=df_ports[anc_col],
                    marker_color=bar_colors,
                    text=df_ports[anc_col].astype(int),
                    textposition="outside",
                ))
                fig_ports.update_layout(
                    height=360, margin=dict(l=0, r=0, t=20, b=0),
                    yaxis=dict(title="Navi Ancorate", dtick=1),
                    xaxis=dict(title="Porto"),
                    plot_bgcolor="rgba(0,0,0,0)",
                )
                fig_ports.add_hline(y=3, line_dash="dash", line_color=COLORS["warning"],
                                    annotation_text="Soglia moderata (3)")
                fig_ports.add_hline(y=6, line_dash="dash", line_color=COLORS["danger"],
                                    annotation_text="Soglia elevata (6)")
                st.plotly_chart(fig_ports, use_container_width=True, key=f"{key_prefix}_pc_24")
                st.caption(
                    "Numero di navi in attesa/ancorate per porto (snapshot AIS). "
                    "Verde = libero; arancio = moderato (≥3); rosso = elevato (≥6). "
                    "Code significative aumentano i tempi di spedizione di 1–3 giorni per nave."
                )

            # Average SOG (speed over ground) se disponibile
            sog_col = next((c for c in ["average_sog", "sog", "avg_sog"] if c in df_ports.columns), None)
            if sog_col:
                df_sog = df_ports[[name_col, sog_col]].copy()
                df_sog[sog_col] = pd.to_numeric(df_sog[sog_col], errors="coerce").fillna(0)
                fig_sog = px.bar(df_sog, x=name_col, y=sog_col,
                                 color=sog_col, color_continuous_scale="RdYlGn",
                                 labels={name_col: "Porto", sog_col: "SOG medio (nodi)"},
                                 title="Velocità Media SOG per Porto (nodi)")
                fig_sog.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig_sog, use_container_width=True, key=f"{key_prefix}_pc_25")
                st.caption("SOG (Speed Over Ground): navi che si muovono lentamente (<1 nodo) indicano attesa attiva.")
    except Exception as e:
        st.warning(f"Errore grafico porti: {e}")

    # Comex transport modes
    if comex:
        tm = comex.get("transport_modes_latest") or (
            (comex.get("transport_series") or [{}])[-1].get("breakdown", [])
        )
        if tm:
            st.divider()
            st.markdown("### Modalità Trasporto Export — Comex Stat")
            try:
                df_tm = pd.DataFrame(tm)
                via_col = next((c for c in ["via", "transport_mode", "mode"] if c in df_tm.columns), None)
                fob_col = next((c for c in ["fob_usd", "share_fob_pct"] if c in df_tm.columns), None)
                kg_col = next((c for c in ["kg", "share_kg_pct"] if c in df_tm.columns), None)
                if via_col and (fob_col or kg_col):
                    metric_col = fob_col or kg_col
                    df_tm[metric_col] = pd.to_numeric(df_tm[metric_col], errors="coerce").fillna(0)
                    fig_tm = px.pie(df_tm, values=metric_col, names=via_col,
                                    hole=0.4,
                                    color_discrete_sequence=px.colors.qualitative.Pastel,
                                    title="Ripartizione per Modalità Trasporto")
                    fig_tm.update_layout(height=340, margin=dict(l=0, r=0, t=50, b=0))
                    st.plotly_chart(fig_tm, use_container_width=True, key=f"{key_prefix}_pc_26")
                    st.caption("Il trasporto marittimo domina le esportazioni di caffè brasiliano. "
                               "Fonte: Comex Stat, modalità di trasporto (via).")
            except Exception as e:
                st.warning(f"Errore grafico transport modes: {e}")

    # Summary
    summary = port_data.get("summary_en", "")
    if summary:
        with st.expander("📋 Riepilogo Snapshot AIS"):
            st.caption(summary)
            sigs = port_data.get("signals", [])
            if sigs:
                st.markdown("**Segnali rilevati:** " + ", ".join(f"`{s}`" for s in sigs))


# ============================================================================
# RENDER TAB 9 — FERTILIZZANTI (API World Bank Pink Sheet)
# ============================================================================

@st.cache_data(ttl=86400, show_spinner=False)
def _api_fertilizers() -> pd.DataFrame | None:
    """
    Scarica prezzi fertilizzanti dal World Bank Pink Sheet (stesso Excel prezzi).
    Estrae: DAP (diammonium phosphate), Urea (bulk), Potassium chloride (MOP).
    Prezzi in USD/tonnellata metrica.
    """
    try:
        import requests
        res = requests.get(WB_MONTHLY_URL, timeout=30)
        res.raise_for_status()
        content = io.BytesIO(res.content)
        xls = pd.ExcelFile(content)

        # Sheet "Monthly Prices" — same as coffee prices
        raw = pd.read_excel(content, sheet_name=xls.sheet_names[1], header=[3, 4])
        date_col = raw.columns[0]

        # Find fertilizer columns
        fert_targets = {
            "DAP": "dap_usd_t",
            "Urea": "urea_usd_t",
            "Potassium": "mop_usd_t",
        }
        found_cols: dict[str, str] = {}
        for col in raw.columns:
            col_str = str(col[0]) + " " + str(col[1])
            for keyword, out_name in fert_targets.items():
                if keyword.lower() in col_str.lower() and out_name not in found_cols.values():
                    found_cols[col] = out_name
                    break

        if not found_cols:
            return None

        df = raw[[date_col] + list(found_cols.keys())].copy()
        df.columns = ["date_raw"] + list(found_cols.values())
        df["date"] = pd.to_datetime(
            df["date_raw"].astype(str).str.replace("M", "-", regex=False), errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date")
        df["date"] = df["date"] + pd.offsets.MonthEnd(0)
        for col in found_cols.values():
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df[["date"] + list(found_cols.values())].dropna(how="all").tail(120).reset_index(drop=True)
    except Exception:
        return None


def _sim_fertilizers() -> pd.DataFrame:
    """Dati simulati fertilizzanti."""
    rng = np.random.default_rng(_SEED + 7)
    dates = pd.date_range(end=pd.Timestamp.today() + pd.offsets.MonthEnd(0),
                          periods=120, freq="ME")
    n = len(dates)
    dap  = 400 + np.cumsum(rng.normal(0, 15, n))
    urea = 280 + np.cumsum(rng.normal(0, 12, n))
    mop  = 320 + np.cumsum(rng.normal(0, 10, n))
    return pd.DataFrame({
        "date": dates,
        "dap_usd_t":  np.clip(dap, 200, 900),
        "urea_usd_t": np.clip(urea, 150, 700),
        "mop_usd_t":  np.clip(mop, 200, 650),
    })


def render_fertilizers_tab(country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """
    Prezzi fertilizzanti (DAP, Urea, Potash/MOP).
    MongoDB mode: legge fertilizer_series dal documento WB_PINK_SHEET (ora salvato dal workflow).
    API mode: scarica direttamente l'Excel WB Pink Sheet.
    """
    fert_df = _load("fertilizers", country, use_api)
    # normalizza nome colonna potash (MongoDB usa potash_usd_t, sim usa mop_usd_t)
    if fert_df is not None and "potash_usd_t" in fert_df.columns and "mop_usd_t" not in fert_df.columns:
        fert_df = fert_df.rename(columns={"potash_usd_t": "mop_usd_t"})

    is_simulated = (fert_df is _sim_fertilizers() or
                    (fert_df is not None and "Simulato" in str(fert_df.get("source_label", ""))))
    # segnala la sorgente
    if not use_api:
        wb_doc = get_latest_doc("raw_prices", "WB_PINK_SHEET", country)
        if wb_doc and wb_doc.get("fertilizer_available"):
            st.success("✅ Dati fertilizzanti caricati da MongoDB (WB Pink Sheet — workflow n8n).")
        else:
            st.info("ℹ️ Fertilizzanti non ancora in MongoDB — il workflow n8n WB Pink Sheet deve girare "
                    "almeno una volta con la nuova versione per popolare `fertilizer_series`. "
                    "Attualmente visualizzazione simulata.")
    else:
        st.success("✅ Dati fertilizzanti caricati dall'API World Bank Pink Sheet (Excel live).")

    # KPI row
    if fert_df is not None and not fert_df.empty:
        latest = fert_df.iloc[-1]
        prev = fert_df.iloc[-2] if len(fert_df) >= 2 else latest
        cols = [c for c in ["dap_usd_t", "urea_usd_t", "mop_usd_t"] if c in fert_df.columns]
        labels = {"dap_usd_t": "DAP (USD/t)", "urea_usd_t": "Urea (USD/t)", "mop_usd_t": "MOP/Potassio (USD/t)"}
        metric_cols = st.columns(len(cols))
        for mc, col in zip(metric_cols, cols):
            val = float(latest.get(col, 0) or 0)
            delta = float((latest.get(col, 0) or 0) - (prev.get(col, 0) or 0))
            mc.metric(labels.get(col, col), f"${val:,.0f}", f"{delta:+.0f} $/t MoM")

    if fert_df is None:
        st.warning("Dati fertilizzanti non disponibili.")
        return

    try:
        avail_cols = [c for c in ["dap_usd_t", "urea_usd_t", "mop_usd_t"] if c in fert_df.columns]
        col_labels = {"dap_usd_t": "DAP", "urea_usd_t": "Urea", "mop_usd_t": "MOP/Potassio"}
        colors_fert = {"dap_usd_t": "#4A2F1D", "urea_usd_t": "#1A5EA8", "mop_usd_t": "#3E7B58"}

        colA, colB = st.columns(2)
        with colA:
            st.markdown("#### Prezzi Fertilizzanti (USD/t) — Ultimi 10 Anni")
            fig_fert = go.Figure()
            for col in avail_cols:
                fig_fert.add_trace(go.Scatter(
                    x=fert_df["date"], y=fert_df[col],
                    name=col_labels.get(col, col),
                    line=dict(color=colors_fert.get(col, "#999"), width=2),
                    mode="lines",
                ))
            fig_fert.update_layout(
                height=400, margin=dict(l=0, r=0, t=10, b=0),
                yaxis=dict(title="USD / tonnellata metrica"),
                legend=dict(orientation="h", y=1.05),
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_fert, use_container_width=True, key=f"{key_prefix}_pc_27")
            st.caption(
                "**DAP** (fosfato diammonico) è il fertilizzante principale per la fioritura del caffè. "
                "**Urea** è la fonte di azoto più economica. "
                "**MOP** (cloreto de potássio) supporta la qualità del chicco."
            )

        with colB:
            if len(avail_cols) >= 2:
                st.markdown("#### Variazione YoY Prezzi Fertilizzanti (%)")
                fert_yoy = fert_df.copy()
                for col in avail_cols:
                    fert_yoy[f"{col}_yoy"] = fert_yoy[col].pct_change(12) * 100
                fig_yoy = go.Figure()
                for col in avail_cols:
                    yoy_col = f"{col}_yoy"
                    if yoy_col in fert_yoy.columns:
                        vals = fert_yoy[yoy_col].tolist()
                        bar_c = ["#B23A2E" if v > 0 else "#3E7B58" for v in
                                 [v if v == v else 0 for v in vals]]
                        fig_yoy.add_trace(go.Bar(
                            x=fert_yoy["date"], y=fert_yoy[yoy_col],
                            name=col_labels.get(col, col),
                            opacity=0.75,
                        ))
                fig_yoy.add_hline(y=0, line_dash="dot", line_color="#999")
                fig_yoy.update_layout(
                    barmode="group", height=400,
                    margin=dict(l=0, r=0, t=10, b=0),
                    yaxis=dict(title="Variazione YoY (%)", ticksuffix="%"),
                    legend=dict(orientation="h", y=1.05),
                )
                st.plotly_chart(fig_yoy, use_container_width=True, key=f"{key_prefix}_pc_28")
                st.caption("Variazione annuale (YoY) dei prezzi fertilizzanti. "
                           "Aumenti sostenuti (>20% YoY) impattano i margini dei produttori brasiliani.")

        # Indice aggregato fertilizzanti vs prezzo arabica
        prices_df = _load("prices", country, use_api)
        if prices_df is not None and not prices_df.empty and avail_cols:
            st.markdown("#### Costo Fertilizzanti vs Prezzo Arabica — Pressione sui Margini")
            try:
                fert_idx = fert_df.copy()
                for col in avail_cols:
                    fert_idx[col] = pd.to_numeric(fert_idx[col], errors="coerce")
                fert_idx["fert_composite"] = fert_idx[avail_cols].mean(axis=1)
                fert_idx["date"] = pd.to_datetime(fert_idx["date"])
                prices_m = prices_df.copy()
                prices_m["date"] = pd.to_datetime(prices_m["date"])
                merged = pd.merge_asof(
                    prices_m.sort_values("date"),
                    fert_idx[["date", "fert_composite"]].sort_values("date"),
                    on="date", direction="nearest", tolerance=pd.Timedelta(days=45)
                ).dropna(subset=["fert_composite"])
                if not merged.empty:
                    # Normalize both series to base 100
                    merged["ara_idx"] = (merged["arabica_eur_kg"] / merged["arabica_eur_kg"].iloc[0]) * 100
                    # USD/t → approximate to EUR/kg scale (*0.93/1000) then base 100
                    fert_eur_kg = merged["fert_composite"] * 0.93 / 1000
                    merged["fert_idx"] = (fert_eur_kg / fert_eur_kg.iloc[0]) * 100
                    fig_margin = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_margin.add_trace(go.Scatter(
                        x=merged["date"], y=merged["ara_idx"],
                        name="Arabica (Base 100)", line=dict(color=COLORS["arabica"], width=2),
                    ), secondary_y=False)
                    fig_margin.add_trace(go.Scatter(
                        x=merged["date"], y=merged["fert_idx"],
                        name="Fertilizzanti Composito (Base 100)",
                        line=dict(color=COLORS["danger"], width=2, dash="dot"),
                    ), secondary_y=True)
                    fig_margin.update_yaxes(title_text="Arabica (Base 100)", secondary_y=False)
                    fig_margin.update_yaxes(title_text="Fertilizzanti (Base 100)", secondary_y=True)
                    fig_margin.update_layout(
                        height=400, margin=dict(l=0, r=0, t=10, b=0),
                        legend=dict(orientation="h", y=1.05),
                        plot_bgcolor="rgba(0,0,0,0)",
                    )
                    st.plotly_chart(fig_margin, use_container_width=True, key=f"{key_prefix}_pc_29")
                    st.caption(
                        "Confronto normalizzato (Base 100) tra prezzo arabica e costo composito fertilizzanti. "
                        "Quando i fertilizzanti crescono più velocemente dell'arabica, i margini dei produttori si comprimono."
                    )
            except Exception:
                pass
    except Exception as e:
        st.warning(f"Errore grafici fertilizzanti: {e}")


# ============================================================================
# INTERFACCIA PUBBLICA per app.py
# ============================================================================

# Mapping tab_name → render function
_TAB_RENDERERS = {
    "enso":         render_enso_tab,
    "fires":        render_fires_tab,
    "prices":       render_prices_tab,
    "yields":       render_yields_tab,
    "climate":      render_climate_tab,
    "ibge_comex":   render_ibge_comex_tab,
    "ports":        render_ports_tab,
    "fertilizers":  render_fertilizers_tab,
}

# Tab da mostrare nel Dashboard Visiva e relativi nomi
DASHBOARD_TABS = [
    ("🌦️ Clima & ENSO",              "enso"),
    ("🔥 Incendi",                     "fires"),
    ("📈 Prezzi di Mercato",           "prices"),
    ("🌾 Produttività Raccolti",       "yields"),
    ("🌧️ Precipitazioni",             "climate"),
    ("📦 IBGE + Comex Export",        "ibge_comex"),
    ("⚓ Porti & Trasporti",          "ports"),
    ("🌱 Fertilizzanti",              "fertilizers"),
]


def render_dashboard_tab(tab_key: str, country: str = "BR", use_api: bool = False, key_prefix: str = "") -> None:
    """
    Punto d'ingresso per Dashboard Visiva.
    tab_key: uno tra "enso", "fires", "prices", "yields", "climate"
    """
    fn = _TAB_RENDERERS.get(tab_key)
    if fn is None:
        st.warning(f"Tab '{tab_key}' non riconosciuto.")
        return
    fn(country=country, use_api=use_api, key_prefix=key_prefix)


# Backward-compat per _render_charts_section esistente in app.py
CHART_REGISTRY: dict[str, callable] = {}
DASHBOARD_SOURCES: dict[str, list[str]] = {}


def build_chart(source: str, country: str = "BR",
                use_api_fallback: bool = False) -> tuple[object | None, str]:
    """Mantenuto per retrocompatibilità — non più il percorso principale."""
    return None, f"Usa render_dashboard_tab() invece di build_chart('{source}')."
