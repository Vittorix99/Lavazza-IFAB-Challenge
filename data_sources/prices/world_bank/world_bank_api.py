import re
import os
import numpy as np
import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec
from scipy import stats
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pymongo import MongoClient
from pathlib import Path

# --- 0. CONFIG ---
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB  = os.getenv("MONGODB_DB",  "lavazza_ifab")

COMMODITY_MARKETS_URL = "https://www.worldbank.org/en/research/commodity-markets"
LINK_FX = "https://open.er-api.com/v6/latest/USD"
BASE_DIR = Path(__file__).resolve().parent

# --- 1. TROVA URL EXCEL DINAMICAMENTE ---
print("Ricerca URL aggiornato Pink Sheet in corso...")
page_response = requests.get(COMMODITY_MARKETS_URL, timeout=20)
page_response.raise_for_status()

match = re.search(
    r'https://thedocs\.worldbank\.org/en/doc/[^"\']+CMO-Historical-Data-Monthly\.xlsx',
    page_response.text
)
if not match:
    raise RuntimeError("URL del Pink Sheet non trovato nella pagina commodity-markets")

LINK_WB = match.group(0)
print(f"URL trovato: {LINK_WB}")

# --- 2. TASSO DI CAMBIO (USD → EUR) ---
print("Recupero tasso di cambio USD/EUR in corso...")
fx_response = requests.get(LINK_FX, timeout=10)
fx_response.raise_for_status()
usd_to_eur = fx_response.json()['rates']['EUR']
print(f"Tasso di cambio attuale applicato: 1 USD = {usd_to_eur:.4f} EUR")

# --- 3. SCARICA PINK SHEET ---
print("Scaricamento dati dalla World Bank in corso...")
response = requests.get(LINK_WB, timeout=30)
response.raise_for_status()

file_path = BASE_DIR / "monthly_prices.xlsx"
with open(file_path, "wb") as f:
    f.write(response.content)

sheet = pd.ExcelFile(file_path)
df = pd.read_excel(file_path, sheet_name=sheet.sheet_names[1], header=[3, 4])

# Trova colonne caffè
coffee_cols = [
    col for col in df.columns
    if 'coffee' in str(col[0]).lower() or 'coffee' in str(col[1]).lower()
]
date_col = df.columns[0]

df_coffee = df[[date_col] + coffee_cols].copy()

if len(df_coffee.columns) == 3:
    df_coffee.columns = ['Date', 'Arabica', 'Robusta']
else:
    raise ValueError(f"Attenzione: mi aspettavo 3 colonne totali, ma ne ho trovate {len(df_coffee.columns)}.")

# Pulizia e conversione in EUR
df_coffee['Date'] = df_coffee['Date'].astype(str).str.replace('M', '-')
df_coffee['Date'] = pd.to_datetime(df_coffee['Date'], errors='coerce')
df_coffee['Date'] = df_coffee['Date'].dt.to_period('M').dt.to_timestamp()
df_coffee = df_coffee.dropna(subset=['Date'])

df_coffee['Arabica'] = pd.to_numeric(df_coffee['Arabica'], errors='coerce') * usd_to_eur
df_coffee['Robusta'] = pd.to_numeric(df_coffee['Robusta'], errors='coerce') * usd_to_eur

# --- 4. PREPARAZIONE DATI PER MONGODB ---
collected_at = datetime.utcnow()

df_melted = pd.melt(
    df_coffee,
    id_vars=['Date'],
    value_vars=['Arabica', 'Robusta'],
    var_name='commodity',
    value_name='price_eur'
)

df_melted['commodity']     = df_melted['commodity'].str.lower()
df_melted                  = df_melted.rename(columns={'Date': 'date'})
df_melted['currency_pair'] = 'EUR/kg'
df_melted['source']        = 'world_bank_pink_sheet'
df_melted['source_url']    = LINK_WB
df_melted['country']       = 'BR'
df_melted['macroarea']     = 'prices'
df_melted['collected_at']  = collected_at

mongo_cols = ['commodity', 'date', 'price_eur', 'currency_pair',
              'source', 'source_url', 'country', 'macroarea', 'collected_at']
