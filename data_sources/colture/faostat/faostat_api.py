import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
from scipy import stats
from datetime import datetime
from dotenv import load_dotenv
import faostat
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

load_dotenv()

fao_user = os.getenv('FAOSTAT_USERNAME')
fao_pass = os.getenv('FAOSTAT_PASSWORD')

faostat.set_requests_args(username=fao_user, password=fao_pass)

mypars = {
    'area': '21',
    'element': [2312, 2413, 2510, 2111, 2313],
    'item': '656'
}

print("Scaricamento dati da FAOSTAT in corso...")
df_raw = faostat.get_data_df('QCL', pars=mypars)

df_pivot = df_raw.pivot_table(
    index='Year', 
    columns='Element', 
    values='Value', 
    aggfunc='first'
).reset_index()

df_mongo = pd.DataFrame()
df_mongo['season'] = df_pivot['Year'].astype(str)
df_mongo['production_mt'] = df_pivot['Production']
df_mongo['yield_kgha'] = df_pivot['Yield']

df_mongo['region'] = None  
df_mongo['country'] = 'BR'
df_mongo['export_mt'] = None
df_mongo['source'] = 'faostat'
df_mongo['collected_at'] = datetime.now()

mongo_schema_cols = [
    'region', 'country', 'season', 'production_mt', 
    'yield_kgha', 'export_mt', 'source', 'collected_at'
]
df_mongo = df_mongo[mongo_schema_cols]

# PULIZIA PER MONGODB (Sostituisco NaN con None per il DB)
df_mongo_db = df_mongo.replace({np.nan: None})
print("\nAnteprima dati pronti per MongoDB:")
print(df_mongo_db.tail())

# PLOT

# Creiamo una copia per il grafico convertendo i tipi di dato necessari
df = df_mongo.copy()
df['season_num'] = pd.to_numeric(df['season'])
df['production_mt'] = pd.to_numeric(df['production_mt'], errors='coerce')
df['yield_kgha'] = pd.to_numeric(df['yield_kgha'], errors='coerce')

# Rimuoviamo eventuali righe senza produzione o resa per non far fallire la regressione lineare
df = df.dropna(subset=['production_mt', 'yield_kgha', 'season_num'])
df = df.sort_values("season_num").reset_index(drop=True)

prod_m = df["production_mt"] / 1e6       # in milioni di tonnellate
yld    = df["yield_kgha"]
years  = df["season_num"].astype(int)

# Calcoli statistici
roll5_prod = prod_m.rolling(5, center=True).mean()
roll5_yld  = yld.rolling(5, center=True).mean()

slope_p, intercept_p, r_p, _, _ = stats.linregress(years, prod_m)
slope_y, intercept_y, r_y, _, _ = stats.linregress(years, yld)
r_corr, p_corr = stats.pearsonr(yld, prod_m)

trend_prod = slope_p * years + intercept_p
trend_yld  = slope_y * years + intercept_y


# VISUALIZZAZIONE

# Palette e stile
BLUE   = "#1A5EA8"
TEAL   = "#0D9E74"
AMBER  = "#C27A0E"
GRAY   = "#6B6B6B"
LBLUE  = "#D0E4F7"
LTEAL  = "#C5EDE0"
LAMBER = "#FAE8C4"

plt.rcParams.update({
    "font.family":     "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid":       True,
    "grid.color":      "#E0E0E0",
    "grid.linewidth":  0.6,
    "axes.labelsize":  11,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "figure.facecolor": "white",
    "axes.facecolor":  "white",
})

fig = plt.figure(figsize=(18, 14))
fig.patch.set_facecolor("white")
gs = GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.35,
              left=0.07, right=0.97, top=0.92, bottom=0.06)

ax1 = fig.add_subplot(gs[0, :])    # produzione — larghezza intera
ax2 = fig.add_subplot(gs[1, :])    # resa      — larghezza intera
ax3 = fig.add_subplot(gs[2, 0])    # scatter
ax4 = fig.add_subplot(gs[2, 1])    # variazione % decade

# ── TITOLO GENERALE ──
fig.text(0.5, 0.965, "Brasile · Produzione e resa agricola",
         ha="center", fontsize=15, fontweight="bold", color="#1A1A1A")
fig.text(0.5, 0.945, "Fonte: FAOSTAT — elaborazione propria",
         ha="center", fontsize=9, color=GRAY)


# PRODUZIONE nel tempo

ax1.fill_between(years, prod_m, alpha=0.15, color=BLUE)
ax1.plot(years, prod_m,   color=BLUE,  linewidth=1.2, alpha=0.5, label="Annuale")
ax1.plot(years, roll5_prod, color=BLUE, linewidth=2.2, label="Media mobile 5 anni")
ax1.plot(years, trend_prod, "--", color=AMBER, linewidth=1.4,
         label=f"Trend lineare  (R²={r_p**2:.2f})")

idx_max = prod_m.idxmax();  idx_min = prod_m.idxmin()
for idx, lbl, va in [(idx_max, "Max", "bottom"), (idx_min, "Min", "top")]:
    ax1.annotate(
        f"{lbl}: {prod_m[idx]:.1f} Mt\n({years[idx]})",
        xy=(years[idx], prod_m[idx]),
        xytext=(10, 18 if va == "bottom" else -28),
        textcoords="offset points",
        fontsize=8, color=BLUE,
        arrowprops=dict(arrowstyle="-", color=BLUE, lw=0.8),
    )
