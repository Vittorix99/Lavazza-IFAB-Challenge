import os
import requests
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec
from scipy import stats
from datetime import datetime
from dateutil.relativedelta import relativedelta

# --- 1. DOWNLOAD DATI WORLD BANK E TASSO DI CAMBIO ---
LINK_WB = "https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx"
LINK_FX = "https://open.er-api.com/v6/latest/USD"

# Recupero Tasso di Cambio (Live)
print("Recupero tasso di cambio USD/EUR in corso...")
fx_response = requests.get(LINK_FX)
fx_response.raise_for_status()
usd_to_eur = fx_response.json()['rates']['EUR']
print(f"Tasso di cambio attuale applicato: 1 USD = {usd_to_eur:.4f} EUR")

# Recupero Dati World Bank
print("Scaricamento dati dalla World Bank in corso...")
response = requests.get(LINK_WB)
response.raise_for_status()

file_path = "data_sources/world_bank/monthly_prices.xlsx"
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

# Pulizia e Conversione in EUR
df_coffee['Date'] = df_coffee['Date'].astype(str).str.replace('M', '-')
df_coffee['Date'] = pd.to_datetime(df_coffee['Date'], errors='coerce')
df_coffee['Date'] = df_coffee['Date'].dt.to_period('M').dt.to_timestamp()
df_coffee = df_coffee.dropna(subset=['Date'])

# Applicazione del tasso di cambio ai valori
df_coffee['Arabica'] = pd.to_numeric(df_coffee['Arabica'], errors='coerce') * usd_to_eur
df_coffee['Robusta'] = pd.to_numeric(df_coffee['Robusta'], errors='coerce') * usd_to_eur

# --- 2. PREPARAZIONE DATI PER MONGODB ---

# Unpivot (Melt) per lo schema MongoDB
df_melted = pd.melt(
    df_coffee, 
    id_vars=['Date'], 
    value_vars=['Arabica', 'Robusta'],
    var_name='commodity', 
    value_name='price_eur'  # Rinominato da price_usd
)

# Mappatura campi
df_melted['commodity'] = df_melted['commodity'].str.lower()
df_melted = df_melted.rename(columns={'Date': 'date'})
df_melted['currency_pair'] = 'EUR/kg' # Aggiornato in EUR
df_melted['source'] = 'world_bank_api'
df_melted['collected_at'] = datetime.now()

# Ordine finale e conversione NaN in None
mongo_cols = ['commodity', 'date', 'price_eur', 'currency_pair', 'source', 'collected_at']
df_mongo = df_melted[mongo_cols].copy()
df_mongo_db = df_mongo.replace({np.nan: None})

print("\nAnteprima dati pronti per MongoDB (in EUR):")
print(df_mongo_db.tail())


# --- 3. VISUALIZZAZIONE DATI (LAVAZZA DASHBOARD IN EUR) ---

print("\nGenerazione dashboard analitica in corso...")

df_plot = df_coffee.dropna(subset=['Arabica', 'Robusta', 'Date']).copy()
df_plot = df_plot.sort_values('Date').reset_index(drop=True)

df_plot['Spread'] = df_plot['Arabica'] - df_plot['Robusta']

dates = df_plot['Date']
arabica = df_plot['Arabica']
robusta = df_plot['Robusta']
spread = df_plot['Spread']

# Medie mobili a 12 mesi
ma12_arabica = arabica.rolling(12, center=True).mean()
ma12_robusta = robusta.rolling(12, center=True).mean()

# Proiezioni a 5 anni
date_nums = dates.map(datetime.toordinal)
slope_a, int_a, r_a, _, _ = stats.linregress(date_nums, arabica)
slope_r, int_r, r_r, _, _ = stats.linregress(date_nums, robusta)

future_dates = [dates.iloc[-1] + relativedelta(months=i) for i in range(1, 61)]
future_nums = np.array([d.toordinal() for d in future_dates])
trend_arabica_fut = slope_a * future_nums + int_a
trend_robusta_fut = slope_r * future_nums + int_r

# Stile e Colori
LAVAZZA_BLUE = "#00205B"
GOLD = "#C49A45"      
BROWN = "#5C3A21"     
RED = "#A8201A"       
GRAY = "#808080"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": "#EFEFEF",
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})

fig = plt.figure(figsize=(18, 16))
gs = GridSpec(4, 2, figure=fig, hspace=0.5, wspace=0.25, top=0.92, bottom=0.06)

ax1 = fig.add_subplot(gs[0:2, :]) 
ax2 = fig.add_subplot(gs[2, :])   
ax3 = fig.add_subplot(gs[3, 0])   
ax4 = fig.add_subplot(gs[3, 1])   

