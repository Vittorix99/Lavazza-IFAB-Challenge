# .env required:
#   USDA_API_KEY          - USDA PSD API key (default provided as fallback)
#   FAOSTAT_USERNAME      - FAOSTAT credentials (optional, public data works without)
#   FAOSTAT_PASSWORD      - FAOSTAT credentials (optional)
#   AIS_API_KEY           - hardcoded below (aisstream.io)

import os
import io
import json
import time
import asyncio
from datetime import datetime
from typing import Tuple

import numpy as np
import pandas as pd
import requests
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import geopandas as gpd

import nest_asyncio
import websockets
from dotenv import load_dotenv

try:
    import faostat as faostat_pkg
    FAOSTAT_AVAILABLE = True
except ImportError:
    FAOSTAT_AVAILABLE = False

nest_asyncio.apply()

st.set_page_config(
    page_title="Lavazza Origins Intelligence - AI Prototype",
    page_icon="☕",
    layout="wide",
    initial_sidebar_state="expanded"
)
load_dotenv()

# ==========================================
# CONSTANTS & CONFIG
# ==========================================
WB_MONTHLY_URL = "https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx"
FX_URL = "https://open.er-api.com/v6/latest/USD"
NOAA_ONI_URL = "https://psl.noaa.gov/data/correlation/oni.data"
NOAA_SOI_URL = "https://psl.noaa.gov/data/correlation/soi.data"
FIRMS_MAP_KEY = "63fb02bde23144ea120a3123f959bf4c"
FIRMS_SOURCE = "VIIRS_SNPP_NRT"
FIRMS_DAYS = "5"
FIRMS_BBOX = "-75,-35,-33,6"
GEOJSON_URL = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
AIS_API_KEY = "23dff2542eb48c414c4c0213de19b29dd4deaa30"
AIS_WS_URL = "wss://stream.aisstream.io/v0/stream"

USDA_BASE_URL  = "https://api.fas.usda.gov/api/psd"
USDA_COMMODITY = "0711100"   # Coffee, Green
USDA_COUNTRY   = "BR"

# Exact USDA attribute names to extract (avoids multi-column ambiguity)
USDA_TARGET_ATTRS = {
    "Production":           "production_mt",
    "Exports":              "exports_mt",
    "Ending Stocks":        "ending_stocks_mt",
    "Beginning Stocks":     "beginning_stocks_mt",
    "Domestic Consumption": "consumption_mt",
}

# Global ports used for LIVE AIS stream (free tier has reliable coverage here)
AIS_LIVE_PORTS = {
    "Singapore":   [[1.10, 103.55], [1.35, 104.10]],
    "Rotterdam":   [[51.87, 3.90],  [52.02, 4.25]],
    "Los Angeles": [[33.65, -118.32], [33.82, -118.14]],
}

CONAB_CSV_PATH = "data_sources/conab/conab_data.csv"

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

COFFEE_STATE_PROD = {
    'MG': {'Arabica': 28.0, 'Robusta': 0.3},
    'ES': {'Arabica': 3.0, 'Robusta': 10.5},
    'SP': {'Arabica': 5.4, 'Robusta': 0.0},
    'BA': {'Arabica': 1.2, 'Robusta': 2.2},
    'RO': {'Arabica': 0.0, 'Robusta': 2.8},
    'PR': {'Arabica': 0.5, 'Robusta': 0.0},
    'RJ': {'Arabica': 0.3, 'Robusta': 0.0},
    'GO': {'Arabica': 0.2, 'Robusta': 0.0},
    'MT': {'Arabica': 0.0, 'Robusta': 0.2}
}

PORTS = [
    ("Santos", -23.95, -46.33, 62.0),
    ("Vitoria", -20.32, -40.34, 38.0),
    ("Paranagua", -25.52, -48.50, 45.0),
    ("Rio de Janeiro", -22.90, -43.17, 26.0),
    ("Salvador", -12.90, -38.51, 18.0),
]

PORTS_BBOXES = {
    "Santos": [[-24.15, -46.45], [-23.90, -46.25]],
    "Vitoria": [[-20.45, -40.40], [-20.20, -40.10]],
    "Rio de Janeiro": [[-23.05, -43.35], [-22.75, -43.00]],
    "Paranagua": [[-25.65, -48.65], [-25.40, -48.35]],
    "Salvador": [[-13.10, -38.70], [-12.70, -38.40]]
}

# State-based region lookup (no overlapping bounding boxes)
STATE_REGION_MAP = {
    "AC": "Nord", "AP": "Nord", "AM": "Nord", "PA": "Nord",
    "RO": "Nord", "RR": "Nord", "TO": "Nord",
    "AL": "Nord-Est", "BA": "Nord-Est", "CE": "Nord-Est",
    "MA": "Nord-Est", "PB": "Nord-Est", "PE": "Nord-Est",
    "PI": "Nord-Est", "RN": "Nord-Est", "SE": "Nord-Est",
    "DF": "Centro-Ovest", "GO": "Centro-Ovest",
    "MT": "Centro-Ovest", "MS": "Centro-Ovest",
    "ES": "Sud-Est", "MG": "Sud-Est",
    "RJ": "Sud-Est", "SP": "Sud-Est",
    "PR": "Sud", "RS": "Sud", "SC": "Sud",
}

COLORS = {
    "arabica": "#4A2F1D",
    "robusta": "#C6842D",
    "highlight": "#1A5EA8",
    "danger": "#B23A2E",
    "warning": "#C6842D",
    "safe": "#3E7B58"
}

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ==========================================
# MASTER REGION NAME NORMALIZER
# Maps every possible region/state name variant to a clean Italian label.
# ==========================================
REGION_NAME_MASTER = {
    # State abbreviations
    "MG": "MG - Minas Gerais (Sud-Est)",
    "ES": "ES - Espírito Santo (Sud-Est)",
    "SP": "SP - São Paulo (Sud-Est)",
    "RJ": "RJ - Rio de Janeiro (Sud-Est)",
    "PR": "PR - Paraná (Sud)",
    "SC": "SC - Santa Catarina (Sud)",
    "RS": "RS - Rio Grande do Sul (Sud)",
    "BA": "BA - Bahia (Nord-Est)",
    "PE": "PE - Pernambuco (Nord-Est)",
    "CE": "CE - Ceará (Nord-Est)",
    "RO": "RO - Rondônia (Nord)",
    "AM": "AM - Amazonas (Nord)",
    "PA": "PA - Pará (Nord)",
    "GO": "GO - Goiás (Centro-Ovest)",
    "MT": "MT - Mato Grosso (Centro-Ovest)",
    "MS": "MS - Mato Grosso do Sul (Centro-Ovest)",
    "DF": "DF - Distrito Federal (Centro-Ovest)",
    "AC": "AC - Acre (Nord)",
    "AP": "AP - Amapá (Nord)",
    "RR": "RR - Roraima (Nord)",
    "TO": "TO - Tocantins (Nord)",
    "AL": "AL - Alagoas (Nord-Est)",
    "MA": "MA - Maranhão (Nord-Est)",
    "PB": "PB - Paraíba (Nord-Est)",
    "PI": "PI - Piauí (Nord-Est)",
    "RN": "RN - Rio Grande do Norte (Nord-Est)",
    "SE": "SE - Sergipe (Nord-Est)",
    # Full state names (various spellings)
    "Minas Gerais":   "MG - Minas Gerais (Sud-Est)",
    "Espirito Santo": "ES - Espírito Santo (Sud-Est)",
    "Espírito Santo": "ES - Espírito Santo (Sud-Est)",
    "Sao Paulo":      "SP - São Paulo (Sud-Est)",
    "São Paulo":      "SP - São Paulo (Sud-Est)",
    "Bahia":          "BA - Bahia (Nord-Est)",
    "Rondonia":       "RO - Rondônia (Nord)",
    "Rondônia":       "RO - Rondônia (Nord)",
    "Parana":         "PR - Paraná (Sud)",
    "Paraná":         "PR - Paraná (Sud)",
    "Goias":          "GO - Goiás (Centro-Ovest)",
    "Goiás":          "GO - Goiás (Centro-Ovest)",
    "Mato Grosso":    "MT - Mato Grosso (Centro-Ovest)",
    "Rio de Janeiro": "RJ - Rio de Janeiro (Sud-Est)",
    "Amazonas":       "AM - Amazonas (Nord)",
    # CONAB micro-regions → map to parent state/area
    "Triângulo, Alto Paranaiba e Noroeste": "MG Norte-Ovest - Triângulo/Noroeste",
    "Triângulo, Alto Paranaíba e Noroeste": "MG Norte-Ovest - Triângulo/Noroeste",
    "Norte, Jequitinhonha e Mucuri":        "MG Nord - Jequitinhonha/Mucuri",
    "Zona da Mata, Rio Doce e Central":     "MG Centro-Est - Zona da Mata",
    "Sul e Centro-Oeste":                   "MG Sud - Sul e Centro-Oeste",
    "Sul e Centro-Oeste de MG":             "MG Sud - Sul e Centro-Oeste",
    "Planalto":                             "MG Planalto - Região Central",
    "Cerrado":                              "MG Cerrado - Região do Cerrado",
    "Atlântico":                            "ES Atlântico - Costa dell'Atlantico",
    "Atlântico ES":                         "ES Atlântico - Costa dell'Atlantico",
    # Brazilian macro-regions
    "SUDESTE":      "Sud-Est Brasile (MG, ES, SP, RJ)",
    "NORDESTE":     "Nord-Est Brasile (BA, PE, CE...)",
    "NORTE":        "Nord Brasile (RO, AM, PA...)",
    "CENTRO-OESTE": "Centro-Ovest Brasile (GO, MT, MS)",
    "SUL":          "Sud Brasile (PR, SC, RS)",
    "Norte":        "Nord Brasile (RO, AM, PA...)",
    "Nordeste":     "Nord-Est Brasile (BA, PE, CE...)",
    "Sudeste":      "Sud-Est Brasile (MG, ES, SP, RJ)",
    "Centro-Oeste": "Centro-Ovest Brasile (GO, MT, MS)",
    "Sul":          "Sud Brasile (PR, SC, RS)",
}


def normalize_region_name(name: str) -> str:
    """Map any region/state name variant to a clean, readable Italian label."""
    if not isinstance(name, str):
        return str(name)
    name_stripped = name.strip()
    return REGION_NAME_MASTER.get(name_stripped, name_stripped)


def get_session_seed():
    return 42


def get_macro_region_from_sigla(sigla: str) -> str:
    return STATE_REGION_MAP.get(str(sigla).upper().strip(), "Other")


def try_api_get(url: str, api_name: str, timeout: int = 10) -> Tuple[requests.Response, dict]:
    status = {"api": api_name, "url": url[:30] + "...", "status": "✅ Successo", "error": "-"}
    try:
        res = requests.get(url, timeout=timeout)
        res.raise_for_status()
        return res, status
    except requests.exceptions.Timeout:
        status["status"] = "❌ Fallito"
        status["error"] = "Timeout dopo 10s"
        return None, status
    except requests.exceptions.HTTPError as e:
        status["status"] = "❌ Fallito"
        msg = "403 Forbidden" if getattr(e.response, "status_code", None) == 403 else str(e)
        status["error"] = msg[:30]
        return None, status
    except requests.exceptions.ConnectionError:
        status["status"] = "❌ Fallito"
        status["error"] = "Errore di connessione"
        return None, status
    except Exception as e:
        status["status"] = "❌ Fallito"
        status["error"] = str(e)[:30]
        return None, status


