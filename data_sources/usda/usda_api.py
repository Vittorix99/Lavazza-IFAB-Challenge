import os
import requests
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
from scipy import stats
from datetime import datetime
from dotenv import load_dotenv

# ==========================================
# 1. CONFIGURAZIONE
# ==========================================
load_dotenv()
USDA_API_KEY   = os.getenv('USDA_API_KEY', 'kPnlweZJyFyjaYjhw2jUgsQZTUBVYtkrxRZ8i2q5')
headers        = {'accept': 'application/json', 'X-Api-Key': USDA_API_KEY}
COMMODITY_CODE = '0711100'
COUNTRY_CODE   = 'BR'
YEARS          = range(1990, 2025)
BASE_URL       = 'https://api.fas.usda.gov/api/psd'

# 1 unità USDA = 1 000 sacchi × 60 kg = 60 tonnellate metriche
BAG_TO_MT = 60

# ==========================================
# 2. FETCH MULTI-ANNO
# ==========================================
print("Scaricamento dizionari USDA…")
attr_map = {
    item['attributeId']: item['attributeName'].strip()
    for item in requests.get(f"{BASE_URL}/commodityAttributes", headers=headers).json()
}

rows = []
for year in YEARS:
    try:
        res = requests.get(
            f"{BASE_URL}/commodity/{COMMODITY_CODE}/country/{COUNTRY_CODE}/year/{year}",
            headers=headers, timeout=10
        )
        res.raise_for_status()
        for rec in res.json():
            rec['marketYear']     = year
            rec['Attribute_Name'] = attr_map.get(rec['attributeId'], str(rec['attributeId']))
            rows.append(rec)
    except Exception as e:
        print(f"  ⚠ Anno {year}: {e}")

print(f"Righe scaricate: {len(rows)}")
df_all  = pd.DataFrame(rows)
df_all  = df_all.sort_values(['marketYear', 'attributeId', 'month'])
df_last = df_all.groupby(['marketYear', 'Attribute_Name'])['value'].last().unstack().reset_index()

# ==========================================
# 3. COSTRUZIONE SERIE — solo attributi confermati dall'ispezione
# ==========================================
def s(col):
    return (df_last[col] if col in df_last.columns
            else pd.Series(np.nan, index=df_last.index))

df = pd.DataFrame()
df['year']         = df_last['marketYear'].astype(int)

# Produzione
df['production']   = s('Production')          * BAG_TO_MT / 1e6
df['arabica']      = s('Arabica Production')  * BAG_TO_MT / 1e6
df['robusta']      = s('Robusta Production')  * BAG_TO_MT / 1e6
df['other_prod']   = s('Other Production')    * BAG_TO_MT / 1e6

# Export per grado di trasformazione
df['exp_bean']     = s('Bean Exports')            * BAG_TO_MT / 1e6
df['exp_rg']       = s('Roast & Ground Exports')  * BAG_TO_MT / 1e6
df['exp_soluble']  = s('Soluble Exports')          * BAG_TO_MT / 1e6
df['exp_total']    = s('Exports')                  * BAG_TO_MT / 1e6

# Consumo interno per tipo
df['cons_rg']      = s('Rst,Ground Dom. Consum')  * BAG_TO_MT / 1e6
df['cons_soluble'] = s('Soluble Dom. Cons.')       * BAG_TO_MT / 1e6
df['cons_total']   = s('Domestic Consumption')     * BAG_TO_MT / 1e6

# Scorte
df['stock_begin']  = s('Beginning Stocks') * BAG_TO_MT / 1e6
df['stock_end']    = s('Ending Stocks')    * BAG_TO_MT / 1e6

df = df.sort_values('year').dropna(subset=['production']).reset_index(drop=True)
years = df['year'].astype(int)

# Trend
slope_p, intercept_p, r_p, _, _ = stats.linregress(years, df['production'])
trend_p = slope_p * years + intercept_p

mask_e = df['exp_total'].notna()
slope_e, intercept_e, r_e, _, _ = stats.linregress(years[mask_e], df['exp_total'][mask_e])
trend_e = slope_e * years[mask_e] + intercept_e

# ==========================================
# 4. STILE
# ==========================================
BLUE   = "#1A5EA8"
BLUE2  = "#5B9BD5"
TEAL   = "#0D9E74"
AMBER  = "#C27A0E"
RUST   = "#C94040"
PURPLE = "#7B4FA6"
GRAY   = "#6B6B6B"

