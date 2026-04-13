"""_config.py — Costanti e URL per il package charts."""

import os

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
