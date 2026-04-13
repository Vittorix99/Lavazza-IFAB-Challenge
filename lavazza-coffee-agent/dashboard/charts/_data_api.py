"""_data_api.py — Fetch API live (NOAA, NASA, WB, USDA, yfinance/faostat)."""

import io
import os

import numpy as np
import pandas as pd
import streamlit as st

from ._config import (
    MONTH_NAMES, NOAA_ONI_URL, NOAA_SOI_URL, FIRMS_MAP_KEY,
    USDA_BASE_URL, USDA_COMMODITY, USDA_COUNTRY, USDA_TARGET_ATTRS, WB_MONTHLY_URL,
)


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
        # EUR/BRL — quanti BRL per 1 EUR
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
        import yfinance as yf
        # EUR/USD — quanti USD per 1 EUR (e.g. 1.08)
        raw_eurusd = yf.download("EURUSD=X", period="12y", interval="1mo",
                                 auto_adjust=True, progress=False)
        if isinstance(raw_eurusd.columns, pd.MultiIndex):
            raw_eurusd.columns = raw_eurusd.columns.get_level_values(0)
        raw_eurusd = raw_eurusd[["Close"]].rename(columns={"Close": "usd_per_eur"})
        raw_eurusd.index = pd.to_datetime(raw_eurusd.index).to_period("M").to_timestamp("M")
        raw_eurusd = raw_eurusd.reset_index().rename(columns={"index": "date", "Date": "date"})
        raw_eurusd["date"] = pd.to_datetime(raw_eurusd["date"])
        raw_eurusd = raw_eurusd.dropna(subset=["usd_per_eur"])
    except Exception:
        raw_eurusd = pd.DataFrame(columns=["date", "usd_per_eur"])

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

        # Merge EUR/USD rate (real, from yfinance)
        if not raw_eurusd.empty:
            raw_eurusd["date"] = raw_eurusd["date"] + pd.offsets.MonthEnd(0)
            coffee = pd.merge_asof(coffee.sort_values("date"), raw_eurusd.sort_values("date"),
                                   on="date", direction="nearest",
                                   tolerance=pd.Timedelta(days=45))
            coffee["usd_per_eur"] = coffee["usd_per_eur"].ffill(limit=3)
        else:
            coffee["usd_per_eur"] = None  # no fallback — propagate None

        coffee = coffee.dropna(subset=["usd_per_eur"])
        # USD/kg → EUR/kg: divido per il tasso EUR/USD (1 EUR = usd_per_eur USD)
        coffee["arabica_eur_kg"] = coffee["arabica_usd_kg"] / coffee["usd_per_eur"]
        coffee["robusta_eur_kg"] = coffee["robusta_usd_kg"] / coffee["usd_per_eur"]

        # Merge EUR/BRL rate
        if not raw_fx.empty:
            raw_fx["date"] = raw_fx["date"] + pd.offsets.MonthEnd(0)
            coffee = pd.merge_asof(coffee.sort_values("date"), raw_fx.sort_values("date"),
                                   on="date", direction="nearest",
                                   tolerance=pd.Timedelta(days=45))
            coffee["fx_brl_per_eur"] = coffee["fx_brl_per_eur"].ffill(limit=3)
        else:
            coffee["fx_brl_per_eur"] = None

        coffee = coffee.dropna(subset=["arabica_eur_kg", "fx_brl_per_eur"])
        # USD/kg → BRL/kg: arabica_usd * (BRL/EUR) / (USD/EUR) = arabica_usd * BRL/USD
        coffee["arabica_brl_kg"] = coffee["arabica_usd_kg"] * (
            coffee["fx_brl_per_eur"] / coffee["usd_per_eur"]
        )
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
        # USDA PSD restituisce valori in "1.000 sacchi da 60 kg" (non in MT).
        # 1 unità USDA = 1.000 sacchi → moltiplica per 1000 per avere sacchi individuali.
        USDA_UNIT_TO_BAGS = 1000
        ARA, ROB = 0.72, 0.28
        for col_usda, ara_col, rob_col in [
            ("production_mt",    "arabica_bags",  "robusta_bags"),
            ("exports_mt",       "export_ara",    "export_rob"),
            ("ending_stocks_mt", "inventory_ara", "inventory_rob"),
        ]:
            if col_usda in df_last.columns:
                total_bags = pd.to_numeric(df_last[col_usda], errors="coerce") * USDA_UNIT_TO_BAGS
                df_last[ara_col] = total_bags * ARA
                df_last[rob_col] = total_bags * ROB
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

        raw = pd.read_excel(content, sheet_name=xls.sheet_names[1], header=[3, 4])
        date_col = raw.columns[0]

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