plt.rcParams.update({
    "font.family":       "DejaVu Sans",
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.color":        "#E0E0E0",
    "grid.linewidth":    0.6,
    "axes.labelsize":    11,
    "xtick.labelsize":   9,
    "ytick.labelsize":   9,
    "figure.facecolor":  "white",
    "axes.facecolor":    "white",
})

# ==========================================
# 5. LAYOUT — 3 × 2
# ==========================================
fig = plt.figure(figsize=(18, 17))
fig.patch.set_facecolor("white")
gs  = GridSpec(3, 2, figure=fig, hspace=0.50, wspace=0.35,
               left=0.07, right=0.97, top=0.93, bottom=0.06)

ax1 = fig.add_subplot(gs[0, :])
ax2 = fig.add_subplot(gs[1, :])
ax3 = fig.add_subplot(gs[2, 0])
ax4 = fig.add_subplot(gs[2, 1])

fig.text(0.5, 0.968,
         "Brasile · Caffè Verde — Offerta, Esportazioni e Mercato Interno",
         ha="center", fontsize=15, fontweight="bold", color="#1A1A1A")
fig.text(0.5, 0.950,
         "Fonte: USDA FAS PSD — elaborazione propria  |  unità: milioni di tonnellate metriche",
         ha="center", fontsize=9, color=GRAY)

# ── PANNELLO 1 · Arabica vs Robusta ─────────────────────────────────────────
mask_ab = df['arabica'].notna() & df['robusta'].notna()
yr_ab   = years[mask_ab]

ax1.stackplot(yr_ab,
              df['arabica'][mask_ab],
              df['robusta'][mask_ab],
              df['other_prod'][mask_ab],
              labels=["Arabica", "Robusta", "Altro"],
              colors=[BLUE, TEAL, "#B0B0B0"], alpha=0.78)
ax1.plot(years, df['production'].rolling(5, center=True).mean(),
         color=AMBER, linewidth=2.5,
         label="Produzione totale — media mobile 5 anni", zorder=5)
ax1.plot(years, trend_p, "--", color=RUST, linewidth=1.5,
         label=f"Trend lineare (R²={r_p**2:.2f})", zorder=6)

idx_max = df['production'].idxmax()
ax1.annotate(
    f"Record: {df['production'][idx_max]:.2f} Mt\n({years[idx_max]})",
    xy=(years[idx_max], df['production'][idx_max]),
    xytext=(10, -30), textcoords="offset points", fontsize=8, color=BLUE,
    arrowprops=dict(arrowstyle="-", color=BLUE, lw=0.8)
)
ax1.annotate(
    f"Ultimo: {df['production'].iloc[-1]:.2f} Mt",
    xy=(years.iloc[-1], df['production'].iloc[-1]),
    xytext=(-65, 14), textcoords="offset points", fontsize=8, color=AMBER,
    arrowprops=dict(arrowstyle="-", color=AMBER, lw=0.8)
)
last_rob_pct = df['robusta'].iloc[-1] / df['production'].iloc[-1] * 100
ax1.text(0.98, 0.06,
         f"Quota Robusta (ultimo anno): {last_rob_pct:.0f}%",
         transform=ax1.transAxes, ha="right", fontsize=8.5, color=TEAL,
         bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=TEAL, lw=0.8))

ax1.set_title("Composizione della produzione: Arabica vs Robusta", fontweight="bold", pad=8)
ax1.set_ylabel("Produzione (milioni t)")
ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.1f} Mt"))
ax1.set_xlim(years.iloc[0] - 1, years.iloc[-1] + 1)
ax1.legend(loc="upper left", fontsize=8.5, framealpha=0.7)

# ── PANNELLO 2 · Struttura export ────────────────────────────────────────────
mask_ex = df['exp_bean'].notna()
yr_ex   = years[mask_ex]

ax2.stackplot(yr_ex,
              df['exp_bean'][mask_ex],
              df['exp_rg'][mask_ex],
              df['exp_soluble'][mask_ex],
              labels=["Caffè verde (Bean)", "Torrefatto & Macinato", "Solubile"],
              colors=[BLUE, AMBER, RUST], alpha=0.78)
ax2.plot(years[mask_e], trend_e, "--", color=GRAY, linewidth=1.4,
         label=f"Trend export totale (R²={r_e**2:.2f})", zorder=5)
