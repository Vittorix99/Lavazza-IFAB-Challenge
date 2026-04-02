import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec
from datetime import datetime
from scipy import stats
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin

# ==========================================
# 0. SCRAPING PER TROVARE L'ULTIMO REPORT (CONAB)
# ==========================================
BASE_URL = "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe"

print("Ricerca dell'ultimo bollettino CONAB in corso...")
response_page = requests.get(BASE_URL)
response_page.raise_for_status()

soup = BeautifulSoup(response_page.text, 'html.parser')

# ------------------------------------------
# 1. Trova il report più recente
# ------------------------------------------
report_pattern = re.compile(r'(\d+[ºo°]?\s*Levantamento de Café\s*-\s*Safra\s*\d{4})', re.IGNORECASE)

report_link = None
report_title = None

for a in soup.find_all('a', href=True):
    text = a.get_text(strip=True)
    match = report_pattern.search(text)
    if match:
        report_title = match.group(1)
        report_link = urljoin(BASE_URL, a['href'])
        break

if not report_link:
    raise Exception("Impossibile trovare il report più recente")

# ------------------------------------------
# 2. Estrai anno safra dal titolo
# ------------------------------------------
year_match = re.search(r'Safra\s*(\d{4})', report_title, re.IGNORECASE)
season_year = year_match.group(1) if year_match else "unknown"

print(f"Trovato report: {report_title}")
print(f"Anno safra: {season_year}")
print(f"Pagina report: {report_link}")

# ------------------------------------------
# 3. Apri la pagina del report
# ------------------------------------------
response_report = requests.get(report_link)
response_report.raise_for_status()

soup_report = BeautifulSoup(response_report.text, 'html.parser')

# ------------------------------------------
# 4. Trova il file Excel
# ------------------------------------------
excel_link = None

for a in soup_report.find_all('a', href=True):
    if re.search(r'\.xls[x]?$', a['href'], re.IGNORECASE):
        excel_link = urljoin(report_link, a['href'])
        break

if not excel_link:
    raise Exception("File Excel non trovato nella pagina del report")

print(f"Link Excel trovato: {excel_link}")

# ==========================================
# 1. DOWNLOAD E LETTURA DATI
# ==========================================

response = requests.get(excel_link)
response.raise_for_status()

file_path = "data_sources/conab/conab_data.xls"
with open(file_path, "wb") as f:
    f.write(response.content)

# Leggiamo il file SENZA header. Questo ci permette di esplorare la griglia grezza
try:
    df = pd.read_excel(file_path, sheet_name=1, header=None)
except FileNotFoundError:
    print(f"Errore: Il file non è stato salvato correttamente in {file_path}")
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
df_data['season'] = season_year # <-- Aggiornato dinamicamente

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
# 2. PREPARAZIONE DATI PER IL PLOT (LAVAZZA INTELLIGENCE)
# ==========================================

# Rimuoviamo righe senza dati validi per il plot e ordiniamo per produzione
df_plot = df_mongo.dropna(subset=['production_mt', 'yield_kgha']).copy()
df_plot = df_plot.sort_values(by='production_mt', ascending=False).reset_index(drop=True)

if len(df_plot) > 10:
    df_plot = df_plot.head(10) # Focus sulla Top 10 per decisioni strategiche

regions = df_plot['region']
prod_m = df_plot['production_mt'] / 1000 # in migliaia di tonnellate
yld = df_plot['yield_kgha']
total_prod_m = prod_m.sum()

# Identifichiamo gli stati chiave per Lavazza
# Minas Gerais (Arabica) ed Espirito Santo (Robusta)
key_arabica_state = 'Minas Gerais'
key_robusta_state = 'Espirito Santo'

# ==========================================
# 3. VISUALIZZAZIONE (LAVAZZA PROCUREMENT DASHBOARD)
# ==========================================

