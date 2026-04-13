"""_data_sim.py — Dati simulati (fallback numpy+pandas sempre disponibile)."""

import numpy as np
import pandas as pd

from ._config import (
    COLORS, MONTH_NAMES, COFFEE_STATE_PROD, STATE_COORDS, PORTS, _SEED,
)


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