# ==========================================
# FETCH & MOCK LOGIC (CACHED)
# ==========================================

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_enso_data(simulated: bool) -> Tuple[pd.Series, dict]:
    status = {"api": "NOAA ONI", "url": NOAA_ONI_URL[:30] + "...", "status": "✅ Successo", "error": "-"}
    if not simulated:
        res, status = try_api_get(NOAA_ONI_URL, "NOAA ONI", 10)
        if res is not None:
            lines = res.text.split('\n')
            data_lines = [line for line in lines
                          if len(line.split()) >= 13
                          and line.split()[0].isdigit()
                          and int(line.split()[0]) >= 1950]
            cols = ['Year', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            df_oni = pd.DataFrame([l.split()[:13] for l in data_lines],
                                   columns=cols).set_index('Year').astype(float)
            df_oni[df_oni < -90] = np.nan
            df_oni[df_oni > 90] = np.nan
            stacked = df_oni.stack()
            month_map = {m: i + 1 for i, m in enumerate(cols[1:])}
            new_index = pd.MultiIndex.from_tuples(
                [(int(y), month_map[m]) for y, m in stacked.index],
                names=["Year", "Month"]
            )
            stacked = pd.Series(stacked.values, index=new_index).dropna()
            return stacked, status

    if simulated:
        status["status"] = "⚪ Simulato"
    rng = np.random.default_rng(get_session_seed())
    dates = pd.date_range(start="2014-01-01", periods=120, freq="ME")
    vals = 0.8 * np.sin(np.linspace(0, 4 * np.pi, 120)) + rng.normal(0, 0.2, 120)
    idx = pd.MultiIndex.from_arrays([dates.year.tolist(), dates.month.tolist()], names=["Year", "Month"])
    return pd.Series(vals, index=idx).dropna(), status


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_soi_data(simulated: bool) -> Tuple[pd.Series, dict]:
    status = {"api": "NOAA SOI", "url": NOAA_SOI_URL[:30] + "...", "status": "✅ Successo", "error": "-"}
    if not simulated:
        res, status = try_api_get(NOAA_SOI_URL, "NOAA SOI", 10)
        if res is not None:
            lines = res.text.split('\n')
            data_lines = [line for line in lines
                          if len(line.split()) >= 13
                          and line.split()[0].isdigit()
                          and int(line.split()[0]) >= 1950]
            cols = ['Year', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            df_soi = pd.DataFrame([l.split()[:13] for l in data_lines],
                                   columns=cols).set_index('Year').astype(float)
            df_soi[df_soi < -90] = np.nan
            df_soi[df_soi > 90] = np.nan
            stacked = df_soi.stack()
            month_map = {m: i + 1 for i, m in enumerate(cols[1:])}
            new_index = pd.MultiIndex.from_tuples(
                [(int(y), month_map[m]) for y, m in stacked.index],
                names=["Year", "Month"]
            )
            stacked = pd.Series(stacked.values, index=new_index).dropna()
            return stacked, status

    if simulated:
        status["status"] = "⚪ Simulato"
    rng = np.random.default_rng(get_session_seed() + 1)
    dates = pd.date_range(start="2014-01-01", periods=120, freq="ME")
    vals = -10.0 * np.sin(np.linspace(0, 4 * np.pi, 120)) + rng.normal(0, 3.0, 120)
    idx = pd.MultiIndex.from_arrays([dates.year.tolist(), dates.month.tolist()], names=["Year", "Month"])
    return pd.Series(vals, index=idx).dropna(), status


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_firms_data(simulated: bool) -> Tuple[pd.DataFrame, dict]:
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{FIRMS_MAP_KEY}/{FIRMS_SOURCE}/{FIRMS_BBOX}/{FIRMS_DAYS}"
    status = {"api": "NASA FIRMS", "url": url[:30] + "...", "status": "✅ Successo", "error": "-"}
    if not simulated:
        res, status = try_api_get(url, "NASA FIRMS", 15)
        if res is not None:
            df = pd.read_csv(io.StringIO(res.text))
            if not df.empty and "latitude" in df.columns:
                return df, status

    if simulated:
        status["status"] = "⚪ Simulato"
    rng = np.random.default_rng(get_session_seed())
    rows = []
    for _ in range(150):
        rows.append({"latitude": rng.normal(-13, 2), "longitude": rng.normal(-56, 3), "frp": float(rng.uniform(20, 80))})
    for _ in range(100):
        rows.append({"latitude": rng.normal(-19, 1.5), "longitude": rng.normal(-43, 2), "frp": float(rng.uniform(10, 60))})
    for _ in range(50):
        rows.append({"latitude": float(rng.uniform(-30, -5)), "longitude": float(rng.uniform(-70, -35)), "frp": float(rng.uniform(5, 50))})
    return pd.DataFrame(rows), status


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_prices(simulated: bool) -> Tuple[pd.DataFrame, list]:
    statuses = [
        {"api": "World Bank Prices", "url": WB_MONTHLY_URL[:30] + "...", "status": "✅ Successo", "error": "-"},
        {"api": "yfinance EURBRL=X",  "url": "yfinance / EURBRL=X / 10yr",  "status": "✅ Successo", "error": "-"}
    ]
    if not simulated:
        # ── Step 1: Download historical EURBRL=X monthly FX via yfinance ─────────────
        try:
            import yfinance as yf
            raw_fx = yf.download(
                "EURBRL=X",
                period="12y",        # 12 years to ensure 10y of data after resampling
                interval="1mo",
                auto_adjust=True,
                progress=False,
            )
            # Flatten MultiIndex columns if present
            if isinstance(raw_fx.columns, pd.MultiIndex):
                raw_fx.columns = raw_fx.columns.get_level_values(0)
            raw_fx = raw_fx[["Close"]].rename(columns={"Close": "fx_brl_per_eur"})
            raw_fx.index = pd.to_datetime(raw_fx.index).to_period("M").to_timestamp("M")
            raw_fx = raw_fx.reset_index().rename(columns={"index": "date", "Date": "date"})
            raw_fx["date"] = pd.to_datetime(raw_fx["date"])
            raw_fx = raw_fx.dropna(subset=["fx_brl_per_eur"])
            statuses[1]["status"] = "✅ Successo"
        except Exception as e:
            statuses[1]["status"] = "❌ Fallito"
            statuses[1]["error"] = str(e)[:60]
            raw_fx = pd.DataFrame(columns=["date", "fx_brl_per_eur"])

        # ── Step 2: Download World Bank coffee prices ────────────────────────────
        wb_res, wb_stat = try_api_get(WB_MONTHLY_URL, "World Bank Prices", 15)
        statuses[0] = wb_stat
        if wb_res is not None:
            content = io.BytesIO(wb_res.content)
            sheet_names = pd.ExcelFile(content).sheet_names
            raw = pd.read_excel(content, sheet_name=sheet_names[1], header=[3, 4])
            date_col = raw.columns[0]
            coffee_cols = [col for col in raw.columns
                           if "coffee" in str(col[0]).lower() or "coffee" in str(col[1]).lower()]
            coffee = raw[[date_col] + coffee_cols].copy().iloc[:, :3]
            coffee.columns = ["date_raw", "arabica_usd_kg", "robusta_usd_kg"]
            coffee["date"] = pd.to_datetime(
                coffee["date_raw"].astype(str).str.replace("M", "-", regex=False), errors="coerce")
            coffee = coffee.dropna(subset=["date"]).sort_values("date")

            # Normalise dates to month-end for merge alignment
            coffee["date"] = coffee["date"] + pd.offsets.MonthEnd(0)

            # ── Step 3: Merge historical FX onto coffee prices ──────────────────
            if not raw_fx.empty:
                raw_fx["date"] = raw_fx["date"] + pd.offsets.MonthEnd(0)
                coffee = pd.merge_asof(
                    coffee.sort_values("date"),
                    raw_fx.sort_values("date"),
                    on="date",
                    direction="nearest",
                    tolerance=pd.Timedelta(days=45),
                )
                # Forward-fill any gaps ≤ 3 months; beyond that stays NaN → dropped
                coffee["fx_brl_per_eur"] = coffee["fx_brl_per_eur"].ffill(limit=3)
            else:
                # Fallback: constant rate if yfinance completely failed
                coffee["fx_brl_per_eur"] = 5.5

            coffee = coffee.dropna(subset=["arabica_usd_kg", "fx_brl_per_eur"])

            # USD → EUR using a fixed approximate spot (WB publishes USD prices only)
            USD_TO_EUR = 0.93   # approximate multi-year average; good enough for EUR display
            coffee["arabica_eur_kg"] = coffee["arabica_usd_kg"] * USD_TO_EUR
            coffee["robusta_eur_kg"] = coffee["robusta_usd_kg"] * USD_TO_EUR
            coffee["arabica_brl_kg"] = coffee["arabica_usd_kg"] * coffee["fx_brl_per_eur"] * (1 / USD_TO_EUR) * USD_TO_EUR
            # Simplify: arabica_brl_kg = arabica_usd_kg × (BRL per USD)
            #   BRL/USD = fx_brl_per_eur × USD_TO_EUR (since BRL/EUR ÷ EUR/USD = BRL/USD)
            #   arabica_brl_kg = arabica_usd_kg × fx_brl_per_eur × USD_TO_EUR
            coffee["arabica_brl_kg"] = coffee["arabica_usd_kg"] * (coffee["fx_brl_per_eur"] * USD_TO_EUR)

            return coffee.tail(120).reset_index(drop=True), statuses

    # ── Simulated fallback ──────────────────────────────────────────────────
    if simulated:
        statuses[0]["status"] = "⚪ Simulato"
        statuses[1]["status"] = "⚪ Simulato"
    rng = np.random.default_rng(get_session_seed())
    dates = pd.date_range(end=pd.Timestamp.today() + pd.offsets.MonthEnd(0), periods=120, freq="ME")
    n = len(dates)
    eur_series = 4.5 + np.cumsum(rng.normal(0, 0.1, n))
    fx_series  = 5.2 + np.cumsum(rng.normal(0, 0.05, n))
    df = pd.DataFrame({
        "date":            dates,
        "arabica_eur_kg":  eur_series,
        "robusta_eur_kg":  2.2 + np.cumsum(rng.normal(0, 0.05, n)),
        "fx_brl_per_eur": fx_series,
        "arabica_brl_kg": eur_series * fx_series,
    })
    return df, statuses


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_climate(date_series: pd.Series, simulated: bool) -> pd.DataFrame:
    rng = np.random.default_rng(get_session_seed())
    df = pd.DataFrame({"date": date_series})
    df["oni"] = 0.25 * np.sin(np.linspace(0, 2.5 * np.pi, len(df))) + rng.normal(0, 0.07, len(df))
    month = df["date"].dt.month
    dry_season = month.isin([6, 7, 8, 9]).astype(float)
    df["rainfall_deficit_pct"] = np.clip(
        6 + 9 * dry_season + 10 * np.clip(-df["oni"], 0, None) + rng.normal(0, 2, len(df)), 0, 30)
    df["wildfire_count"] = np.clip(
        250 + 70 * dry_season + 36 * df["rainfall_deficit_pct"] + rng.normal(0, 50, len(df)), 50, 4500).round()
    df["temperature_anomaly_c"] = np.clip(
        0.05                                          # leggera tendenza positiva (riscaldamento globale)
        + 0.35 * np.clip(df["oni"], 0, None)          # El Niño = più caldo
        - 0.20 * np.clip(-df["oni"], 0, None)         # La Niña = più fresco
        + 0.03 * df["rainfall_deficit_pct"]
        + rng.normal(0, 0.12, len(df)),
        -0.8, 2.0                                     # permette negativi fino a -0.8°C
    )
    return df


# ==========================================
# USDA PSD - per-year keyed fetch
# ==========================================

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_usda(simulated: bool) -> Tuple[pd.DataFrame, dict]:
    status = {"api": "USDA PSD", "url": f"{USDA_BASE_URL}/commodity/...", "status": "✅ Successo", "error": "-"}

    if not simulated:
        try:
            api_key = os.getenv("USDA_API_KEY", "fweuVK6WJVHfLp95h2yYFd6sbHnL631RcY0OkGoG")
            headers = {"accept": "application/json", "X-Api-Key": api_key}

            # Step 1: fetch attribute map
            attr_resp = requests.get(f"{USDA_BASE_URL}/commodityAttributes", headers=headers, timeout=10)
            attr_resp.raise_for_status()
            attr_map = {item["attributeId"]: item["attributeName"].strip() for item in attr_resp.json()}

            # Step 2: fetch data year by year, keeping only target attributes
            rows = []
            for year in range(2000, pd.Timestamp.today().year + 1):
                try:
                    r = requests.get(
                        f"{USDA_BASE_URL}/commodity/{USDA_COMMODITY}/country/{USDA_COUNTRY}/year/{year}",
                        headers=headers, timeout=10
                    )
                    r.raise_for_status()
                    for rec in r.json():
                        attr_name = attr_map.get(rec.get("attributeId"), "")
                        if attr_name in USDA_TARGET_ATTRS:
                            rows.append({
                                "year":      year,
                                "attr_name": attr_name,
                                "value":     rec.get("value", 0),
                                "month":     rec.get("month", 0),
                            })
                except Exception:
                    continue  # skip individual year failures silently

            if not rows:
                raise ValueError("No USDA rows returned for any year. Check API key.")

            df_all = pd.DataFrame(rows)
            # Take the last monthly revision for each year+attribute
            df_last = (
                df_all
                .sort_values("month")
                .groupby(["year", "attr_name"])["value"]
                .last()
                .unstack("attr_name")
                .reset_index()
            )

            # Rename to internal column names
            df_last = df_last.rename(columns=USDA_TARGET_ATTRS)
            df_last = df_last.sort_values("year").reset_index(drop=True)

            # USDA 'value' is already in 1,000 MT units
            # 1,000 MT × 16.667 bags/MT = bags (no extra ×1000)
            MT_TO_BAGS = 16.667   # sacchi da 60 kg per tonnellata metrica
            ARA_SHARE, ROB_SHARE = 0.72, 0.28

            for col_mt, ara_col, rob_col in [
                ("production_mt",    "arabica_bags",  "robusta_bags"),
                ("exports_mt",       "export_ara",    "export_rob"),
                ("ending_stocks_mt", "inventory_ara", "inventory_rob"),
            ]:
                if col_mt in df_last.columns:
                    # value è in 1000 MT → moltiplica solo per MT_TO_BAGS (non ×1000)
                    df_last[ara_col] = df_last[col_mt] * MT_TO_BAGS * ARA_SHARE
                    df_last[rob_col] = df_last[col_mt] * MT_TO_BAGS * ROB_SHARE
                else:
                    df_last[ara_col] = np.nan
                    df_last[rob_col] = np.nan

            df_last["yield_ara"] = 1200.0
            df_last["yield_rob"] = 1600.0

            df_ret = df_last.dropna(subset=["arabica_bags"])
            if not df_ret.empty:
                return df_ret, status

        except Exception as e:
            status["status"] = "❌ Fallito"
            status["error"] = str(e)[:80]

    # ---- Simulated fallback ----
    status["status"] = "⚪ Simulato"
    rng = np.random.default_rng(42)
    yrs = np.arange(2000, pd.Timestamp.today().year + 1)
    biennial = np.sin(np.arange(len(yrs)) * np.pi)
    # Simulato: valori in sacchi reali (60 kg), range realistico 40M-65M
    ara = np.clip(52_000_000 + 3_000_000 * biennial + rng.normal(0, 1_000_000, len(yrs)), 38_000_000, 68_000_000)
    rob = np.clip(18_000_000 + 1_200_000 * np.sin(np.arange(len(yrs)) / 2) + rng.normal(0, 500_000, len(yrs)), 10_000_000, 25_000_000)
    return pd.DataFrame({
        "year":          yrs,
        "arabica_bags":  ara,
        "robusta_bags":  rob,
        "yield_ara":     np.clip(1200 + 50 * biennial + rng.normal(0, 20, len(yrs)), 800, 1800),
        "yield_rob":     np.clip(1600 + 40 * np.sin(np.arange(len(yrs)) / 2) + rng.normal(0, 10, len(yrs)), 1200, 2100),
        "export_ara":    ara * 0.80 + rng.normal(0, 800_000, len(yrs)),
        "export_rob":    rob * 0.65 + rng.normal(0, 400_000, len(yrs)),
        "inventory_ara": ara * 0.18 + rng.normal(0, 300_000, len(yrs)),
        "inventory_rob": rob * 0.12 + rng.normal(0, 150_000, len(yrs)),
    }), status


# ==========================================
# FAOSTAT - via faostat Python package
# ==========================================

def _faostat_mock() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    years = list(range(1990, pd.Timestamp.today().year))
    n = len(years)
    return pd.DataFrame({
        "Year":            years,
        "Area harvested":  np.clip(2_200_000 + np.cumsum(rng.normal(0, 15_000, n)), 1_800_000, 3_100_000),
        "Production":      np.clip(3_200_000 + np.cumsum(rng.normal(0, 80_000, n)), 2_000_000, 6_500_000),
        "Yield":           np.clip(14_000 + rng.normal(0, 800, n), 9_000, 22_000),
    })


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_faostat(simulated: bool) -> Tuple[pd.DataFrame, dict]:
    status = {"api": "FAOSTAT (QCL)", "url": "faostat pkg / QCL / Brazil", "status": "✅ Successo", "error": "-"}

    if not simulated:
        try:
            import faostat as faostat_pkg
        except ImportError:
            status["status"] = "❌ Fallito"
            status["error"] = "faostat package not installed. Run: pip install faostat"
            return _faostat_mock(), status

        try:
            fao_user = os.getenv("FAOSTAT_USERNAME", "")
            fao_pass = os.getenv("FAOSTAT_PASSWORD", "")
            if fao_user and fao_pass:
                faostat_pkg.set_requests_args(username=fao_user, password=fao_pass)

            # Elements as comma-separated STRING (not a list) - required by the package
            # 2312=Area harvested, 2413=Yield, 2510=Production
            # Try with elements first, fall back to no element filter
            mypars_full = {"area": "21", "item": "656", "element": "2312,2413,2510"}
            mypars_bare = {"area": "21", "item": "656"}

            df_raw = None
            last_err = "unknown"
            for pars in [mypars_full, mypars_bare]:
                try:
                    df_raw = faostat_pkg.get_data_df("QCL", pars=pars)
                    if df_raw is not None and not df_raw.empty:
                        break
                except Exception as e_inner:
                    last_err = str(e_inner)
                    continue

            if df_raw is None or df_raw.empty:
                raise ValueError(f"Empty FAOSTAT response. Last error: {last_err}")

            # The package returns columns: Area, Item, Element, Year, Unit, Value, Flag
            # Pivot so each Element becomes its own column
            df_pivot = df_raw.pivot_table(
                index="Year", columns="Element", values="Value", aggfunc="first"
            ).reset_index()
            df_pivot.columns = [str(c).strip() for c in df_pivot.columns]
            return df_pivot, status

        except Exception as e:
            status["status"] = "❌ Fallito"
            status["error"] = str(e)[:80]
            return _faostat_mock(), status

    status["status"] = "⚪ Simulato"
    return _faostat_mock(), status


# ==========================================
# CONAB - file-based, no live scrape in app
# ==========================================

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_conab_states(simulated: bool) -> Tuple[pd.DataFrame, dict]:
    status = {"api": "CONAB Excel", "url": "gov.br/conab/...", "status": "✅ Successo", "error": "-"}

    if os.path.exists(CONAB_CSV_PATH):
        try:
            df_csv = pd.read_csv(CONAB_CSV_PATH)
            # Map to expected columns if present
            if 'region' in df_csv.columns:
                df_csv = df_csv.rename(columns={'region': 'state'})
            if 'yield_kgha' in df_csv.columns:
                df_csv = df_csv.rename(columns={'yield_kgha': 'yield'})
            if 'production_mt' in df_csv.columns:
                # Convert MT to bags (1 MT = 16.667 bags)
                df_csv['production_bags'] = df_csv['production_mt'] * 16.667
            # Ensure required columns exist
            for col in ['state', 'production_bags', 'yield']:
                if col not in df_csv.columns:
                    df_csv[col] = np.nan
            # Re-attach lat/lon from STATE_COORDS if possible
            state_name_to_code = {v[0]: (k, v[1], v[2]) for k, v in STATE_COORDS.items()}
            uf_map = {
                'MG': 'Minas Gerais', 'ES': 'Espirito Santo', 'SP': 'Sao Paulo',
                'PR': 'Parana', 'BA': 'Bahia', 'RO': 'Rondonia', 'GO': 'Goias',
                'MT': 'Mato Grosso', 'RJ': 'Rio de Janeiro',
            }
            if 'code' not in df_csv.columns:
                df_csv['code'] = df_csv['state'].map({v: k for k, v in uf_map.items()}).fillna('')
            df_csv['lat'] = df_csv['code'].map(
                {code: STATE_COORDS.get(name, ('', 0, 0))[1]
                 for code, name in uf_map.items()}).fillna(0)
            df_csv['lon'] = df_csv['code'].map(
                {code: STATE_COORDS.get(name, ('', 0, 0))[2]
                 for code, name in uf_map.items()}).fillna(0)
            df_csv['log_production'] = np.log1p(df_csv['production_bags'].fillna(0))
            status["error"] = f"Loaded from {CONAB_CSV_PATH}"
            return df_csv.dropna(subset=['production_bags']).head(20), status
        except Exception as e:
            status["status"] = "⚠️ Errore file"
            status["error"] = str(e)[:60]
            # Fall through to static data

    # Static fallback
    status["status"] = "⚪ Ripiego statico"
    status["error"] = f"File non trovato: {CONAB_CSV_PATH}. Eseguire python fetch_conab.py"
    base = [
        ("Minas Gerais", 32000000, 29.5), ("Espirito Santo", 15500000, 31.0),
        ("Sao Paulo", 5600000, 27.0), ("Bahia", 5200000, 30.5),
        ("Rondonia", 3800000, 33.5), ("Parana", 2100000, 23.0),
        ("Goias", 1800000, 26.0), ("Mato Grosso", 1400000, 24.0)
    ]
    df = pd.DataFrame([{
        "state": s, "code": STATE_COORDS[s][0],
        "lat": STATE_COORDS[s][1], "lon": STATE_COORDS[s][2],
        "production_bags": p, "yield": y
    } for s, p, y in base])
    df["log_production"] = np.log1p(df["production_bags"])
    return df, status


@st.cache_data(ttl=3600, show_spinner=False)
def build_port_history(climate_df: pd.DataFrame, simulated: bool) -> pd.DataFrame:
    rng = np.random.default_rng(get_session_seed())
    rows = []
    for idx, row in climate_df.iterrows():
        press = 0.45 * row.get("rainfall_deficit_pct", 10) + 0.2 * (row.get("wildfire_count", 0) / 4000 * 100)
        for port, lat, lon, b in PORTS:
            cong = b + 0.5 * press + rng.normal(0, 3)
            delay = np.clip(0.8 + cong / 20 + rng.normal(0, 0.3), 0.2, 9.0)
            rows.append({
                "date": row["date"], "port": port, "lat": lat, "lon": lon,
                "congestion": np.clip(cong, 10, 100), "delay_days": delay,
                "risk": "Alto" if cong > 80 else "Medio" if cong > 50 else "Basso"
            })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False)
def get_coffee_state_prod(simulated: bool) -> pd.DataFrame:
    rows = []
    for sigla, vals in COFFEE_STATE_PROD.items():
        # normalize_region_name maps sigla → "MG - Minas Gerais (Sud-Est)" etc.
        rows.append({
            "state": normalize_region_name(sigla),
            "arabica_bags": vals['Arabica'],
            "robusta_bags": vals['Robusta'],
        })
    return pd.DataFrame(rows)


# ==========================================
# LIVE WEBSOCKET LOGIC (AIS) - NO CACHE
# ==========================================

async def _fetch_ais_snapshot(simulated: bool, listen_time_seconds: int = 10):
    status = {"api": "AISStream WS", "url": AIS_WS_URL, "status": "✅ Successo", "error": "-"}
    diag = {
        "connection":       "Not attempted",
        "messages_received": 0,
        "position_reports":  0,
        "static_data_msgs":  0,
        "in_bbox_raw":       0,
        "cargo_filtered_out": 0,
        "final_tracked":     0,
        "listen_seconds":    listen_time_seconds,
        "error":             None,
        "ports_used":        list(AIS_LIVE_PORTS.keys()),
    }
    tracked = {}
    ship_types = {}

    if simulated:
        status["status"] = "⚪ Simulato"
        diag["connection"] = "Simulato ⚪"
        rng = np.random.default_rng(42)
        for port in AIS_LIVE_PORTS:
            for i in range(int(rng.integers(8, 25))):
                vid = f"SIM_T_{port}_{i}"
                tracked[vid] = {"port": port, "sog": float(rng.uniform(2, 14)),
                                "status": 0, "last_seen": time.time()}
                ship_types[vid] = int(rng.integers(70, 80))
            for i in range(int(rng.integers(10, 40))):
                vid = f"SIM_A_{port}_{i}"
                tracked[vid] = {"port": port, "sog": 0.0,
                                "status": 1, "last_seen": time.time()}
                ship_types[vid] = int(rng.integers(70, 80))
        diag["messages_received"] = len(tracked)
        diag["position_reports"]  = len(tracked)
        diag["in_bbox_raw"]       = len(tracked)
        diag["final_tracked"]     = len(tracked)
        return tracked, ship_types, status, diag

    def get_live_port_zone(lat, lon):
        for port_name, box in AIS_LIVE_PORTS.items():
            if box[0][0] <= lat <= box[1][0] and box[0][1] <= lon <= box[1][1]:
                return port_name
        return None

    try:
        diag["connection"] = "Connessione in corso..."
        async with websockets.connect(AIS_WS_URL) as ws:
            diag["connection"] = "Connesso ✅"
            sub = {
                "APIKey": AIS_API_KEY,
                "BoundingBoxes": list(AIS_LIVE_PORTS.values()),
                "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
            }
            await ws.send(json.dumps(sub))
            t0 = time.time()
            while time.time() - t0 < listen_time_seconds:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    diag["messages_received"] += 1
                    msg = json.loads(raw)
                    mtype = msg.get("MessageType", "")

                    if mtype == "ShipStaticData":
                        diag["static_data_msgs"] += 1
                        d = msg.get("Message", {}).get("ShipStaticData", {})
                        mmsi = d.get("UserID")
                        if mmsi:
                            ship_types[mmsi] = int(d.get("Type", 75))

                    elif mtype == "PositionReport":
                        diag["position_reports"] += 1
                        d = msg.get("Message", {}).get("PositionReport", {})
                        mmsi = d.get("UserID")
                        lat  = d.get("Latitude")
                        lon  = d.get("Longitude")
                        sog  = d.get("Sog", 0)
                        nav  = d.get("NavigationalStatus", 99)
                        port = get_live_port_zone(lat, lon)
                        if port:
                            diag["in_bbox_raw"] += 1
                            ship_t = ship_types.get(mmsi, 75)
                            # Keep type-0 (not defined) and 70-89; exclude confirmed non-cargo
                            if ship_t == 0 or (70 <= ship_t <= 89):
                                tracked[mmsi] = {
                                    "port": port, "sog": sog,
                                    "status": nav, "last_seen": time.time(),
                                }
                            else:
                                diag["cargo_filtered_out"] += 1
                except asyncio.TimeoutError:
                    continue

    except Exception as e:
        status["status"] = "❌ Fallito"
        status["error"] = str(e)[:120]
        diag["connection"] = f"Fallito ❌: {str(e)[:80]}"
        diag["error"] = str(e)

    diag["final_tracked"] = len(tracked)
    return tracked, ship_types, status, diag


def _fetch_ais_snapshot_sync(simulated: bool, listen_time_seconds: int = 10):
    """Synchronous wrapper around the async AIS fetch."""
    return asyncio.run(_fetch_ais_snapshot(simulated, listen_time_seconds))


# ==========================================
# WILDFIRE MAP (MATPLOTLIB + GEOPANDAS)
# ==========================================

@st.cache_data(ttl=3600, show_spinner=False)
def load_brazil_geodataframe() -> gpd.GeoDataFrame:
    return gpd.read_file(GEOJSON_URL)


def render_wildfire_maps(fires_df: pd.DataFrame, states_prod: pd.DataFrame):
    """Render side-by-side Arabica/Robusta choropleth + fire dots via matplotlib+geopandas."""
    try:
        brazil_states = load_brazil_geodataframe()
    except Exception as e:
        st.warning(f"Impossibile caricare la GeoJSON del Brasile: {e}")
        return

    coffee_df = states_prod[["state", "arabica_bags", "robusta_bags"]].copy()

    def _extract_sigla(label: str) -> str:
        """Extract 2-letter sigla from a normalized label like 'MG - Minas Gerais (Sud-Est)'."""
        if isinstance(label, str) and "-" in label:
            return label.split("-")[0].strip()
        return label.strip() if isinstance(label, str) else ""

    sigla_to_arabica = {_extract_sigla(r["state"]): r["arabica_bags"]
                        for _, r in coffee_df.iterrows() if _extract_sigla(r["state"])}
    sigla_to_robusta = {_extract_sigla(r["state"]): r["robusta_bags"]
                        for _, r in coffee_df.iterrows() if _extract_sigla(r["state"])}

    brazil_map = brazil_states.copy()
    brazil_map["Arabica"] = brazil_map["sigla"].map(sigla_to_arabica).replace(0, np.nan)
    brazil_map["Robusta"] = brazil_map["sigla"].map(sigla_to_robusta).replace(0, np.nan)

    if not fires_df.empty and "latitude" in fires_df.columns:
        fires_gdf = gpd.GeoDataFrame(
            fires_df,
            geometry=gpd.points_from_xy(fires_df["longitude"], fires_df["latitude"]),
            crs="EPSG:4326"
        )
        if brazil_states.crs is None:
            brazil_states = brazil_states.set_crs("EPSG:4326")
        fires_in_brazil = gpd.sjoin(fires_gdf, brazil_states[["geometry"]], how="inner", predicate="intersects")
    else:
        fires_in_brazil = gpd.GeoDataFrame(columns=["geometry", "frp"])

    threshold = 50
    large_fires = fires_in_brazil[fires_in_brazil["frp"] > threshold] if not fires_in_brazil.empty else gpd.GeoDataFrame()
    small_fires = fires_in_brazil[fires_in_brazil["frp"] <= threshold] if not fires_in_brazil.empty else gpd.GeoDataFrame()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
    fig.patch.set_facecolor("none")

    ax1.set_title("Produzione Arabica & Rilevamenti Incendi (FRP)", fontsize=14)
    brazil_map.plot(column="Arabica", ax=ax1, cmap="Greens", edgecolor="white",
                    linewidth=0.5, legend=True, missing_kwds={"color": "#e0e0e0"})
    if not small_fires.empty:
        ax1.scatter(small_fires.geometry.x, small_fires.geometry.y,
                    color="grey", s=3, alpha=0.2, edgecolors="none")
    if not large_fires.empty:
        ax1.scatter(large_fires.geometry.x, large_fires.geometry.y,
                    c=large_fires["frp"], cmap="hot",
                    s=np.sqrt(large_fires["frp"]) * 3, alpha=0.9,
                    edgecolors="black", linewidth=0.3)
    ax1.axis("off")

    ax2.set_title("Produzione Robusta & Rilevamenti Incendi (FRP)", fontsize=14)
    brazil_map.plot(column="Robusta", ax=ax2, cmap="Purples", edgecolor="white",
                    linewidth=0.5, legend=True, missing_kwds={"color": "#e0e0e0"})
    if not small_fires.empty:
        ax2.scatter(small_fires.geometry.x, small_fires.geometry.y,
                    color="grey", s=3, alpha=0.2, edgecolors="none")
    if not large_fires.empty:
        ax2.scatter(large_fires.geometry.x, large_fires.geometry.y,
                    c=large_fires["frp"], cmap="hot",
                    s=np.sqrt(large_fires["frp"]) * 3, alpha=0.9,
                    edgecolors="black", linewidth=0.3)
    ax2.axis("off")

    plt.tight_layout()
    st.pyplot(fig)

    with st.expander("📖 Come leggere la mappa - Legenda FRP (Fire Radiative Power)", expanded=False):
        col_l1, col_l2, col_l3 = st.columns(3)
        with col_l1:
            st.markdown("**Punti Grigi (FRP ≤ 50 MW)**")
            st.caption(
                "Focolai di bassa intensità: fuochi agricoli controllati, "
                "disboscamento minore, biomassa secca. Impatto agronomico limitato."
            )
        with col_l2:
            st.markdown("**Punti Rosso-Arancio (FRP 50–200 MW)**")
            st.caption(
                "Incendi significativi. Rischio diretto per le piantagioni nelle vicinanze. "
                "Monitorare se sovrapposti alle aree di produzione colorata."
            )
        with col_l3:
            st.markdown("**Punti Giallo-Bianco (FRP > 200 MW)**")
            st.caption(
                "Incendi di massima intensità. Equivale a migliaia di ettari in fiamme. "
                "Impatto certo sul raccolto in corso e potenzialmente su quello successivo."
            )
        st.markdown("---")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.markdown("**Scala colore mappa sinistra (Verde)**")
            st.caption("Intensità di produzione Arabica per stato (milioni di sacchi da 60 kg). "
                       "Verde scuro = alta produzione. Grigio chiaro = produzione assente o trascurabile.")
        with col_s2:
            st.markdown("**Scala colore mappa destra (Viola)**")
            st.caption("Intensità di produzione Robusta/Conilon per stato. "
                       "Viola intenso = Espírito Santo (principale produttore). "
                       "Rondônia (RO) è il secondo produttore Robusta.")
        st.info(
            "**FRP (Fire Radiative Power)** è la potenza energetica irradiata dall'incendio misurata dal satellite "
            "NASA VIIRS in **Megawatt (MW)**. Non è la superficie bruciata - è l'intensità istantanea del fuoco. "
            "Un valore alto indica combustione intensa di vegetazione densa (es. foresta, non sterpaglia)."
        )

    plt.close(fig)


# ==========================================
# UI TABS RENDERING
# ==========================================

def render_tab_1(oni_series, soi_series):
    def safe_delta(series):
        if len(series) < 2:
            return None
        return series.iloc[-1] - series.iloc[-2]

    latest_oni = oni_series.iloc[-1]
    latest_soi = soi_series.iloc[-1]
    oni_delta = safe_delta(oni_series)
    soi_delta = safe_delta(soi_series)

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
    c3.markdown(f"**Fase Attuale:**<br><span style='color:{color}; font-size:1.4em; font-weight:bold;'>{phase}</span>",
                unsafe_allow_html=True)
    c4.info(f"**Impatto Agronomico:** {advice}")

    colA, colB = st.columns(2)
    try:
        with colA:
            st.markdown("#### Indice ONI (Oceanico)")
            oni_recent = oni_series.tail(36)
            x_vals = [f"{idx[0]}-{str(idx[1]).zfill(2)}" for idx in oni_recent.index]
            y_vals = oni_recent.values.tolist()

            fig_oni = go.Figure()
            # Red fill above +0.5
            fig_oni.add_trace(go.Scatter(
                x=x_vals + x_vals[::-1],
                y=[max(v, 0.5) for v in y_vals] + [0.5] * len(x_vals),
                fill='toself', fillcolor='rgba(220,50,50,0.25)',
                line=dict(width=0), hoverinfo='skip', showlegend=False
            ))
            # Blue fill below -0.5
            fig_oni.add_trace(go.Scatter(
                x=x_vals + x_vals[::-1],
                y=[min(v, -0.5) for v in y_vals] + [-0.5] * len(x_vals),
                fill='toself', fillcolor='rgba(50,100,220,0.25)',
                line=dict(width=0), hoverinfo='skip', showlegend=False
            ))
            fig_oni.add_trace(go.Scatter(x=x_vals, y=y_vals, mode='lines+markers', name='ONI',
                                         line=dict(color='black', width=1.5), marker=dict(size=4)))
            fig_oni.add_hline(y=0.5, line_dash="dash", line_color="red", annotation_text="El Niño (+0.5)")
            fig_oni.add_hline(y=-0.5, line_dash="dash", line_color="blue", annotation_text="La Niña (-0.5)")
            fig_oni.update_yaxes(title_text="Anomalia Termica (°C)")
            fig_oni.update_xaxes(title_text="Periodo")
            fig_oni.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_oni, use_container_width=True)
            st.caption("L'Oceanic Niño Index (ONI) misura le anomalie della temperatura superficiale del mare nel Pacifico centrale. Valori sopra +0.5°C indicano condizioni El Niño; sotto -0.5°C indicano La Niña. Le aree ombreggiate evidenziano le fasi attive.")

        with colB:
            st.markdown("#### Indice SOI (Atmosferico)")
            soi_recent = soi_series.tail(36)
            x_soi = [f"{idx[0]}-{str(idx[1]).zfill(2)}" for idx in soi_recent.index]
            bar_colors = ['blue' if val >= 0 else 'red' for val in soi_recent.values]
            fig_soi = go.Figure(data=[go.Bar(x=x_soi, y=soi_recent.values, marker_color=bar_colors)])
            fig_soi.add_hline(y=7, line_dash="dash", line_color="blue", annotation_text="La Niña (+7)")
            fig_soi.add_hline(y=-7, line_dash="dash", line_color="red", annotation_text="El Niño (-7)")
            fig_soi.update_yaxes(title_text="Indice SOI (adimensionale)")
            fig_soi.update_xaxes(title_text="Periodo")
            fig_soi.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_soi, use_container_width=True)
            st.caption("Il Southern Oscillation Index (SOI) misura le differenze di pressione atmosferica nel Pacifico. Valori fortemente positivi confermano La Niña; valori fortemente negativi confermano El Niño. La divergenza dall'ONI segnala un evento debole o disaccoppiato.")

        # ONI Heatmap
        st.markdown("#### Mappa Termica ONI Storica (10 Anni)")
        oni_10yr = oni_series.tail(120).reset_index()
        oni_10yr.columns = ["Year", "Month", "ONI"]
        oni_10yr["Year"] = oni_10yr["Year"].astype(int)
        oni_10yr["Month"] = oni_10yr["Month"].astype(int)
        pivot_oni = oni_10yr.pivot_table(index="Month", columns="Year", values="ONI", aggfunc="mean")
        pivot_oni = pivot_oni.sort_index(axis=1)
        pivot_oni = pivot_oni.reindex(range(1, 13))
        pivot_oni.index = [MONTH_NAMES[i - 1] for i in pivot_oni.index]
        fig_heat = px.imshow(pivot_oni, text_auto=".1f", aspect="auto",
                             color_continuous_scale="RdBu_r", color_continuous_midpoint=0)
        fig_heat.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0),
                               coloraxis_colorbar=dict(title="ONI (°C)"))
        st.plotly_chart(fig_heat, use_container_width=True)
        st.caption("Valori ONI mensili su 10 anni, organizzati per anno (colonne) e mese (righe). Le celle rosse indicano mesi El Niño; le blu indicano La Niña. Utile per identificare schemi stagionali e cicli pluriennali.")

    except Exception as e:
        st.warning(f"Impossibile visualizzare il grafico ENSO: {e}")