# -- TITOLO --
fig.text(0.5, 0.96, "Intelligence Approvvigionamento Caffè · Mercato Globale (Convertito in EUR)", 
         ha="center", fontsize=16, fontweight="bold", color=LAVAZZA_BLUE)
fig.text(0.5, 0.94, f"Dati Storici e Proiezioni (Fonte: World Bank) | Tasso applicato: 1 USD = {usd_to_eur:.4f} EUR", 
         ha="center", fontsize=10, color=GRAY)

# --- PLOT 1 ---
ax1.plot(dates, arabica, color=GOLD, alpha=0.3, linewidth=1)
ax1.plot(dates, robusta, color=BROWN, alpha=0.3, linewidth=1)
ax1.plot(dates, ma12_arabica, color=GOLD, linewidth=2.5, label="Arabica (Media Mobile 12m)")
ax1.plot(dates, ma12_robusta, color=BROWN, linewidth=2.5, label="Robusta (Media Mobile 12m)")
ax1.plot(future_dates, trend_arabica_fut, "--", color=GOLD, linewidth=2, label="Proiezione Trend Arabica")
ax1.plot(future_dates, trend_robusta_fut, "--", color=BROWN, linewidth=2, label="Proiezione Trend Robusta")

ax1.annotate(f"€{arabica.iloc[-1]:.2f}/kg", xy=(dates.iloc[-1], arabica.iloc[-1]), 
             xytext=(10, 0), textcoords="offset points", fontweight='bold', color=GOLD)
ax1.annotate(f"€{robusta.iloc[-1]:.2f}/kg", xy=(dates.iloc[-1], robusta.iloc[-1]), 
             xytext=(10, 0), textcoords="offset points", fontweight='bold', color=BROWN)

ax1.set_title("Andamento Storico e Proiezione Prezzi (EUR/kg)", fontweight="bold")
ax1.set_ylabel("Prezzo EUR/kg")
ax1.legend(loc="upper left")

# --- PLOT 2 ---
ax2.fill_between(dates, spread, 0, where=(spread > spread.mean()), color=RED, alpha=0.3, label="Spread sopra media (Rischio Margini)")
ax2.fill_between(dates, spread, 0, where=(spread <= spread.mean()), color=LAVAZZA_BLUE, alpha=0.2, label="Spread favorevole")
ax2.plot(dates, spread, color=LAVAZZA_BLUE, linewidth=1.2)
ax2.axhline(spread.mean(), color="black", linestyle="--", linewidth=1, label=f"Media Storica (€{spread.mean():.2f})")

ax2.set_title("Differenziale di Prezzo Arabica/Robusta (EUR/kg)", fontweight="bold")
ax2.set_ylabel("Spread (EUR/kg)")
ax2.legend(loc="upper left")

# --- PLOT 3 ---
r_corr, _ = stats.pearsonr(robusta, arabica)
ax3.scatter(robusta, arabica, alpha=0.5, color=LAVAZZA_BLUE, edgecolors='w', s=40)
z = np.polyfit(robusta, arabica, 1)
p = np.poly1d(z)
ax3.plot(robusta, p(robusta), "--", color=RED)
ax3.set_title(f"Correlazione Mercati (Pearson r = {r_corr:.2f})", fontweight="bold")
ax3.set_xlabel("Prezzo Robusta (EUR/kg)")
ax3.set_ylabel("Prezzo Arabica (EUR/kg)")

# --- PLOT 4 ---
ax4.hist(arabica, bins=30, alpha=0.6, color=GOLD, label="Arabica", density=True)
ax4.hist(robusta, bins=30, alpha=0.6, color=BROWN, label="Robusta", density=True)
kde_a = stats.gaussian_kde(arabica)
kde_r = stats.gaussian_kde(robusta)
x_a = np.linspace(arabica.min(), arabica.max(), 100)
x_r = np.linspace(robusta.min(), robusta.max(), 100)
ax4.plot(x_a, kde_a(x_a), color=GOLD, linewidth=2)
ax4.plot(x_r, kde_r(x_r), color=BROWN, linewidth=2)
ax4.set_title("Distribuzione Storica dei Prezzi", fontweight="bold")
ax4.set_xlabel("Prezzo (EUR/kg)")
ax4.set_yticks([]) 
ax4.legend()

# --- SALVATAGGIO ---
out_path = "data_sources/world_bank/world_bank_dashboard_lavazza.png"
plt.savefig(out_path, dpi=160, bbox_inches="tight", facecolor="white")
print(f"Grafico salvato con successo: {out_path}")