ax2.plot(years, df['exp_total'].rolling(5, center=True).mean(),
         color="#1A1A1A", linewidth=2.0,
         label="Export totale — media mobile 5 anni", zorder=6)

last_va = (df['exp_rg'].iloc[-1] + df['exp_soluble'].iloc[-1]) / df['exp_total'].iloc[-1] * 100
ax2.text(0.02, 0.91,
         f"Export trasformato (R&G + Solubile): {last_va:.1f}% nell'ultimo anno",
         transform=ax2.transAxes, fontsize=8.5, color=RUST,
         bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=RUST, lw=0.8))

ax2.set_title("Struttura delle esportazioni per grado di trasformazione",
              fontweight="bold", pad=8)
ax2.set_ylabel("Export (milioni t)")
ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.2f} Mt"))
ax2.set_xlim(years.iloc[0] - 1, years.iloc[-1] + 1)
ax2.legend(loc="upper left", fontsize=8.5, framealpha=0.7)

# ── PANNELLO 3 · Consumo interno ─────────────────────────────────────────────
mask_c = df['cons_rg'].notna() & df['cons_soluble'].notna()
yr_c   = years[mask_c]

ax3.stackplot(yr_c,
              df['cons_rg'][mask_c],
              df['cons_soluble'][mask_c],
              labels=["Torrefatto & Macinato", "Solubile"],
              colors=[AMBER, PURPLE], alpha=0.78)
ax3.plot(years, df['cons_total'].rolling(5, center=True).mean(),
         color="#1A1A1A", linewidth=2.0,
         label="Totale — media mobile 5 anni", zorder=5)

last_sol_pct = df['cons_soluble'].iloc[-1] / df['cons_total'].iloc[-1] * 100
ax3.text(0.98, 0.06,
         f"Quota solubile: {last_sol_pct:.0f}%",
         transform=ax3.transAxes, ha="right", fontsize=8.5, color=PURPLE,
         bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=PURPLE, lw=0.8))

ax3.set_title("Consumo interno: Torrefatto vs Solubile", fontweight="bold", pad=8)
ax3.set_ylabel("Consumo (milioni t)")
ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.2f}"))
ax3.set_xlim(years.iloc[0] - 1, years.iloc[-1] + 1)
ax3.legend(loc="upper left", fontsize=8.0, framealpha=0.7)

# ── PANNELLO 4 · Bilancio scorte + stock-to-use ──────────────────────────────
width = 0.35
x     = np.arange(len(years))

ax4.bar(x - width/2, df['stock_begin'], width,
        color=BLUE2, alpha=0.75, label="Scorte iniziali", edgecolor="white")
ax4.bar(x + width/2, df['stock_end'], width,
        color=[TEAL if v >= b else RUST
               for v, b in zip(df['stock_end'], df['stock_begin'])],
        alpha=0.80,
        label="Scorte finali  (verde = build-up, rosso = draw-down)",
        edgecolor="white")

ax4.set_xticks(x[::5])
ax4.set_xticklabels(years.iloc[::5], rotation=30, ha="right")
ax4.set_title("Bilancio scorte: Iniziali vs Finali\n(scorte finali: verde=build-up, rosso=draw-down)",
              fontweight="bold", pad=8)
ax4.set_ylabel("Scorte (milioni t)")
ax4.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.2f}"))
ax4.legend(fontsize=7.5, loc="upper right", framealpha=0.7)

# Stock-to-use ratio sull'asse destro
ax4r = ax4.twinx()
stu  = (df['stock_end'] / df['exp_total']).replace([np.inf, -np.inf], np.nan)
ax4r.plot(x, stu, color=AMBER, linewidth=1.8, linestyle="--",
          label="Stock-to-use ratio (→ destra)", zorder=6)
ax4r.set_ylabel("Stock-to-use ratio", color=AMBER, fontsize=9)
ax4r.tick_params(axis='y', labelcolor=AMBER)
ax4r.spines['top'].set_visible(False)
ax4r.legend(fontsize=7.5, loc="upper left", framealpha=0.7)

# ==========================================
# 6. SALVATAGGIO
# ==========================================
out_path = "data_sources/usda/usda_psd_dashboard_brasile_caffe.png"
os.makedirs(os.path.dirname(out_path), exist_ok=True)
plt.savefig(out_path, dpi=160, bbox_inches="tight", facecolor="white")
print(f"\nGrafico salvato: {out_path}")
plt.show()