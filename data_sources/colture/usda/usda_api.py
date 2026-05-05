import os
import requests
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec
from scipy import stats
from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# ==========================================
# 1. CONFIGURATION & SETUP
# ==========================================
load_dotenv()
USDA_API_KEY   = os.getenv('USDA_API_KEY', 'kPnlweZJyFyjaYjhw2jUgsQZTUBVYtkrxRZ8i2q5')
headers        = {'accept': 'application/json', 'X-Api-Key': USDA_API_KEY}
COMMODITY_CODE = '0711100' # Coffee, Green
COUNTRY_CODE   = 'BR'      # Brazil
YEARS          = range(1990, 2025)
BASE_URL       = 'https://api.fas.usda.gov/api/psd'

# Conversion: 1 USDA unit = 1,000 bags * 60 kg = 60 Metric Tons
BAG_TO_MT = 60

# ==========================================
# 2. DATA EXTRACTION (USDA API)
# ==========================================
print("Fetching USDA attributes map...")
attr_map = {
    item['attributeId']: item['attributeName'].strip()
    for item in requests.get(f"{BASE_URL}/commodityAttributes", headers=headers).json()
}

print("Fetching historical coffee data for Brazil...")
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
        print(f"  ⚠ Year {year}: {e}")

print(f"Rows downloaded: {len(rows)}")
df_all  = pd.DataFrame(rows)
df_all  = df_all.sort_values(['marketYear', 'attributeId', 'month'])
df_last = df_all.groupby(['marketYear', 'Attribute_Name'])['value'].last().unstack().reset_index()

# ==========================================
# 3. DATA PROCESSING & RISK ANALYTICS
# ==========================================
def s(col):
    return (df_last[col] if col in df_last.columns
            else pd.Series(np.nan, index=df_last.index))

df = pd.DataFrame()
df['year'] = df_last['marketYear'].astype(int)

# --- A. Production Metrics (Long-term availability) ---
df['production'] = s('Production')         * BAG_TO_MT / 1e6
df['arabica']    = s('Arabica Production') * BAG_TO_MT / 1e6
df['robusta']    = s('Robusta Production') * BAG_TO_MT / 1e6
df['other_prod'] = s('Other Production')   * BAG_TO_MT / 1e6

# --- B. Export Metrics (International availability) ---
df['exp_bean']    = s('Bean Exports')           * BAG_TO_MT / 1e6
df['exp_rg']      = s('Roast & Ground Exports') * BAG_TO_MT / 1e6
df['exp_soluble'] = s('Soluble Exports')        * BAG_TO_MT / 1e6
df['exp_total']   = s('Exports')                * BAG_TO_MT / 1e6

# --- C. Inventory Metrics (Buffer against shocks) ---
df['stock_begin'] = s('Beginning Stocks') * BAG_TO_MT / 1e6
df['stock_end']   = s('Ending Stocks')    * BAG_TO_MT / 1e6

# Filter out empty years
df = df.sort_values('year').dropna(subset=['production']).reset_index(drop=True)
years = df['year'].astype(int)

# --- D. Supply Risk Indicators ---
# 1. Production Trend Line (identifies baseline expected supply)
slope_p, intercept_p, r_p, _, _ = stats.linregress(years, df['production'])
trend_p = slope_p * years + intercept_p

# 2. Year-over-Year Volatility (identifies climate/agronomic shocks)
df['prod_yoy_pct'] = df['production'].pct_change() * 100
df['prod_diff']    = df['production'].diff()

# 3. Identify Severe Shocks (Drops > 10%)
df['severe_shock'] = df['prod_yoy_pct'] <= -10.0
idx_worst_drop = df['prod_diff'].idxmin()
worst_drop_year = df.loc[idx_worst_drop, 'year']
worst_drop_val = df.loc[idx_worst_drop, 'prod_diff']