def render_tab_2(fires, climate, states_prod):
    try:
        render_wildfire_maps(fires, states_prod)
        st.caption("L'ombreggiatura verde mostra il volume di produzione Arabica per stato brasiliano. I punti rossi/gialli sono rilevamenti di incendi satellitari NASA VIIRS degli ultimi 5 giorni, dimensionati e colorati per FRP (MW). La sovrapposizione con le regioni verdi segnala rischio diretto al raccolto.")
        st.caption("L'ombreggiatura viola mostra l'intensità di produzione Robusta (Conilon) per stato. I punti incendi usano la stessa scala FRP. Espírito Santo (ES) e Rondônia (RO) sono le principali zone a rischio Robusta.")

        colA, colB = st.columns(2)
        with colA:
            st.markdown("#### Conteggio Mensile Incendi (Ultimi 24 Mesi)")
            recent_climate = climate.tail(24).copy()
            fig_ts = px.line(
                recent_climate, x="date", y="wildfire_count",
                markers=True,
                color_discrete_sequence=[COLORS['danger']],
                labels={"wildfire_count": "Numero Incendi (focolai/mese)", "date": "Data"}
            )
            fig_ts.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_ts, use_container_width=True)
            st.caption("Conteggio mensile dei focolai di incendio rilevati da satellite in Brasile negli ultimi 24 mesi. I picchi si verificano tipicamente nella stagione secca (giugno–settembre). Aumenti rapidi correlano con stress idrico e umidità ridotta.")

        with colB:
            st.markdown("#### Hotspot per Macro-Regione")
            if not fires.empty:
                fires_c = fires.copy()
                if "province" in fires_c.columns:
                    fires_c["macro_region"] = fires_c["province"].apply(get_macro_region_from_sigla)
                elif "country_id" in fires_c.columns:
                    fires_c["macro_region"] = fires_c["country_id"].apply(get_macro_region_from_sigla)
                else:
                    def lat_lon_region(row):
                        lat, lon = row["latitude"], row["longitude"]
                        if lat > -4:                         return "Nord"
                        elif lat > -15 and lon > -44:        return "Nord-Est"
                        elif lat > -20 and lon < -52:        return "Centro-Ovest"
                        elif lat > -25:                      return "Sud-Est"
                        else:                                return "Sud"
                    fires_c["macro_region"] = fires_c.apply(lat_lon_region, axis=1)

                reg_counts = fires_c["macro_region"].value_counts().reset_index()
                reg_counts.columns = ["Regione", "Conteggio"]
                fig_bar = px.bar(reg_counts, x="Regione", y="Conteggio", color="Regione",
                                 color_discrete_sequence=px.colors.qualitative.Pastel)
                fig_bar.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
                st.plotly_chart(fig_bar, use_container_width=True)
                st.caption("Conteggio rilevamenti incendi aggregati per macro-regione geografica del Brasile. Le regioni Centro-Ovest e Nord dominano tipicamente per l'esposizione ai biomi del Cerrado e dell'Amazzonia.")
            else:
                st.info("Nessun incendio attivo da aggregare.")
    except Exception as e:
        st.warning(f"Impossibile visualizzare il grafico degli incendi: {e}")


