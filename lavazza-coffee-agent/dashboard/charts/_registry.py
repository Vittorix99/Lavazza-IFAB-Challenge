"""_registry.py — Mappa tab_key → render function e interfaccia pubblica."""

import streamlit as st

from .tabs_environment import render_enso_tab, render_fires_tab, render_climate_tab
from .tabs_prices import render_prices_tab, render_fertilizers_tab
from .tabs_crops import render_yields_tab, render_ibge_comex_tab
from .tabs_logistics import render_ports_tab

# Mapping tab_name → render function
_TAB_RENDERERS: dict[str, callable] = {
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


def render_dashboard_tab(tab_key: str, country: str = "BR",
                          use_api: bool = False, key_prefix: str = "") -> None:
    """
    Punto d'ingresso per Dashboard Visiva.
    tab_key: uno tra "enso", "fires", "prices", "yields", "climate",
             "ibge_comex", "ports", "fertilizers"
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