# 4. Export Coverage Ratio (Stock-to-Use purely based on exports)
# Measures how many years of export demand current stocks can satisfy
df['export_coverage_ratio'] = (df['stock_end'] / df['exp_total']).replace([np.inf, -np.inf], np.nan)

# ==========================================
# 4. STYLING & MATPLOTLIB CONFIG
# ==========================================
BLUE   = "#1A5EA8"
TEAL   = "#0D9E74"
AMBER  = "#C27A0E"
RUST   = "#C94040"
GRAY   = "#6B6B6B"
DARK   = "#1A1A1A"

plt.rcParams.update({
    "font.family":       "sans-serif",
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.color":        "#E8E8E8",
    "grid.linewidth":    0.6,
    "axes.labelsize":    10,
    "xtick.labelsize":   9,
    "ytick.labelsize":   9,
    "figure.facecolor":  "white",
    "axes.facecolor":    "white",
})

# ==========================================
# 5. DASHBOARD LAYOUT (2x2 Grid)
# ==========================================
fig = plt.figure(figsize=(16, 12))
gs  = GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.25,
               left=0.05, right=0.95, top=0.90, bottom=0.08)

ax1 = fig.add_subplot(gs[0, 0])
ax2 = fig.add_subplot(gs[0, 1])
ax3 = fig.add_subplot(gs[1, 0])
ax4 = fig.add_subplot(gs[1, 1])

fig.text(0.5, 0.96, "Brazil Coffee Supply Risk Indicators", 
         ha="center", fontsize=18, fontweight="bold", color=DARK)
fig.text(0.5, 0.93, "Strategic Dashboard for Green Coffee Procurement  |  Source: USDA FAS PSD  |  Unit: Million Metric Tons (Mt)", 
         ha="center", fontsize=10, color=GRAY)

# ── PANEL 1: Long-term Production Trend & Split ──────────────────────────────
# Business value: Shows overall supply trajectory and dependency on Arabica vs Robusta.
mask_ab = df['arabica'].notna() & df['robusta'].notna()

ax1.stackplot(years[mask_ab], df['arabica'][mask_ab], df['robusta'][mask_ab], df['other_prod'][mask_ab],
              labels=["Arabica", "Robusta", "Other"], colors=[BLUE, TEAL, "#D0D0D0"], alpha=0.8)
ax1.plot(years, trend_p, "--", color=RUST, linewidth=2, label=f"Total Trend (R²={r_p**2:.2f})")

# Highlight largest absolute drop
ax1.annotate(f"Worst Drop:\n{worst_drop_val:.2f} Mt",
             xy=(worst_drop_year, df.loc[idx_worst_drop, 'production']),
             xytext=(worst_drop_year - 5, df.loc[idx_worst_drop, 'production'] + 0.5),
             arrowprops=dict(facecolor=RUST, arrowstyle="->", lw=1.5),
             fontsize=9, color=RUST, fontweight='bold')

ax1.set_title("Production Structure & Long-Term Trends", fontweight="bold")
ax1.set_ylabel("Production (Mt)")
ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.1f}"))
ax1.set_xlim(years.iloc[0], years.iloc[-1])
ax1.legend(loc="upper left", framealpha=0.9, fontsize=9)

# ── PANEL 2: Supply Volatility (YoY % Change) ────────────────────────────────
# Business value: Explicitly isolates severe harvests (droughts/frosts) causing price spikes.
colors_yoy = [RUST if val < 0 else TEAL for val in df['prod_yoy_pct']]
bars = ax2.bar(years, df['prod_yoy_pct'], color=colors_yoy, alpha=0.85)
ax2.axhline(0, color=DARK, linewidth=1)

# Annotate severe shocks (>10% drop)
for idx, row in df[df['severe_shock']].iterrows():
    ax2.annotate(f"{row['prod_yoy_pct']:.1f}%",
                 xy=(row['year'], row['prod_yoy_pct']),
                 xytext=(0, -12), textcoords="offset points",
                 ha='center', va='top', fontsize=8, color=RUST, fontweight='bold')