last_y, last_v = years.iloc[-1], prod_m.iloc[-1]
ax1.annotate(f"Ultimo: {last_v:.1f} Mt", xy=(last_y, last_v),
             xytext=(-50, 10), textcoords="offset points", fontsize=8, color=BLUE,
             arrowprops=dict(arrowstyle="-", color=BLUE, lw=0.8))

ax1.set_title("Andamento della produzione nel tempo", fontweight="bold", pad=8)
ax1.set_ylabel("Produzione (milioni di tonnellate)")
ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f} Mt"))
ax1.set_xlim(years.iloc[0] - 1, years.iloc[-1] + 1)
ax1.legend(loc="upper left", fontsize=8.5, framealpha=0.7)

 
# RESA nel tempo con zone colorate

q1, q3 = yld.quantile(0.25), yld.quantile(0.75)
ylim_lo = yld.min() - 100

ax2.axhspan(ylim_lo,  q1, color=LAMBER, alpha=0.5, label="Bassa resa (Q1)")
ax2.axhspan(q1,       q3, color=LTEAL,  alpha=0.4, label="Resa media (IQR)")
ax2.axhspan(q3,  yld.max() + 200, color=LBLUE, alpha=0.5, label="Alta resa (Q3+)")

ax2.plot(years, yld,      color=TEAL, linewidth=1.0, alpha=0.45)
ax2.plot(years, roll5_yld, color=TEAL, linewidth=2.2, label="Media mobile 5 anni")
ax2.plot(years, trend_yld, "--", color=AMBER, linewidth=1.4,
         label=f"Trend lineare  (R²={r_y**2:.2f})")

idx_max2 = yld.idxmax()
ax2.annotate(
    f"Record: {yld[idx_max2]:.0f} kg/ha\n({years[idx_max2]})",
    xy=(years[idx_max2], yld[idx_max2]),
    xytext=(10, -22), textcoords="offset points",
    fontsize=8, color=TEAL,
    arrowprops=dict(arrowstyle="-", color=TEAL, lw=0.8),
)

ax2.set_title("Andamento della resa nel tempo", fontweight="bold", pad=8)
ax2.set_ylabel("Resa (kg/ha)")
ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
ax2.set_xlim(years.iloc[0] - 1, years.iloc[-1] + 1)
handles2, labels2 = ax2.get_legend_handles_labels()
ax2.legend(handles2, labels2, loc="upper left", fontsize=8.5, framealpha=0.7)


# SCATTER: Produzione vs Resa — colorato per decade

decades    = ((years // 10) * 10).astype(int)
dec_unique = sorted(decades.unique())
cmap       = plt.get_cmap("Blues") 
# Adattiamo i colori in base al numero di decadi
dec_colors = {d: cmap((i + 2) / (len(dec_unique) + 2)) for i, d in enumerate(dec_unique)}

for dec in dec_unique:
    mask = decades == dec
    ax3.scatter(yld[mask], prod_m[mask],
                color=dec_colors[dec], s=40, alpha=0.8,
                label=f"{dec}s", zorder=3)

x_fit = np.linspace(yld.min(), yld.max(), 200)
y_fit = np.polyval(np.polyfit(yld, prod_m, 1), x_fit)
ax3.plot(x_fit, y_fit, "--", color=AMBER, linewidth=1.6, zorder=4)

ax3.text(0.05, 0.93,
         f"r = {r_corr:.2f}  p {'< 0.001' if p_corr < 0.001 else f'= {p_corr:.3f}'}",
         transform=ax3.transAxes, fontsize=9, color=AMBER,
         bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=AMBER, lw=0.8))

ax3.set_title("Correlazione resa → produzione\n(punti colorati per decade)",
              fontweight="bold", pad=8)
ax3.set_xlabel("Resa (kg/ha)")
ax3.set_ylabel("Produzione (milioni t)")
ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}"))
ax3.legend(title="Decade", fontsize=7.5, title_fontsize=8,
           loc="upper left", framealpha=0.7, ncol=2)


# 4. VARIAZIONE % PER DECADE (bar chart)

dec_prod_avg = df.assign(decade=decades).groupby("decade")["production_mt"].mean() / 1e6
pct_change   = dec_prod_avg.pct_change() * 100
bars = ax4.bar(pct_change.index[1:], pct_change.dropna(),
               color=[TEAL if v >= 0 else "#C94040" for v in pct_change.dropna()],
               width=7, edgecolor="white", linewidth=0.8)

for bar in bars:
    h = bar.get_height()
    ax4.text(bar.get_x() + bar.get_width() / 2, h + (1 if h >= 0 else -3),
             f"{h:+.0f}%", ha="center", fontsize=8.5, fontweight="bold",
             color=TEAL if h >= 0 else "#C94040")

ax4.axhline(0, color=GRAY, linewidth=0.8, linestyle="--")
ax4.set_title("Variazione % della produzione media\nda decade a decade",
              fontweight="bold", pad=8)
ax4.set_xlabel("Decade")
ax4.set_ylabel("Variazione (%)")
ax4.set_xticks(pct_change.index[1:])
ax4.set_xticklabels([f"{d}s" for d in pct_change.index[1:]], rotation=30, ha="right")

# ── Salvataggio ──
out_path = BASE_DIR / "fao_dashboard_brasile.png"
plt.savefig(out_path, dpi=160, bbox_inches="tight", facecolor="white")
print(f"Grafico salvato con successo: {out_path}")
plt.show()