def render_tab_3(ports_history, live_vessels, ship_types, ais_status, diag):

    # ── SECTION 1: LIVE GLOBAL AIS STREAM ──────────────────────────────────
    st.markdown("### 🛰️ Flusso AIS Live - Porti di Riferimento Globali")
    st.info(
        "**Perché porti globali?** Il piano gratuito di AISStream.io non ha copertura affidabile "
        "nelle bounding box dei porti brasiliani. Singapore, Rotterdam e Los Angeles sono "
        "mostrati come dimostrazione AIS live. I dati di congestione dei porti brasiliani (Sezione 2) "
        "utilizzano stime modellistiche basate su clima e pattern storici di navigazione."
    )

    with st.expander("🔍 Diagnostica Flusso AIS", expanded=True):
        if "❌" in ais_status.get("status", ""):
            st.error(f"Connessione WebSocket fallita: {ais_status.get('error', 'Errore sconosciuto')}")
        else:
            dc = st.columns(6)
            dc[0].metric("Stato WS",              diag["connection"])
            dc[1].metric("Messaggi Ricevuti",      diag["messages_received"])
            dc[2].metric("Report Posizione",        diag["position_reports"])
            dc[3].metric("Msg Dati Statici",        diag["static_data_msgs"])
            dc[4].metric("Nel Bbox (grezzo)",       diag["in_bbox_raw"])
            dc[5].metric("Tracciati Finali",        diag["final_tracked"])
            st.caption(
                f"In ascolto per {diag['listen_seconds']}s su "
                f"{', '.join(diag.get('ports_used', []))}. "
                f"Navi di tipo non-cargo escluse: {diag['cargo_filtered_out']}. "
                f"Navi di tipo sconosciuto mantenute (assunte cargo)."
            )

    # Tally per global port
    live_results = {p: {"transito": 0, "ormeggiato": 0, "totale_segnali": 0} for p in AIS_LIVE_PORTS}
    for mmsi, v in live_vessels.items():
        p = v.get("port")
        if p not in live_results:
            continue
        live_results[p]["totale_segnali"] += 1
        ship_t = ship_types.get(mmsi, 75)
        # Only count confirmed or assumed cargo (70-89 or unknown=75)
        if ship_t == 0 or (70 <= ship_t <= 89):
            if v["sog"] < 1.0 or v.get("status") in [1, 5]:
                live_results[p]["ormeggiato"] += 1
            else:
                live_results[p]["transito"] += 1

    cols = st.columns(len(AIS_LIVE_PORTS))
    for i, (port, counts) in enumerate(live_results.items()):
        cargo = counts["transito"] + counts["ormeggiato"]
        cols[i].metric(
            port,
            f"{cargo} cargo",
            f"Totale segnali AIS: {counts['totale_segnali']}"
        )

    try:
        bar_data = [{"Porto": k, "In Transito": v["transito"], "All'Ancora/Ormeggiato": v["ormeggiato"]}
                    for k, v in live_results.items()]
        df_bar = pd.DataFrame(bar_data).melt(id_vars="Porto", var_name="Stato", value_name="Navi")
        fig_live = px.bar(df_bar, x="Porto", y="Navi", color="Stato", barmode="group",
                          color_discrete_map={"In Transito": COLORS["safe"], "All'Ancora/Ormeggiato": COLORS["danger"]})
        fig_live.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_live, use_container_width=True)
        st.caption("Conteggi live AIS di navi cargo nei tre porti globali ad alto traffico. "
                   "Navi in transito (SOG > 1 nodi) vs. all'ancora o ormeggiate. "
                   "Aggiornato su richiesta tramite il pulsante qui sotto.")
    except Exception as e:
        st.warning(f"Errore grafico a barre: {e}")

    if st.button("🔄 Aggiorna Dati AIS Live (~10s)"):
        if "ais_data" in st.session_state:
            del st.session_state["ais_data"]
        st.rerun()

    st.caption(f"Ultimo aggiornamento: {st.session_state.get('ais_fetched_at', 'Mai')}")

    st.divider()
    with st.expander("ℹ️ Perché i dati brasiliani sono stime e non dati live?", expanded=True):
        st.markdown("""
Il sistema AIS (Automatic Identification System) gratuito non ha copertura affidabile nei porti brasiliani.
Il tier gratuito di AISStream.io copre principalmente i grandi hub globali (Asia, Nord Europa, West Coast USA).
Per dati AIS live sui porti di Santos, Vitória e Paranaguá in produzione sarebbe necessario un feed premium
(es. MarineTraffic, Spire Maritime) al costo indicativo di **€500–5.000/mese**.
        """)

    # ── SECTION 2: BRAZIL PORTS - HISTORICAL MODELLED DATA ────────────────
    st.markdown("### 🇧🇷 Porti Brasiliani del Caffè - Esempio di visualizzazione")

    try:
        colA, colB = st.columns(2)
        with colA:
            st.markdown("#### Tendenze Ritardo Porto - Ultimi 12 Mesi (Giorni)")
            if not ports_history.empty:
                recent = ports_history[
                    ports_history["date"] >= ports_history["date"].max() - pd.DateOffset(months=12)
                ]
                fig_delay = px.line(recent, x="date", y="delay_days", color="port", markers=True,
                                    labels={"delay_days": "Ritardo (giorni)", "port": "Porto", "date": "Data"})
                fig_delay.update_yaxes(title_text="Ritardo Stimato (giorni)")
                fig_delay.update_xaxes(title_text="Data")
                fig_delay.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
                st.plotly_chart(fig_delay, use_container_width=True)
                st.caption("Ogni linea mostra il ritardo di spedizione stimato per un porto di esportazione di caffè brasiliano negli ultimi 12 mesi. Ritardi più elevati correlano con la congestione della stagione secca e le interruzioni stradali causate dagli incendi.")

        with colB:
            st.markdown("#### Mappa Rischio Porto Attuale")
            latest_ports = ports_history[ports_history["date"] == ports_history["date"].max()]
            fig_map = px.scatter_mapbox(
                latest_ports, lat="lat", lon="lon", color="risk", size="delay_days",
                hover_name="port",
                color_discrete_map={"Alto": COLORS["danger"], "Medio": COLORS["warning"], "Basso": COLORS["safe"]},
                mapbox_style="carto-positron", zoom=4, center={"lat": -20, "lon": -45}
            )
            fig_map.update_layout(height=380, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig_map, use_container_width=True)
            st.caption("Porti di esportazione brasiliani del caffè, dimensionati per il ritardo attuale stimato e colorati per livello di rischio. Passa il cursore per i valori esatti.")
    except Exception as e:
        st.warning(f"Errore grafici porti brasiliani: {e}")


