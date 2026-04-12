"""
fetch_conab.py — Standalone CONAB scraper (run manually or on a schedule).
Run with: python fetch_conab.py

Output:  data_sources/conab/conab_data.csv

# .env required:  (none — all data is public)
"""

import os
import re
import io
import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ==========================================
# CONFIG
# ==========================================
BASE_URL = "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe"
OUTPUT_DIR = "data_sources/conab"
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "conab_data.csv")

# ==========================================
# 1. DISCOVER LATEST REPORT
# ==========================================
print("Ricerca dell'ultimo bollettino CONAB in corso...")
response_page = requests.get(BASE_URL, timeout=30)
response_page.raise_for_status()

soup = BeautifulSoup(response_page.text, 'html.parser')

# Find the most recent "Levantamento de Café" report link
report_pattern = re.compile(
    r'(\d+[ºo°]?\s*Levantamento de Café\s*-\s*Safra\s*\d{4})', re.IGNORECASE
)

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
    raise RuntimeError(
        "Impossibile trovare il report più recente. "
        "La struttura della pagina CONAB potrebbe essere cambiata."
    )

# ==========================================
# 2. PARSE SAFRA YEAR FROM TITLE
# ==========================================
year_match = re.search(r'Safra\s*(\d{4})', report_title, re.IGNORECASE)
season_year = year_match.group(1) if year_match else "unknown"

print(f"Trovato report: {report_title}")
print(f"Anno safra:    {season_year}")
print(f"Pagina report: {report_link}")

# ==========================================
# 3. OPEN REPORT PAGE
# ==========================================
response_report = requests.get(report_link, timeout=30)
response_report.raise_for_status()

soup_report = BeautifulSoup(response_report.text, 'html.parser')

# ==========================================
# 4. FIND EXCEL FILE LINK
# ==========================================
excel_link = None

for a in soup_report.find_all('a', href=True):
    if re.search(r'\.xls[x]?$', a['href'], re.IGNORECASE):
        excel_link = urljoin(report_link, a['href'])
        break

if not excel_link:
    # Fallback: look inside iframes or embedded objects
    for tag in soup_report.find_all(['iframe', 'object', 'embed']):
        src = tag.get('src', '') or tag.get('data', '')
        if re.search(r'\.xls[x]?', src, re.IGNORECASE):
            excel_link = urljoin(report_link, src)
            break

if not excel_link:
    raise RuntimeError(
        f"File Excel non trovato nella pagina del report: {report_link}"
    )

print(f"Link Excel trovato: {excel_link}")

# ==========================================
# 5. DOWNLOAD EXCEL FILE
# ==========================================
os.makedirs(OUTPUT_DIR, exist_ok=True)

xls_ext = ".xlsx" if excel_link.lower().endswith(".xlsx") else ".xls"
xls_path = os.path.join(OUTPUT_DIR, f"conab_data{xls_ext}")

print(f"Download in corso da: {excel_link}")
response = requests.get(excel_link, timeout=60)
response.raise_for_status()

with open(xls_path, "wb") as f:
    f.write(response.content)

print(f"File salvato: {xls_path}  ({len(response.content):,} bytes)")

# ==========================================
# 6. READ & PARSE EXCEL DATA
# ==========================================
# CONAB Levantamento typically contains a summary table per sheet.
# We try to find numeric rows with state-level data.

xl = pd.ExcelFile(xls_path)
print(f"Fogli trovati: {xl.sheet_names}")

all_frames = []

for sheet in xl.sheet_names:
    try:
        raw = pd.read_excel(xls_path, sheet_name=sheet, header=None)

        # Look for rows that contain "MG", "ES", "SP" etc (state abbreviations)
        STATE_ABBREVS = ['MG', 'ES', 'SP', 'BA', 'RO', 'PR', 'GO', 'MT', 'RJ', 'MS']

        # Find the header row by looking for "Estado" or "UF" or "Região"
        header_row = None
        for i, row in raw.iterrows():
            row_str = " ".join(str(v) for v in row.values).upper()
            if any(kw in row_str for kw in ["ESTADO", "UF", "REGIÃO", "REGIAO", "PRODUÇÃO", "AREA"]):
                header_row = i
                break

        if header_row is None:
            continue

        df_sh = pd.read_excel(xls_path, sheet_name=sheet, header=header_row)
        df_sh.columns = [str(c).strip() for c in df_sh.columns]
        df_sh = df_sh.dropna(how='all')

        # Identify columns
        # Typical columns: UF/Estado, Area (mil ha), Produção (mil sacas), Produtividade (sc/ha)
        uf_col = next((c for c in df_sh.columns
                       if any(k in c.upper() for k in ["UF", "ESTADO", "REGIÃO", "REGIAO"])), None)
        prod_col = next((c for c in df_sh.columns
                         if any(k in c.upper() for k in ["PRODUÇÃO", "PRODUCAO", "PROD"])), None)
        area_col = next((c for c in df_sh.columns
                         if any(k in c.upper() for k in ["ÁREA", "AREA"])), None)
        yield_col = next((c for c in df_sh.columns
                          if any(k in c.upper() for k in ["PRODUTIVIDADE", "SC/HA", "RENDIMENTO"])), None)

        if uf_col is None or prod_col is None:
            continue

        df_out = pd.DataFrame()
        df_out["region"] = df_sh[uf_col].astype(str).str.strip()
        df_out["production_mt"] = pd.to_numeric(df_sh[prod_col], errors='coerce')
        if area_col:
            df_out["area_ha"] = pd.to_numeric(df_sh[area_col], errors='coerce')
        if yield_col:
            df_out["yield_kgha"] = pd.to_numeric(df_sh[yield_col], errors='coerce')
        df_out["safra_year"] = season_year
        df_out["sheet"] = sheet

        # Filter to rows that look like states or regions (non-empty, non-total)
        df_out = df_out[df_out["production_mt"].notna()]
        df_out = df_out[~df_out["region"].str.upper().str.contains("TOTAL|BRASIL|MÉDIA|MEDIA", na=False)]
        df_out = df_out[df_out["region"].str.len() >= 2]

        if not df_out.empty:
            all_frames.append(df_out)
            print(f"  ✅ Sheet '{sheet}': {len(df_out)} rows parsed")

    except Exception as e:
        print(f"  ⚠ Sheet '{sheet}' skipped: {e}")

# ==========================================
# 7. SAVE OUTPUT CSV
# ==========================================
if all_frames:
    df_data = pd.concat(all_frames, ignore_index=True)
    df_data = df_data.drop_duplicates(subset=["region", "safra_year"])
    df_data.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✅ CSV salvato: {OUTPUT_CSV}  ({len(df_data)} righe)")
    print(df_data[["region", "production_mt", "safra_year"]].head(15).to_string(index=False))
else:
    print("\n⚠️  Nessun dato estratto. Verificare la struttura dell'Excel CONAB.")
    print(f"   File raw salvato in: {xls_path} — aprirlo manualmente per ispezionare.")