df_mongo = df_melted[mongo_cols].copy()
df_mongo_db = df_mongo.replace({np.nan: None})

records = df_mongo_db.to_dict('records')
print(f"\nAnteprima dati pronti per MongoDB (in EUR):")
print(df_mongo_db.tail())

# --- 5. INSERT SU MONGODB ---
print("\nInserimento in MongoDB...")
client = MongoClient(MONGODB_URI)
db     = client[MONGODB_DB]
result = db["raw_prices"].insert_many(records)
print(f"Inseriti {len(result.inserted_ids)} documenti in raw_prices")

# Ingestion log
db["ingestion_log"].insert_one({
    "source":       "WB_PINK_SHEET",
    "country":      "BR",
    "run_date":     collected_at.isoformat(),
    "status":       "done",
    "completed_at": collected_at.isoformat()
})
print("Ingestion log scritto")
client.close()

# --- 6. VISUALIZZAZIONE ---
print("\nGenerazione dashboard analitica in corso...")

df_plot = df_coffee.dropna(subset=['Arabica', 'Robusta', 'Date']).copy()
df_plot = df_plot.sort_values('Date').reset_index(drop=True)
df_plot['Spread'] = df_plot['Arabica'] - df_plot['Robusta']

dates   = df_plot['Date']
arabica = df_plot['Arabica']
robusta = df_plot['Robusta']
spread  = df_plot['Spread']

ma12_arabica  = arabica.rolling(12).mean()
std12_arabica = arabica.rolling(12).std()
upper_band_a  = ma12_arabica + std12_arabica
lower_band_a  = ma12_arabica - std12_arabica
ma12_robusta  = robusta.rolling(12).mean()

volatility_arabica = arabica.pct_change().rolling(12).std() * np.sqrt(12) * 100
volatility_robusta = robusta.pct_change().rolling(12).std() * np.sqrt(12) * 100

curr_a = arabica.iloc[-1]
curr_r = robusta.iloc[-1]
pct_a  = stats.percentileofscore(arabica.dropna(), curr_a)
pct_r  = stats.percentileofscore(robusta.dropna(), curr_r)

LAVAZZA_BLUE       = "#00205B"
GOLD               = "#C49A45"
BROWN              = "#5C3A21"
ALERT_RED          = "#D32F2F"
OPPORTUNITY_GREEN  = "#2E7D32"
GRAY               = "#808080"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": "#EFEFEF",
    "grid.linestyle": "--",
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})

fig = plt.figure(figsize=(18, 18))
gs  = GridSpec(4, 2, figure=fig, hspace=0.45, wspace=0.25, top=0.92, bottom=0.06)

ax1 = fig.add_subplot(gs[0:2, :])
ax2 = fig.add_subplot(gs[2, :])
ax3 = fig.add_subplot(gs[3, 0])
ax4 = fig.add_subplot(gs[3, 1])

fig.text(0.5, 0.965, "Lavazza Procurement Intelligence: Mercato Globale del Caffè",
         ha="center", fontsize=18, fontweight="bold", color=LAVAZZA_BLUE)
fig.text(0.5, 0.945, f"Analisi di Rischio, Volatilità e Spread (Fonte: World Bank) | Valuta: EUR/kg (Tasso 1 USD = {usd_to_eur:.4f} EUR)",
         ha="center", fontsize=11, color=GRAY)

ax1.plot(dates, arabica, color=GOLD, alpha=0.9, linewidth=1.5, label="Prezzo Spot Arabica")
ax1.plot(dates, robusta, color=BROWN, alpha=0.9, linewidth=1.5, label="Prezzo Spot Robusta")
ax1.plot(dates, ma12_arabica, color=GOLD, linestyle="--", linewidth=2, label="Trend Arabica (Media 12m)")
ax1.fill_between(dates, lower_band_a, upper_band_a, color=GOLD, alpha=0.15, label="Fascia di Normalità Arabica (±1 Dev. Std)")
ax1.annotate(f"Attuale: €{curr_a:.2f}", xy=(dates.iloc[-1], curr_a),
             xytext=(10, 5), textcoords="offset points", fontweight='bold', color=GOLD, fontsize=11)