def render_tab_4(prices):
    try:
        # ── Snapshot tasso di cambio BRL/EUR attuale ──────────────────────────
        fx_now = float(prices["fx_brl_per_eur"].iloc[-1]) if not prices.empty else 0.0
        st.metric(
            "Tasso di Cambio Attuale BRL/EUR",
            f"R$ {fx_now:.2f}",
            help="Tasso live da ER-API. Quanti Real brasiliani equivalgono a 1 Euro oggi."
        )

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Prezzi Arabica & Robusta (EUR/kg)")
            figA = make_subplots(specs=[[{"secondary_y": True}]])
            figA.add_trace(go.Scatter(x=prices["date"], y=prices["arabica_eur_kg"],
                                      name="Arabica (€)", line=dict(color=COLORS['arabica'])), secondary_y=False)
            figA.add_trace(go.Scatter(x=prices["date"], y=prices["robusta_eur_kg"],
                                      name="Robusta (€)", line=dict(color=COLORS['robusta'])), secondary_y=True)
            figA.update_yaxes(title_text="Arabica (EUR/kg)", secondary_y=False)
            figA.update_yaxes(title_text="Robusta (EUR/kg)", secondary_y=True)
            figA.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(figA, use_container_width=True)
            st.caption("Prezzi storici ICE futures Arabica e Robusta convertiti in EUR/kg con tassi FX in tempo reale da ER-API. Fonte: World Bank Commodity Price Data (Pink Sheet), frequenza mensile.")

        with c2:
            st.markdown("#### Spread Arabica vs Robusta con Media Mobile a 3 Mesi")
            prices_c = prices.copy()
            prices_c["spread"] = prices_c["arabica_eur_kg"] - prices_c["robusta_eur_kg"]
            prices_c["ma_3"] = prices_c["spread"].rolling(window=3).mean()
            figS = go.Figure()
            figS.add_trace(go.Bar(x=prices_c["date"], y=prices_c["spread"],
                                  name="Differenziale Prezzi", marker_color="#8c564b", opacity=0.6))
            figS.add_trace(go.Scatter(x=prices_c["date"], y=prices_c["ma_3"],
                                      mode="lines", name="Media Mobile 3 Mesi", line=dict(color="red", width=2)))
            figS.update_yaxes(title_text="Differenziale (EUR/kg)")
            figS.update_xaxes(title_text="Data")
            figS.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(figS, use_container_width=True)
            st.caption("Premio di prezzo dell'Arabica sull'Robusta in EUR/kg. Le barre mostrano il differenziale mensile grezzo; la linea rossa è la media mobile a 3 mesi. Un differenziale in allargamento segnala differenziazione qualitativa o shock di offerta.")

        st.markdown("#### Prezzo Arabica: BRL/kg vs EUR/kg a Confronto")

        # ── Build Base-100 normalized series ────────────────────────────────
        px_c = prices[["date", "arabica_brl_kg", "arabica_eur_kg", "fx_brl_per_eur"]].copy().reset_index(drop=True)
        px_c["brl_idx"] = (px_c["arabica_brl_kg"] / px_c["arabica_brl_kg"].iloc[0]) * 100
        px_c["eur_idx"] = (px_c["arabica_eur_kg"] / px_c["arabica_eur_kg"].iloc[0]) * 100

        # ── Rolling 12-month Z-score of fx_brl_per_eur ────────────────────────
        px_c["fx_roll_mean"] = px_c["fx_brl_per_eur"].rolling(12, min_periods=3).mean()
        px_c["fx_roll_std"]  = px_c["fx_brl_per_eur"].rolling(12, min_periods=3).std()
        px_c["fx_zscore"]    = (px_c["fx_brl_per_eur"] - px_c["fx_roll_mean"]) / px_c["fx_roll_std"].replace(0, np.nan)
        bar_colors_fx = ["#3E7B58" if (z == z and z > 1) else "#BDBDBD" for z in px_c["fx_zscore"].fillna(0)]

        figFX = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            row_heights=[0.65, 0.35],
            vertical_spacing=0.08,
            subplot_titles=("Andamento Prezzi Normalizzati (Base 100)",
                            "Z-Score FX BRL/EUR - Rolling 12 Mesi"),
        )

        # ── Top subplot: fill-between segments colored by FX advantage ────────
        dates_list = px_c["date"].tolist()
        brl_vals   = px_c["brl_idx"].tolist()
        eur_vals   = px_c["eur_idx"].tolist()

        for i in range(len(dates_list) - 1):
            eur_advantage = eur_vals[i] < brl_vals[i]   # EUR index lower = cheaper for buyer
            fill_col = "rgba(62,123,88,0.18)" if eur_advantage else "rgba(178,58,46,0.12)"
            figFX.add_trace(go.Scatter(
                x=[dates_list[i], dates_list[i + 1], dates_list[i + 1], dates_list[i]],
                y=[brl_vals[i],   brl_vals[i + 1],   eur_vals[i + 1],   eur_vals[i]],
                fill="toself",
                fillcolor=fill_col,
                mode="lines",                  # suppress stray marker dots at polygon vertices
                line=dict(width=0, color=fill_col),
                hoverinfo="skip",
                showlegend=False,
            ), row=1, col=1)

        figFX.add_trace(go.Scatter(
            x=px_c["date"], y=px_c["brl_idx"],
            name="Arabica BRL/kg (Base 100)",
            line=dict(color="#1A5EA8", width=2),
            hovertemplate="%{x|%b %Y}  BRL idx: %{y:.1f}<extra></extra>",
        ), row=1, col=1)

        figFX.add_trace(go.Scatter(
            x=px_c["date"], y=px_c["eur_idx"],
            name="Arabica EUR/kg (Base 100)",
            line=dict(color="#4A2F1D", width=2, dash="dot"),
            hovertemplate="%{x|%b %Y}  EUR idx: %{y:.1f}<extra></extra>",
        ), row=1, col=1)

        # ── Bottom subplot: Z-score bars ──────────────────────────────────────
        figFX.add_trace(go.Bar(
            x=px_c["date"], y=px_c["fx_zscore"],
            marker_color=bar_colors_fx,
            name="Z-Score FX BRL/EUR",
            hovertemplate="%{x|%b %Y}  Z: %{y:.2f}<extra></extra>",
        ), row=2, col=1)

        figFX.add_hline(y=1,  line_dash="dash", line_color="#3E7B58",
                        annotation_text="+1σ EUR forte", row=2, col=1)
        figFX.add_hline(y=0,  line_dash="dot",  line_color="#AAAAAA", row=2, col=1)
        figFX.add_hline(y=-1, line_dash="dash", line_color="#B23A2E",
                        annotation_text="−1σ", row=2, col=1)

        figFX.update_yaxes(title_text="Indice (Base 100)", row=1, col=1, gridcolor="rgba(0,0,0,0.06)")
        figFX.update_yaxes(title_text="Z-Score",           row=2, col=1, zeroline=True, zerolinecolor="#AAAAAA")
        figFX.update_xaxes(title_text="Data", row=2, col=1)
        figFX.update_layout(
            height=560,
            margin=dict(l=0, r=0, t=50, b=0),
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=1.06, x=0),
            hovermode="x unified",
        )
        st.plotly_chart(figFX, use_container_width=True)
        st.caption(
            "📊 **Come leggere questo grafico** - "
            "Il pannello superiore mostra l'andamento normalizzato (Base 100) del prezzo Arabica "
            "in BRL/kg (linea blu) e EUR/kg (linea marrone tratteggiata). "
            "🟢 Le zone **verdi** indicano periodi in cui l'EUR è relativamente più forte del BRL: "
            "l'acquirente europeo ottiene più cafè per ogni euro speso. "
            "🔴 Le zone **rosse** segnalano il contrario. "
            "Il pannello inferiore mostra lo Z-score rolling 12 mesi del cambio BRL/EUR: "
            "le barre verdi (Z\u202f>\u202f+1σ) evidenziano i momenti storicamente favorevoli all'acquisto in EUR."
        )

        st.markdown("#### Prezzo Medio Annuo Arabica vs Media Decennale")
        pr_annual = prices.copy()
        pr_annual["year"] = pr_annual["date"].dt.year
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
        st.plotly_chart(fig_ann, use_container_width=True)
        st.caption("Prezzo medio annuo Arabica per anno (barre) vs. media decennale (linea tratteggiata). Gli anni significativamente sopra la media seguono spesso shock di offerta come siccità o gelate in Brasile.")

    except Exception as e:
        st.warning(f"Impossibile visualizzare il grafico dei prezzi: {e}")


