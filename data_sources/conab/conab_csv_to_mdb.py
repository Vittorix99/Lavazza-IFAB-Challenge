import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec
from datetime import datetime
from scipy import stats

# ==========================================
# 1. ESTRAZIONE E PULIZIA DATI (CONAB)
# ==========================================

# Leggiamo il file SENZA header. Questo ci permette di esplorare la griglia grezza
try:
    df = pd.read_excel("data_sources/conab/conab_data.xls", sheet_name=0, header=None)
except FileNotFoundError:
    print("Errore: Il file 'conab_data.xls' non è stato trovato. Assicurati che sia nella stessa cartella.")
    exit()

# RICERCA INTELLIGENTE DELLE COLONNE
df_search = df.fillna("").astype(str).apply(lambda col: col.str.strip().str.lower())

try:
    row_idx = df_search[df_search.eq('(f)').any(axis=1)].index[0]
    col_region = 0  
    col_yield = df_search.columns[df_search.iloc[row_idx] == '(d)'][0] 
    col_prod = df_search.columns[df_search.iloc[row_idx] == '(f)'][0]  
except IndexError:
    print("Errore: impossibile identificare le colonne usando la codifica (d) e (f).")
    exit()

# ESTRAZIONE DATI
df_data = df.iloc[row_idx + 1:].copy()
df_data = df_data[[col_region, col_prod, col_yield]]
df_data.columns = ['region_raw', 'production_raw', 'yield_raw']

# PULIZIA DEGLI STATI
df_data = df_data.dropna(subset=['region_raw'])
df_data['region_raw'] = df_data['region_raw'].astype(str).str.strip()
df_data = df_data[df_data['region_raw'].str.match(r'^[A-Z]{2}$')]

# MAPPATURA E CONVERSIONI
uf_map = {
    'MG': 'Minas Gerais', 'ES': 'Espirito Santo', 'SP': 'São Paulo',
    'PR': 'Paraná', 'BA': 'Bahia', 'RO': 'Rondônia', 'GO': 'Goiás',
    'MT': 'Mato Grosso', 'RJ': 'Rio de Janeiro', 'PE': 'Pernambuco',
    'AC': 'Acre', 'CE': 'Ceará', 'PA': 'Pará', 'AM': 'Amazonas'
}

df_data['region'] = df_data['region_raw'].map(uf_map).fillna(df_data['region_raw'])
df_data['country'] = 'BR'
df_data['season'] = '2025'

df_data['production_mt'] = pd.to_numeric(df_data['production_raw'], errors='coerce') * 60
df_data['yield_kgha'] = pd.to_numeric(df_data['yield_raw'], errors='coerce') * 60

df_data['export_mt'] = None
df_data['source'] = 'conab_pdf'
df_data['collected_at'] = datetime.now()

mongo_schema_cols = [
    'region', 'country', 'season', 'production_mt', 
    'yield_kgha', 'export_mt', 'source', 'collected_at'
]
df_mongo = df_data[mongo_schema_cols]


# ==========================================
# 2. PREPARAZIONE DATI PER IL PLOT
# ==========================================

# Rimuoviamo righe senza dati validi per il plot e ordiniamo per produzione
df_plot = df_mongo.dropna(subset=['production_mt', 'yield_kgha']).copy()
df_plot = df_plot.sort_values(by='production_mt', ascending=False).reset_index(drop=True)

# Se ci sono troppi stati (es. > 15), raggruppiamo i minori in "Altri" per pulizia visiva (opzionale, qui teniamo i top 12)
if len(df_plot) > 12:
    df_plot = df_plot.head(12)

regions = df_plot['region']
prod_m = df_plot['production_mt'] / 1000 # Convertiamo in migliaia di tonnellate per leggibilità
yld = df_plot['yield_kgha']
total_prod_m = prod_m.sum()

# ==========================================
# 3. VISUALIZZAZIONE (DASHBOARD REGIONALE)
# ==========================================

# Palette e stile (identici al precedente)
BLUE   = "#1A5EA8"
TEAL   = "#0D9E74"
AMBER  = "#C27A0E"
GRAY   = "#6B6B6B"
LBLUE  = "#D0E4F7"

plt.rcParams.update({
    "font.family":     "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid":       True,
    "grid.color":      "#E0E0E0",
    "grid.linewidth":  0.6,
    "axes.axisbelow":  True, # Griglia dietro alle barre
    "axes.labelsize":  11,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "figure.facecolor": "white",
    "axes.facecolor":  "white",
})

fig = plt.figure(figsize=(18, 14))
gs = GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.35,
              left=0.07, right=0.97, top=0.92, bottom=0.06)

ax1 = fig.add_subplot(gs[0, :])    # Produzione (wide)
ax2 = fig.add_subplot(gs[1, :])    # Resa (wide)
ax3 = fig.add_subplot(gs[2, 0])    # Scatter
ax4 = fig.add_subplot(gs[2, 1])    # Quota %

# ── TITOLO GENERALE ──
fig.text(0.5, 0.965, "Brasile · Produzione e Resa Agricola per Stato (Stima Safra 2025)",
         ha="center", fontsize=15, fontweight="bold", color="#1A1A1A")
fig.text(0.5, 0.945, "Fonte: CONAB — elaborazione propria sui Top 12 Stati",
         ha="center", fontsize=9, color=GRAY)