# Calculate overall volatility (Standard Deviation of YoY changes)
volatility = df['prod_yoy_pct'].std()
ax2.text(0.98, 0.95, f"Historical Volatility (Std Dev): {volatility:.1f}%", 
         transform=ax2.transAxes, ha="right", va="top", fontsize=9, 
         bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=GRAY, lw=0.5))

ax2.set_title("Supply Volatility: Year-over-Year Production Shocks", fontweight="bold")
ax2.set_ylabel("YoY Change (%)")
ax2.set_xlim(years.iloc[0] - 1, years.iloc[-1] + 1)

# ── PANEL 3: Export Dynamics (Green vs Processed) ────────────────────────────
# Business value: Shows how much of Brazil's crop is actually leaving as green beans for roasters.
mask_ex = df['exp_bean'].notna()

ax3.stackplot(years[mask_ex], df['exp_bean'][mask_ex], df['exp_rg'][mask_ex], df['exp_soluble'][mask_ex],
              labels=["Green Bean", "Roasted & Ground", "Soluble"],
              colors=[BLUE, AMBER, RUST], alpha=0.8)

ax3.plot(years, df['exp_total'].rolling(3, center=True).mean(), color=DARK, linewidth=2.0,
         label="Total Exports (3-yr moving avg)")

last_green_pct = df['exp_bean'].iloc[-1] / df['exp_total'].iloc[-1] * 100
ax3.text(0.98, 0.05, f"Green Bean Share (Latest): {last_green_pct:.1f}%", 
         transform=ax3.transAxes, ha="right", va="bottom", fontsize=9, color=BLUE,
         bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=BLUE, lw=0.5))

ax3.set_title("Export Dynamics: Green Bean vs Value-Added", fontweight="bold")
ax3.set_ylabel("Exports (Mt)")
ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.1f}"))
ax3.set_xlim(years.iloc[0], years.iloc[-1])
ax3.legend(loc="upper left", framealpha=0.9, fontsize=9)

# ── PANEL 4: Inventory Risk (Stocks & Coverage Ratio) ────────────────────────
# Business value: Low stocks + low coverage ratio = high vulnerability to the next supply shock.
width = 0.35
x = np.arange(len(years))

ax4.bar(x - width/2, df['stock_begin'], width, color=GRAY, alpha=0.4, label="Beginning Stocks")
# Color ending stocks red if they are drawn down (lower than beginning)
end_colors = [RUST if end < beg else TEAL for end, beg in zip(df['stock_end'], df['stock_begin'])]
ax4.bar(x + width/2, df['stock_end'], width, color=end_colors, alpha=0.85, label="Ending Stocks")

ax4.set_xticks(x[::5])
ax4.set_xticklabels(years.iloc[::5])
ax4.set_title("Inventory Risk: Stocks & Export Coverage", fontweight="bold")
ax4.set_ylabel("Stocks (Mt)")
ax4.legend(loc="upper left", framealpha=0.9, fontsize=9)

# Export Coverage Ratio (Stock-to-Use purely for exports)
ax4r = ax4.twinx()
ax4r.plot(x, df['export_coverage_ratio'], color=AMBER, linewidth=2, linestyle="-", marker="o", markersize=4,
          label="Export Coverage Ratio")
ax4r.set_ylabel("Ratio (Ending Stocks / Total Exports)", color=AMBER, fontsize=10)
ax4r.tick_params(axis='y', labelcolor=AMBER)
ax4r.spines['top'].set_visible(False)
ax4r.spines['right'].set_visible(True)
ax4r.spines['right'].set_color(AMBER)
ax4r.legend(loc="upper right", framealpha=0.9, fontsize=9)

# ==========================================
# 6. SAVE & DISPLAY
# ==========================================
out_path = BASE_DIR / "usda_supply_risk_dashboard.png"
BASE_DIR.mkdir(parents=True, exist_ok=True)
plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
print(f"\nDashboard saved successfully: {out_path}")
#plt.show()
