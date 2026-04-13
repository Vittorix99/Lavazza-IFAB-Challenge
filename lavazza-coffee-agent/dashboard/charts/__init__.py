"""
charts/ — Package grafici Plotly per Lavazza Coffee Intelligence Dashboard.

Struttura:
  _config.py          — costanti, colori, URL API
  _data_sim.py        — dati simulati (fallback)
  _data_mongo.py      — estrattori MongoDB
  _data_api.py        — fetch API live (NOAA, NASA, WB, USDA, yfinance/faostat)
  _loader.py          — _load(): MongoDB → API → Simulato
  tabs_environment.py — render_enso_tab, render_fires_tab, render_climate_tab
  tabs_prices.py      — render_prices_tab, render_fertilizers_tab
  tabs_crops.py       — render_yields_tab, render_ibge_comex_tab
  tabs_logistics.py   — render_ports_tab
  _registry.py        — DASHBOARD_TABS, render_dashboard_tab, build_chart

Punto d'ingresso per app.py:
  render_dashboard_tab(tab_key, country, use_api, key_prefix)
"""

from ._config import COLORS, MONTH_NAMES
from ._registry import (
    DASHBOARD_TABS,
    CHART_REGISTRY,
    DASHBOARD_SOURCES,
    render_dashboard_tab,
    build_chart,
)
from .tabs_environment import render_enso_tab, render_fires_tab, render_climate_tab
from .tabs_prices import render_prices_tab, render_fertilizers_tab
from .tabs_crops import render_yields_tab, render_ibge_comex_tab
from .tabs_logistics import render_ports_tab

__all__ = [
    # Registry / entry point
    "DASHBOARD_TABS",
    "CHART_REGISTRY",
    "DASHBOARD_SOURCES",
    "render_dashboard_tab",
    "build_chart",
    # Individual render functions
    "render_enso_tab",
    "render_fires_tab",
    "render_climate_tab",
    "render_prices_tab",
    "render_fertilizers_tab",
    "render_yields_tab",
    "render_ibge_comex_tab",
    "render_ports_tab",
    # Constants
    "COLORS",
    "MONTH_NAMES",
]
