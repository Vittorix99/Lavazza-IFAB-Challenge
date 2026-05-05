"""_data_mongo.py — Estrattori MongoDB: leggono raw_* e restituiscono DataFrame."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.db import get_latest_doc  # noqa: E402

from ._config import STATE_COORDS


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
    Costruisce DataFrame prezzi dal WB_PINK_SHEET + BCB_PTAX + ECB in MongoDB.
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
            arabica_usd = pd.to_numeric(df[ara_col], errors="coerce")
            df["arabica_eur_kg"] = arabica_usd / usd_per_eur
            df["robusta_eur_kg"] = ((pd.to_numeric(df[rob_col], errors="coerce") / usd_per_eur)
                                    if rob_col else df["arabica_eur_kg"] * 0.45)
            df["fx_brl_per_eur"] = fx_brl_eur
            df["usd_per_eur"] = usd_per_eur  # tasso reale ECB/BCB — usato dal grafico fertilizzanti
            df["arabica_brl_kg"] = arabica_usd * brl_usd
            result = (df[["date", "arabica_eur_kg", "robusta_eur_kg",
                           "fx_brl_per_eur", "usd_per_eur", "arabica_brl_kg"]]
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
    fert_cols = [c for c in ["dap_usd_t", "urea_usd_t", "potash_usd_t"] if c in result.columns]
    if not fert_cols or result[fert_cols].dropna(how="all").empty:
        return None
    return result


@st.cache_data(ttl=3600, show_spinner=False)
def _mongo_usda(country: str = "BR") -> pd.DataFrame | None:
    doc = get_latest_doc("raw_crops", "USDA_FAS_PSD", country)
    if not doc:
        return None

    MT_TO_BAGS = 16.667  # 1 MT reale = 16.667 sacchi da 60 kg
    # Dopo il fix n8n (BAG_TO_MT = 60), i valori _mt nel doc sono MT reali.
    # Se il doc è stato ingestito con il vecchio n8n (BAG_TO_MT = 60/1000000),
    # i valori sono 1.000.000x troppo piccoli → detectato dalla scala e corretto.
    _N8N_BUG_FACTOR = 1_000_000  # fattore di correzione per vecchi documenti

    # Cerca la serie annuale: prima in _chart_fields, poi in "yearly_series"
    candidates = doc.get("_chart_fields", [])
    if "yearly_series" not in candidates:
        candidates = ["yearly_series"] + list(candidates)

    for field in candidates:
        val = doc.get(field)
        if not (isinstance(val, list) and len(val) >= 2):
            continue
        df = pd.DataFrame(val)
        cols = list(df.columns)

        # Colonna anno: preferisce market_year, poi qualsiasi *year*
        year_col = (next((c for c in cols if c == "market_year"), None)
                    or next((c for c in cols if "year" in c.lower()), None))
        if not year_col:
            continue

        # -- Produzione --
        ara_mt_col = next((c for c in cols if "arabica" in c.lower()
                           and "production" in c.lower()), None)
        rob_mt_col = next((c for c in cols if "robusta" in c.lower()
                           and "production" in c.lower()), None)
        tot_mt_col = next((c for c in cols if "production_total" in c.lower()
                           or c == "production_mt"), None)

        # Se non ci sono colonne di produzione usabili, skip
        if not ara_mt_col and not tot_mt_col:
            continue

        df = df.rename(columns={year_col: "year"})
        df["year"] = pd.to_numeric(df["year"], errors="coerce")

        # Rileva se i valori sono nel vecchio formato n8n (bug BAG_TO_MT = 60/1000000)
        # Arabica production brasiliana attesa: 20M-60M MT. Se il valore max < 1000, è buggy.
        _ara_raw = pd.to_numeric(
            df[ara_mt_col] if ara_mt_col else df.get(tot_mt_col, pd.Series([0])),
            errors="coerce"
        )
        _max_val = _ara_raw.max() if not _ara_raw.empty else 0
        _correction = _N8N_BUG_FACTOR if (_max_val > 0 and _max_val < 100) else 1

        if ara_mt_col:
            df["arabica_bags"] = _ara_raw * _correction * MT_TO_BAGS
        else:
            df["arabica_bags"] = pd.to_numeric(df[tot_mt_col], errors="coerce") * _correction * MT_TO_BAGS * 0.72

        if rob_mt_col:
            df["robusta_bags"] = pd.to_numeric(df[rob_mt_col], errors="coerce") * _correction * MT_TO_BAGS
        elif tot_mt_col:
            df["robusta_bags"] = pd.to_numeric(df[tot_mt_col], errors="coerce") * _correction * MT_TO_BAGS * 0.28
        else:
            df["robusta_bags"] = df["arabica_bags"] * (28 / 72)

        # -- Export --
        exp_col = next((c for c in cols if "exports_total" in c.lower()
                        or c == "exports_mt"), None)
        if exp_col:
            exp_bags = pd.to_numeric(df[exp_col], errors="coerce") * _correction * MT_TO_BAGS
            df["export_ara"] = exp_bags * 0.72
            df["export_rob"] = exp_bags * 0.28
        else:
            df["export_ara"] = np.nan
            df["export_rob"] = np.nan

        # -- Scorte finali --
        inv_col = next((c for c in cols if "ending_stocks" in c.lower()
                        or c == "ending_stocks_mt"), None)
        if inv_col:
            inv_bags = pd.to_numeric(df[inv_col], errors="coerce") * _correction * MT_TO_BAGS
            df["inventory_ara"] = inv_bags * 0.72
            df["inventory_rob"] = inv_bags * 0.28
        else:
            df["inventory_ara"] = np.nan
            df["inventory_rob"] = np.nan

        return (df[["year", "arabica_bags", "robusta_bags",
                    "export_ara", "export_rob",
                    "inventory_ara", "inventory_rob"]]
                .dropna(subset=["arabica_bags"])
                .sort_values("year")
                .reset_index(drop=True))

    return None


@st.cache_data(ttl=3600, show_spinner=False)
def _mongo_faostat(country: str = "BR") -> pd.DataFrame | None:
    doc = (get_latest_doc("raw_crops", "FAOSTAT", country)
           or get_latest_doc("raw_crops", "FAOSTAT_QCL", country))
    if not doc:
        return None
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

    _uf_to_name = {v[0]: k for k, v in STATE_COORDS.items()}

    for field in ["top_states_by_production", "all_states", "focus_states"]:
        states = doc.get(field)
        if not (isinstance(states, list) and len(states) >= 2):
            continue
        df = pd.DataFrame(states)
        cols = list(df.columns)

        prod_col = next(
            (c for c in cols if "production" in str(c).lower() and "mt" in str(c).lower()),
            next((c for c in cols if "production" in str(c).lower()), None)
        )
        if not prod_col:
            continue

        yield_col = next((c for c in cols if "yield" in str(c).lower()), None)

        if "state" in cols and "uf" in cols:
            state_series = df["state"].astype(str)
        elif "state" in cols:
            state_series = df["state"].astype(str)
        elif "uf" in cols:
            state_series = df["uf"].astype(str).map(lambda u: _uf_to_name.get(u, u))
        else:
            continue

        out = pd.DataFrame()
        out["state"] = state_series
        out["production_bags"] = pd.to_numeric(df[prod_col], errors="coerce").fillna(0)
        out["yield"] = pd.to_numeric(df[yield_col], errors="coerce").fillna(0) if yield_col else 0.0

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
    """
    doc = get_latest_doc("raw_crops", "IBGE_SIDRA_LSPA", country)
    if not doc:
        return None

    state_focus_list = doc.get("state_focus_latest") or []
    national = doc.get("national_latest") or {}
    period_label = doc.get("latest_period_label") or "Latest"

    rows = []

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

    recent = doc.get("recent_series", [])
    if recent:
        df = pd.DataFrame(recent)
        if "period" in df.columns:
            df["period"] = df["period"].astype(str)
            for col in ["total_exports_fob_usd", "total_exports_kg", "avg_fob_usd_per_kg"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            result["recent_series"] = df

    dest_raw = doc.get("top_destinations", []) or doc.get("destinations_series", [])
    if dest_raw:
        result["destinations"] = dest_raw

    pm = doc.get("product_mix", {})
    if pm:
        result["product_mix"] = pm

    result["derived_metrics"] = doc.get("derived_metrics", {})
    result["latest_month"] = doc.get("latest_month", {})
    result["previous_month"] = doc.get("previous_month", {})
    result["summary_en"] = doc.get("summary_en", "")

    return result if result else None


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