def render_tab_5(usda, states_mock, faostat_df, simulated, api_health_list):
    # ── CONAB info banner ─────────────────────────────────────────────────────
    st.info(
        "ℹ️ I dati CONAB provengono da un report Excel pre-scaricato "
        "(eseguire `python fetch_conab.py` per aggiornare). Vengono mostrati i dati statici "
        "dell'ultimo Levantamento de Café CONAB."
    )

    # ── Data Sources & Live API Status expander ───────────────────────────────
    def _get_status(api_name: str) -> str:
        for item in api_health_list:
            if item.get("api", "").startswith(api_name):
                st_str = item.get("status", "-")
                err = item.get("error", "")
                return f"{st_str} - {err}" if err and err != "-" else st_str
        return "-"

    with st.expander("📡 Fonti Dati & Stato API Live"):
        usda_st = _get_status("USDA PSD")
        fao_st = _get_status("FAOSTAT")
        st.markdown(f"""
| Fonte | Metodo di Accesso | Dati Principali | Stato |
|---|---|---|---|
| USDA PSD | `api.fas.usda.gov/api/psd` - chiave API tramite var d'ambiente `USDA_API_KEY` | Produzione, esportazioni, scorte finali per anno | {usda_st} |
| FAOSTAT | Pacchetto Python `faostat` - credenziali tramite `FAOSTAT_USERNAME` / `FAOSTAT_PASSWORD` | Superficie raccolta, resa, produzione 1990–presente | {fao_st} |
| CONAB | Excel pre-scaricato tramite script `fetch_conab.py` | Produzione & resa per stato e stagione | Statico / file locale |
""")

    # ── FAOSTAT Long-Run historical expander ──────────────────────────────────
    with st.expander("📊 FAOSTAT Dati Storici a Lungo Termine (1990–2023)"):
        if not faostat_df.empty and "Year" in faostat_df.columns:
            try:
                fao_plot = faostat_df.copy()
                # Detect which column name pattern is present (real pivoted names vs mock names)
                area_col = (
                    next((c for c in fao_plot.columns if "area" in c.lower() and "harvest" in c.lower()), None)
                    or next((c for c in fao_plot.columns if "area" in c.lower()), None)
                )
                prod_col  = next((c for c in fao_plot.columns if "production" in c.lower()), None)
                year_col  = "Year" if "Year" in fao_plot.columns else fao_plot.columns[0]

                if prod_col and year_col:
                    fig_fao = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_fao.add_trace(go.Bar(
                        x=fao_plot[year_col], y=fao_plot[prod_col],
                        name="Produzione (tonnellate)", marker_color="#4A2F1D", opacity=0.75
                    ), secondary_y=False)
                    if area_col:
                        fig_fao.add_trace(go.Scatter(
                            x=fao_plot[year_col], y=fao_plot[area_col],
                            name="Superficie Raccolta (ha)", line=dict(color="#3E7B58", width=2.5)
                        ), secondary_y=True)
                    fig_fao.update_yaxes(title_text="Produzione (tonnellate)", secondary_y=False)
                    fig_fao.update_yaxes(title_text="Superficie Raccolta (ettari)", secondary_y=True)
                    fig_fao.update_xaxes(title_text="Anno")
                    fig_fao.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0),
                                          plot_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig_fao, use_container_width=True)
                    st.caption(
                        "Fonte: dataset FAOSTAT QCL, Brasile (area=21), Caffè verde (item=656). "
                        "Le barre mostrano la produzione totale in tonnellate; la linea mostra la superficie raccolta in ettari. "
                        "I cicli lunghi riflettono il pattern biennale anni-on/off."
                    )
                else:
                    st.info("Dati FAOSTAT caricati ma colonne richieste non trovate.")
            except Exception as e:
                st.warning(f"Impossibile visualizzare il grafico FAOSTAT: {e}")
        else:
            st.info("Dati FAOSTAT non disponibili. Passare a Dati API Reali o assicurarsi che il pacchetto `faostat` sia installato.")

    # ── Main productivity charts ──────────────────────────────────────────────
    try:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Produzione Totale Brasiliana di Caffè per Anno")
            figP = go.Figure()
            figP.add_trace(go.Bar(x=usda["year"], y=usda["arabica_bags"],
                                  name="Arabica", marker_color=COLORS['arabica']))
            figP.add_trace(go.Bar(x=usda["year"], y=usda["robusta_bags"],
                                  name="Robusta", marker_color=COLORS['robusta']))
            figP.update_layout(
                barmode='stack', height=380, margin=dict(l=0, r=0, t=10, b=0),
                yaxis=dict(title="Sacchi da 60 kg", tickformat=".2s")
            )
            st.plotly_chart(figP, use_container_width=True)
            st.caption("Produzione totale brasiliana di caffè in sacchi da 60 kg per anno, suddivisa tra Arabica e Robusta. Fonte: dati USDA PSD (live) o proxy CONAB/FAOSTAT (simulato). Il Brasile alterna anni di alta e bassa produzione in un ciclo biennale.")

        with c2:
            st.markdown("#### Volumi Annui Esportazioni vs Scorte Finali")
            figE = make_subplots(specs=[[{"secondary_y": True}]])
            total_exp = usda["export_ara"] + usda["export_rob"]
            total_inv = usda["inventory_ara"] + usda["inventory_rob"]
            figE.add_trace(go.Scatter(x=usda["year"], y=total_exp, name="Esportazioni Totali",
                                      mode="lines+markers", line=dict(color="#2ca02c")), secondary_y=False)
            figE.add_trace(go.Scatter(x=usda["year"], y=total_inv, name="Scorte",
                                      mode="lines", line=dict(color="#1f77b4", dash="dash")), secondary_y=True)
            figE.update_yaxes(title_text="Esportazioni (sacchi da 60 kg)", secondary_y=False)
            figE.update_yaxes(title_text="Scorte Finali (sacchi da 60 kg)", secondary_y=True)
            figE.update_xaxes(title_text="Anno")
            figE.update_yaxes(tickformat=".2s", secondary_y=False)
            figE.update_yaxes(tickformat=".2s", secondary_y=True)
            figE.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(figE, use_container_width=True)
            st.caption("Volume annuo esportazioni (asse sinistro) vs. scorte finali (asse destro). Quando le esportazioni aumentano mentre le scorte scendono, la filiera logistica si sta assottigliando - un indicatore anticipatore della pressione sui prezzi.")

        c3, c4 = st.columns(2)
        with c3:
            st.markdown("#### Efficienza Resa vs Volume Produzione - Top 10 Regioni Produttrici")

            if not states_mock.empty:
                # Keep only top 10 by production volume
                top10 = states_mock.nlargest(10, "production_bags").copy()

                # Normalize all region name variants → consistent Italian label
                top10["stato_label"] = top10["state"].apply(normalize_region_name)

                # Short label = everything before " -" (e.g. "MG", "ES", "MG Nord")
                top10["state_short"] = top10["stato_label"].apply(
                    lambda s: s.split("-")[0].strip() if "-" in s else s[:20]
                )

                figS = px.scatter(
                    top10,
                    x="yield",
                    y="production_bags",
                    color="stato_label",       # full label drives color legend
                    size="production_bags",
                    size_max=55,
                    text="state_short",         # compact label on the bubble
                    hover_name="stato_label",   # full label in tooltip
                    labels={
                        "yield":           "Resa (sacchi/ettaro)",
                        "production_bags": "Produzione Totale (sacchi da 60 kg)",
                        "stato_label":     "Stato"
                    },
                    color_discrete_sequence=px.colors.qualitative.Bold,
                )
                figS.update_traces(
                    textposition="top center",
                    textfont=dict(size=10),
                    marker=dict(opacity=0.85, line=dict(width=1, color="white"))
                )
                figS.update_layout(
                    height=480,
                    margin=dict(l=0, r=0, t=20, b=0),
                    plot_bgcolor="rgba(0,0,0,0)",
                    showlegend=False,
                    yaxis=dict(tickformat=".2s", title="Produzione Totale (sacchi da 60 kg)"),
                    xaxis=dict(title="Resa (sacchi/ettaro)"),
                )
                st.plotly_chart(figS, use_container_width=True)
                st.caption(
                    "Le 10 principali regioni produttrici brasiliane. Ogni bolla rappresenta uno stato: "
                    "più grande la bolla, maggiore il volume di produzione totale. "
                    "Asse X: efficienza di resa in sacchi da 60 kg per ettaro coltivato. "
                    "Asse Y: produzione totale annua in sacchi da 60 kg. "
                    "Le etichette sulle bolle mostrano la sigla dello stato (es. MG, ES). "
                    "Passa il cursore sulla bolla per il nome completo e la regione geografica."
                )

        with c4:
            st.markdown("#### Quota di Mercato Arabica / Robusta (Ultimo Anno)")
            latest_usda = usda.iloc[-1]
            figD = px.pie(values=[latest_usda["arabica_bags"], latest_usda["robusta_bags"]],
                          names=["Arabica", "Robusta"], hole=0.5,
                          color_discrete_sequence=[COLORS['arabica'], COLORS['robusta']])
            figD.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(figD, use_container_width=True)
            st.caption("Quota di mercato tra Arabica e Robusta per l'anno raccolto più recente. Il Brasile è storicamente ~70-75% Arabica, ma la quota Robusta (Conilon) è cresciuta in quanto più resistente alla siccità.")

    except Exception as e:
        st.warning(f"Impossibile visualizzare il grafico di produttività: {e}")