ax1.annotate(f"Attuale: €{curr_r:.2f}", xy=(dates.iloc[-1], curr_r),
             xytext=(10, -10), textcoords="offset points", fontweight='bold', color=BROWN, fontsize=11)
ax1.set_title("Dinamica dei Prezzi e Deviazione dal Trend (EUR/kg)", fontweight="bold", color=LAVAZZA_BLUE, pad=10)
ax1.set_ylabel("Prezzo EUR/kg")
ax1.legend(loc="upper left", framealpha=0.9)

mean_spread = spread.mean()
std_spread  = spread.std()
high_spread = mean_spread + std_spread
low_spread  = mean_spread - std_spread

ax2.plot(dates, spread, color=LAVAZZA_BLUE, linewidth=1.5)
ax2.axhline(mean_spread, color=GRAY, linestyle="-", linewidth=1.5, label=f"Media Storica (€{mean_spread:.2f})")
ax2.axhline(high_spread, color=ALERT_RED, linestyle="--", linewidth=1.2, label="Soglia Allerta (Arabica costosa -> Focus Robusta)")
ax2.axhline(low_spread, color=OPPORTUNITY_GREEN, linestyle="--", linewidth=1.2, label="Soglia Opportunità (Arabica economica)")
ax2.fill_between(dates, spread, high_spread, where=(spread > high_spread), color=ALERT_RED, alpha=0.3)
ax2.fill_between(dates, spread, low_spread, where=(spread < low_spread), color=OPPORTUNITY_GREEN, alpha=0.3)
ax2.set_title("Differenziale Arabica - Robusta: Segnali per Ottimizzazione Blend", fontweight="bold", color=LAVAZZA_BLUE, pad=10)
ax2.set_ylabel("Spread (EUR/kg)")
ax2.legend(loc="upper left")

ax3.plot(dates, volatility_arabica, color=GOLD, linewidth=1.5, label="Volatilità Arabica")
ax3.plot(dates, volatility_robusta, color=BROWN, linewidth=1.5, label="Volatilità Robusta")
ax3.axhline(30, color=ALERT_RED, linestyle=":", linewidth=1.5, label="Soglia Rischio Alto (>30%)")
ax3.set_title("Indice di Volatilità Annualizzata (Rischio)", fontweight="bold", color=LAVAZZA_BLUE, pad=10)
ax3.set_ylabel("Volatilità (%)")
ax3.legend(loc="upper left")

ax4.hist(arabica, bins=40, alpha=0.5, color=GOLD, label="Distribuzione Arabica storici", density=True)
ax4.hist(robusta, bins=40, alpha=0.5, color=BROWN, label="Distribuzione Robusta storici", density=True)
ax4.axvline(curr_a, color=GOLD, linestyle="-", linewidth=2.5)
ax4.axvline(curr_r, color=BROWN, linestyle="-", linewidth=2.5)
ax4.text(curr_a, ax4.get_ylim()[1] * 0.8, f"Oggi:\n{pct_a:.0f}° Percentile",
         color=GOLD, fontweight='bold', ha='right' if pct_a > 50 else 'left',
         bbox=dict(facecolor='white', alpha=0.7, edgecolor='none'))
ax4.text(curr_r, ax4.get_ylim()[1] * 0.6, f"Oggi:\n{pct_r:.0f}° Percentile",
         color=BROWN, fontweight='bold', ha='right' if pct_r > 50 else 'left',
         bbox=dict(facecolor='white', alpha=0.7, edgecolor='none'))
ax4.set_title("Stress Test: Il Prezzo di Oggi rispetto alla Storia", fontweight="bold", color=LAVAZZA_BLUE, pad=10)
ax4.set_xlabel("Prezzo (EUR/kg)")
ax4.set_yticks([])
ax4.legend(loc="upper center")

out_path = BASE_DIR / "world_bank_dashboard_lavazza.png"
plt.savefig(out_path, dpi=160, bbox_inches="tight", facecolor="white")
print(f"Grafico salvato con successo: {out_path}")