# Palette Lavazza Corporate
LAVAZZA_BLUE  = "#002D5A" # Blu scuro istituzionale
LAVAZZA_GOLD  = "#C49A45" # Oro/Bronzo premium
COFFEE_BROWN  = "#4A3020" # Marrone caffè
GRAY_LIGHT    = "#8C8C8C"
ALERT_RED     = "#D32F2F"

plt.rcParams.update({
    "font.family":     "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid":       True,
    "grid.color":      "#EFEFEF",
    "grid.linewidth":  0.8,
    "axes.axisbelow":  True,
    "axes.labelsize":  10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
})

fig = plt.figure(figsize=(18, 14))
gs = GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.30,
              left=0.07, right=0.97, top=0.90, bottom=0.06)

ax1 = fig.add_subplot(gs[0, :])    # Produzione (wide)
ax2 = fig.add_subplot(gs[1, :])    # Resa (wide)
ax3 = fig.add_subplot(gs[2, 0])    # Scatter efficienza
ax4 = fig.add_subplot(gs[2, 1])    # Rischio concentrazione

# ── TITOLO GENERALE ──
fig.text(0.5, 0.96, f"Lavazza Procurement Intelligence: Origine Brasile ({report_title})",
         ha="center", fontsize=18, fontweight="bold", color=LAVAZZA_BLUE)
fig.text(0.5, 0.935, "Focus Strategico su Volumi, Produttività e Rischio di Concentrazione della Supply Chain",
         ha="center", fontsize=11, color=COFFEE_BROWN)

# ══════════════════════════════════════════════════════════════════════════════
# 1. VOLUMI DI SOURCING POTENZIALE (Bar Chart)
# ══════════════════════════════════════════════════════════════════════════════
# Assegniamo colori strategici: Gold per MG (Arabica), Marrone per ES (Robusta), Grigio per gli altri
colors_prod = [LAVAZZA_GOLD if r == key_arabica_state else 
               COFFEE_BROWN if r == key_robusta_state else 
               LAVAZZA_BLUE for r in regions]

bars_prod = ax1.bar(regions, prod_m, color=colors_prod, alpha=0.9, edgecolor="white")

for bar, region in zip(bars_prod, regions):
    yval = bar.get_height()
    font_w = 'bold' if region in [key_arabica_state, key_robusta_state] else 'normal'
    ax1.text(bar.get_x() + bar.get_width()/2, yval + (yval*0.02), 
             f"{yval:,.0f}", ha='center', va='bottom', fontsize=10, fontweight=font_w, color=bar.get_facecolor())

# Legenda custom per spiegare i colori
import matplotlib.patches as mpatches
mg_patch = mpatches.Patch(color=LAVAZZA_GOLD, label='Core Arabica (Minas Gerais)')
es_patch = mpatches.Patch(color=COFFEE_BROWN, label='Core Robusta (Espirito Santo)')
other_patch = mpatches.Patch(color=LAVAZZA_BLUE, label='Altri Stati')
ax1.legend(handles=[mg_patch, es_patch, other_patch], loc='upper right', framealpha=0.9)

ax1.set_title("Volumi Disponibili per lo Scouting (Migliaia di tonnellate)", fontweight="bold", color=LAVAZZA_BLUE, pad=10)
ax1.set_ylabel("Produzione (k tonnellate)")

# ══════════════════════════════════════════════════════════════════════════════
# 2. EFFICIENZA AGRICOLA E VULNERABILITÀ CLIMATICA (Lollipop)
# ══════════════════════════════════════════════════════════════════════════════
ax2.vlines(x=regions, ymin=0, ymax=yld, color=GRAY_LIGHT, alpha=0.7, linewidth=2)
ax2.scatter(regions, yld, color=colors_prod, s=120, zorder=3)

mean_yield = yld.mean()
ax2.axhline(mean_yield, color=ALERT_RED, linestyle=":", linewidth=2, 
            label=f"Benchmark Nazionale: {mean_yield:.0f} kg/ha")

for i, txt in enumerate(yld):
    ax2.text(i, txt + (yld.max()*0.06), f"{txt:,.0f}", ha='center', va='bottom', fontsize=9, fontweight='bold', color=LAVAZZA_BLUE)