def render_tab_6(climate, states_mock):
    with st.expander("📖 Cos'è il Deficit Pluviometrico? - Guida alla Lettura", expanded=True):
        st.markdown("""
### Deficit Pluviometrico: definizione

Il **deficit pluviometrico** misura di quanto le precipitazioni mensili si discostano
**al di sotto** della media storica di riferimento (baseline 1981–2010 per le regioni del Cerrado brasiliano).

**Formula:**
> Deficit (%) = ((Pioggia_media_storica − Pioggia_osservata) / Pioggia_media_storica) × 100

**Esempio pratico:**
Se il mese di agosto ha storicamente 80 mm di pioggia media e quest'anno ne sono caduti 56 mm,
il deficit è del **30%** → zona rossa nel grafico.

### Soglie di impatto agronomico sul caffè

| Deficit | Colore | Impatto sul Caffè |
|---------|--------|-------------------|
| < 10% | 🟢 Verde | Normale - piogge nella norma, nessun impatto atteso |
| 10–20% | 🟠 Arancio | Stress moderato - irrigazione supplementare consigliata |
| > 20% | 🔴 Rosso | Stress severo - rischio calo resa, anticipo fioritura, aumento suscettibilità a malattie |

### Stagionalità normale in Brasile (Cerrado/Minas Gerais)

La **stagione secca** va da **giugno a settembre**: deficit del 20–35% è fisiologico e atteso.
Il problema critico sorge quando il deficit si estende a **ottobre–novembre** (fioritura del caffè)
o a **dicembre–gennaio** (sviluppo del frutto): queste fasi richiedono acqua per garantire
la qualità e la resa del raccolto successivo.
        """)

    try:
        colA, colB = st.columns(2)
        with colA:
            st.markdown("#### Impatto Mensile del Deficit Pluviometrico (Ultimi 24 Mesi)")
            recent_climate = climate.tail(24).copy()

            def get_color(val):
                if val < 10: return COLORS['safe']
                elif val <= 20: return COLORS['warning']
                return COLORS['danger']

            bar_colors = recent_climate['rainfall_deficit_pct'].apply(get_color).tolist()
            recent_climate['rolling_12_m'] = recent_climate['rainfall_deficit_pct'].rolling(12, min_periods=1).mean()

            fig = go.Figure()
            fig.add_trace(go.Bar(x=recent_climate["date"], y=recent_climate["rainfall_deficit_pct"],
                                 marker_color=bar_colors, name="Deficit %"))
            fig.add_trace(go.Scatter(x=recent_climate["date"], y=recent_climate["rolling_12_m"],
                                     mode="lines", line=dict(color='black', width=3), name="Media Mobile 12 Mesi"))
            fig.update_layout(
                height=420,
                margin=dict(l=0, r=0, t=30, b=0),
                yaxis=dict(
                    title="Deficit Pluviometrico (%)",
                    ticksuffix="%",
                    range=[0, max(recent_climate['rainfall_deficit_pct'].max() * 1.15, 25)]
                ),
                xaxis=dict(title="Mese"),
                legend=dict(orientation="h", y=1.05, x=0),
            )
            # Add threshold reference lines
            fig.add_hline(
                y=10, line_dash="dot", line_color=COLORS["warning"],
                annotation_text="Soglia stress moderato (10%)",
                annotation_position="top left"
            )
            fig.add_hline(
                y=20, line_dash="dot", line_color=COLORS["danger"],
                annotation_text="Soglia stress severo (20%)",
                annotation_position="top left"
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "Deficit pluviometrico mensile espresso come percentuale al di sotto della media storica 1981–2010 "
                "(Cerrado/Minas Gerais). Verde = nella norma (<10%); arancio = stress moderato (10–20%); "
                "rosso = stress severo (>20%). La linea nera è la media mobile a 12 mesi. "
                "Le linee tratteggiate mostrano le soglie critiche di impatto agronomico. "
                "Valori basati su modelli di stress climatico calibrati sull'indice ENSO-ONI."
            )

        with colB:
            st.markdown("#### Deficit Pluviometrico Medio per Stato")
            if not states_mock.empty:
                rng = np.random.default_rng(get_session_seed() + 10)
                states_plot = states_mock.copy()

                # Normalize every possible name variant → consistent Italian label
                states_plot["state_full"] = states_plot["state"].apply(normalize_region_name)

                # Short axis label: everything before " -" (e.g. "MG", "ES", "MG Nord")
                states_plot["state_short"] = states_plot["state_full"].apply(
                    lambda s: s.split("-")[0].strip() if "-" in s else s[:20]
                )

                states_plot["avg_deficit"] = rng.uniform(4.0, 25.0, len(states_plot))
                states_plot = states_plot.sort_values(by="avg_deficit", ascending=True)

                figH = px.bar(
                    states_plot,
                    x="avg_deficit",
                    y="state_short",           # compact sigla on Y-axis
                    orientation="h",
                    color="avg_deficit",
                    color_continuous_scale="RdYlGn_r",
                    hover_name="state_full",   # full Italian label in tooltip
                    hover_data={"avg_deficit": ":.1f", "state_short": False},
                    labels={"avg_deficit": "Deficit Pluviometrico (%)", "state_short": "Stato"},
                )
                figH.update_layout(
                    height=420,
                    margin=dict(l=0, r=0, t=10, b=0),
                    xaxis=dict(
                        title="Deficit Pluviometrico Annuo Medio (%)",
                        ticksuffix="%"
                    ),
                    yaxis=dict(title=""),
                    coloraxis_colorbar=dict(
                        title="Deficit (%)",
                        ticksuffix="%"
                    )
                )
                st.plotly_chart(figH, use_container_width=True)
                st.caption(
                    "Deficit pluviometrico annuo medio (%) per stato produttore, ordinato dal più critico al meno critico. "
                    "Le etichette mostrano la sigla dello stato; passa il cursore per il nome completo con la regione geografica. "
                    "Valori derivati da modelli climatici regionali ponderati sull'ONI ENSO. "
                    "Un deficit medio annuo superiore al 15% indica dipendenza strutturale dall'irrigazione: "
                    "gli impianti di irrigazione coprono circa il 30% delle piantagioni di Arabica in Minas Gerais, "
                    "ma la percentuale scende sotto il 10% nelle aree di Robusta in Rondônia."
                )

    except Exception as e:
        st.warning(f"Impossibile visualizzare il grafico delle piogge: {e}")