# ══════════════════════════════════════════════════════════════════════════════
# 1. PRODUZIONE PER STATO (Bar Chart)
# ══════════════════════════════════════════════════════════════════════════════
bars_prod = ax1.bar(regions, prod_m, color=BLUE, alpha=0.85, edgecolor="white")

# Etichette sopra le barre
for bar in bars_prod:
    yval = bar.get_height()
    ax1.text(bar.get_x() + bar.get_width()/2, yval + (yval*0.02), 
             f"{yval:,.0f}", ha='center', va='bottom', fontsize=9, color=BLUE)

ax1.set_title("Produzione totale stimata per Stato", fontweight="bold", pad=8)
ax1.set_ylabel("Produzione (migliaia di tonnellate)")
ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}k"))

# ══════════════════════════════════════════════════════════════════════════════
# 2. RESA PER STATO (Lollipop Chart)
# ══════════════════════════════════════════════════════════════════════════════
# Usiamo un lollipop chart per variare visivamente rispetto alle barre classiche
ax2.vlines(x=regions, ymin=0, ymax=yld, color=TEAL, alpha=0.7, linewidth=3)
ax2.scatter(regions, yld, color=TEAL, s=100, zorder=3)

# Linea media nazionale stimata sui top
mean_yield = yld.mean()
ax2.axhline(mean_yield, color=AMBER, linestyle="--", linewidth=1.5, 
            label=f"Resa Media (Top Stati): {mean_yield:.0f} kg/ha")

for i, txt in enumerate(yld):
    ax2.text(i, txt + (yld.max()*0.05), f"{txt:,.0f}", ha='center', va='bottom', fontsize=9, color=TEAL)

ax2.set_title("Resa agricola per Stato (Produttività)", fontweight="bold", pad=8)
ax2.set_ylabel("Resa (kg/ha)")
ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
ax2.set_ylim(0, yld.max() * 1.2) # Diamo spazio per le etichette
ax2.legend(loc="upper right", framealpha=0.9)

# ══════════════════════════════════════════════════════════════════════════════
# 3. SCATTER: Produzione vs Resa (con etichette stati)
# ══════════════════════════════════════════════════════════════════════════════
# Qui ogni punto è uno stato
ax3.scatter(yld, prod_m, color=BLUE, s=80, alpha=0.7, edgecolor="white", zorder=3)

# Aggiungiamo le sigle degli stati vicino ai punti
for i, row in df_plot.iterrows():
    # Recuperiamo la sigla (prime due lettere o mappatura inversa se necessario)
    # Per semplicità usiamo le prime 3 lettere del nome dello stato
    sigla = row['region'][:3].upper()
    ax3.annotate(sigla, (row['yield_kgha'], row['production_mt'] / 1000), 
                 xytext=(5, 5), textcoords='offset points', fontsize=8, color=GRAY)

# Calcolo correlazione
if len(df_plot) > 1:
    r_corr, p_corr = stats.pearsonr(yld, prod_m)
    ax3.text(0.05, 0.93,
             f"r = {r_corr:.2f}  (Correlazione)",
             transform=ax3.transAxes, fontsize=9, color=AMBER,
             bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=AMBER, lw=0.8))

ax3.set_title("Efficienza: Resa vs Produzione Totale", fontweight="bold", pad=8)
ax3.set_xlabel("Resa (kg/ha)")
ax3.set_ylabel("Produzione (migliaia di t)")
ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}k"))

# ══════════════════════════════════════════════════════════════════════════════
# 4. QUOTA % PRODUZIONE (Horizontal Bar Chart)
# ══════════════════════════════════════════════════════════════════════════════
# Calcoliamo la percentuale di ogni stato sul totale del dataset plot
df_plot['pct_share'] = (df_plot['production_mt'] / df_plot['production_mt'].sum()) * 100

# Prendiamo solo i top 5 per non affollare il grafico, raggruppiamo il resto in "Altri"
top_n = 5
if len(df_plot) > top_n:
    top_states = df_plot.head(top_n).copy()
    others_pct = df_plot.iloc[top_n:]['pct_share'].sum()
    others_df = pd.DataFrame({'region': ['Altri Stati'], 'pct_share': [others_pct]})
    pie_data = pd.concat([top_states[['region', 'pct_share']], others_df])
else:
    pie_data = df_plot[['region', 'pct_share']]

# Ordiniamo per il plot orizzontale dal basso verso l'alto
pie_data = pie_data.sort_values(by='pct_share', ascending=True)

y_pos = np.arange(len(pie_data))
bars_pct = ax4.barh(y_pos, pie_data['pct_share'], color=LBLUE, edgecolor="white")

# Evidenziamo il primo classificato con il colore primario
bars_pct[-1].set_color(BLUE)

for i, v in enumerate(pie_data['pct_share']):
    ax4.text(v + 0.5, i, f"{v:.1f}%", va='center', fontsize=9, fontweight='bold', color=GRAY)

ax4.set_yticks(y_pos)
ax4.set_yticklabels(pie_data['region'])
ax4.set_title(f"Concentrazione della produzione (Top {top_n})", fontweight="bold", pad=8)
ax4.set_xlabel("Quota % sul totale stimato")
ax4.set_xlim(0, pie_data['pct_share'].max() * 1.2) # Spazio per le etichette

# ── Salvataggio ──
out_path = "data_sources/conab/conab_dashboard_regionale.png"
plt.savefig(out_path, dpi=160, bbox_inches="tight", facecolor="white")
print(f"Grafico salvato con successo: {out_path}")
plt.show()