ax2.set_title("Resa per Ettaro: Indicatore di Efficienza e Impatto Climatico (kg/ha)", fontweight="bold", color=LAVAZZA_BLUE, pad=10)
ax2.set_ylim(0, yld.max() * 1.25)
ax2.legend(loc="upper right")

# ══════════════════════════════════════════════════════════════════════════════
# 3. MATRICE SOURCING: Volumi vs Resa
# ══════════════════════════════════════════════════════════════════════════════
ax3.scatter(yld, prod_m, color=LAVAZZA_BLUE, s=100, alpha=0.7, edgecolor="white", zorder=3)

for i, row in df_plot.iterrows():
    sigla = row['region'][:3].upper()
    weight = 'bold' if row['region'] in [key_arabica_state, key_robusta_state] else 'normal'
    col = LAVAZZA_GOLD if row['region'] == key_arabica_state else COFFEE_BROWN if row['region'] == key_robusta_state else GRAY_LIGHT
    
    ax3.annotate(row['region'], (row['yield_kgha'], row['production_mt'] / 1000), 
                 xytext=(8, 0), textcoords='offset points', fontsize=9, fontweight=weight, color=col, va='center')

# Linee mediane per creare i quadranti
ax3.axvline(yld.median(), color=GRAY_LIGHT, linestyle='--', alpha=0.5)
ax3.axhline(prod_m.median(), color=GRAY_LIGHT, linestyle='--', alpha=0.5)

ax3.set_title("Matrice Origini: Stabilità (Resa) vs Capacità (Volumi)", fontweight="bold", color=LAVAZZA_BLUE, pad=10)
ax3.set_xlabel("Stabilità - Resa (kg/ha)")
ax3.set_ylabel("Capacità - Produzione (k tonnellate)")

# ══════════════════════════════════════════════════════════════════════════════
# 4. SUPPLY CHAIN RISK: Concentrazione
# ══════════════════════════════════════════════════════════════════════════════
df_plot['pct_share'] = (df_plot['production_mt'] / df_plot['production_mt'].sum()) * 100

top_3_pct = df_plot.head(3)['pct_share'].sum()

# Prendiamo i top 4 e il resto in altri
top_n = 4
top_states = df_plot.head(top_n).copy()
others_pct = df_plot.iloc[top_n:]['pct_share'].sum()
others_df = pd.DataFrame({'region': ['Resto del Brasile'], 'pct_share': [others_pct]})
pie_data = pd.concat([top_states[['region', 'pct_share']], others_df])
pie_data = pie_data.sort_values(by='pct_share', ascending=True)

y_pos = np.arange(len(pie_data))
bars_pct = ax4.barh(y_pos, pie_data['pct_share'], color=GRAY_LIGHT, alpha=0.6)

# Colora l'ultimo (il più grande, solitamente Minas Gerais)
bars_pct[-1].set_color(LAVAZZA_GOLD)
bars_pct[-1].set_alpha(0.9)

for i, v in enumerate(pie_data['pct_share']):
    ax4.text(v + 1, i, f"{v:.1f}%", va='center', fontsize=10, fontweight='bold', color=LAVAZZA_BLUE)

ax4.set_yticks(y_pos)
ax4.set_yticklabels(pie_data['region'], fontweight='bold')
ax4.set_title(f"Indice di Dipendenza: Top 3 stati valgono il {top_3_pct:.1f}%", fontweight="bold", color=ALERT_RED if top_3_pct > 75 else LAVAZZA_BLUE, pad=10)
ax4.set_xlabel("Quota % dell'offerta totale")
ax4.set_xlim(0, pie_data['pct_share'].max() * 1.3)

# ── Salvataggio ──
out_path = "data_sources/conab/conab_dashboard_lavazza_intelligence.png"
plt.savefig(out_path, dpi=160, bbox_inches="tight", facecolor="white")
print(f"Grafico Intelligence salvato con successo: {out_path}")
#plt.show()