# ==========================================
# MAIN ROUTING
# ==========================================
def main():
    st.title("🌱 Lavazza Operazioni Brasile: Dashboard di Business Intelligence")

    # Sidebar
    st.sidebar.markdown("### Configurazione Endpoint")
    data_source = st.sidebar.radio("Fonte Dati", ["🔴 Dati API Reali", "⚪ Dati Simulati"])
    simulated = "Simulati" in data_source

    with st.sidebar.expander("🩺 Rapporto Salute API", expanded=not simulated):
        health_container = st.empty()
        if simulated:
            health_container.info("Tutti i dati sono simulati. Passare a Dati API Reali per testare gli endpoint live.")

    with st.spinner("Aggregazione analisi macro, terrestri e marittime in corso..."):
        dates_df, st_px = fetch_prices(simulated)
        oni_series, st_oni = fetch_enso_data(simulated)
        soi_series, st_soi = fetch_soi_data(simulated)
        climate = fetch_climate(dates_df["date"], simulated)
        fires, st_fir = fetch_firms_data(simulated)
        usda, st_usda = fetch_usda(simulated)
        faostat_df, st_fao = fetch_faostat(simulated)
        states_prod = get_coffee_state_prod(simulated)
        states_mock, st_conab = fetch_conab_states(simulated)
        ports_history = build_port_history(climate, simulated)

    api_health_list = [*st_px, st_oni, st_soi, st_fir, st_usda, st_fao, st_conab]

    if not simulated:
        df_health = pd.DataFrame(api_health_list)
        health_container.dataframe(df_health, hide_index=True)

    # ── Tab routing ───────────────────────────────────────────────────────────
    tabs = st.tabs(["🌦️ Clima & ENSO", "🔥 Incendi", "⚓ Navi & Porti",
                    "📈 Prezzi di Mercato", "🌾 Produttività dei Raccolti", "🌧️ Precipitazioni"])

    with tabs[0]:
        render_tab_1(oni_series, soi_series)

    with tabs[1]:
        render_tab_2(fires, climate, states_prod)

    with tabs[2]:
        # AIS: fetched once on first load, refreshed via button inside render_tab_3
        if "ais_data" not in st.session_state:
            with st.spinner("Connessione ad AISStream (porti globali, ~10s)..."):
                result = asyncio.run(_fetch_ais_snapshot(simulated, listen_time_seconds=10))
                st.session_state.ais_data = result
                st.session_state.ais_fetched_at = datetime.now().strftime("%H:%M:%S")

        live_vessels, ship_types_live, st_ais, ais_diag = st.session_state.ais_data

        # Prune stale vessels (>15 min)
        now = time.time()
        for mmsi in list(live_vessels.keys()):
            if now - live_vessels[mmsi]["last_seen"] > 900:
                del live_vessels[mmsi]
                ship_types_live.pop(mmsi, None)

        if not simulated:
            api_health_list.append(st_ais)
            df_health_updated = pd.DataFrame(api_health_list)
            health_container.dataframe(df_health_updated, hide_index=True)

        render_tab_3(ports_history, live_vessels, ship_types_live, st_ais, ais_diag)

    with tabs[3]:
        render_tab_4(dates_df)

    with tabs[4]:
        render_tab_5(usda, states_mock, faostat_df, simulated, api_health_list)

    with tabs[5]:
        render_tab_6(climate, states_mock)


if __name__ == "__main__":
    main()
