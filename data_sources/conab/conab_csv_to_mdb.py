import pandas as pd
from datetime import datetime

# 1. Leggiamo il file SENZA header. Questo ci permette di esplorare la griglia grezza
df = pd.read_excel("conab_data.xls", sheet_name=0, header=None)

# 2. RICERCA INTELLIGENTE DELLE COLONNE TRAMITE LETTERE (a, b, c, d, e, f)
# Puliamo i dati trasformando tutto in stringhe minuscole senza spazi per facilitare la ricerca
df_search = df.fillna("").astype(str).apply(lambda col: col.str.strip().str.lower())

try:
    # Troviamo la riga che contiene la cella "(f)" (che in CONAB è sempre la Produzione Safra Atual)
    row_idx = df_search[df_search.eq('(f)').any(axis=1)].index[0]
    
    # Ora recuperiamo le coordinate esatte delle colonne basandoci sulle lettere
    col_region = 0  # La colonna 0 è sempre quella degli stati (REGIÃO/UF)
    col_yield = df_search.columns[df_search.iloc[row_idx] == '(d)'][0] # (d) = Produtividade 2025
    col_prod = df_search.columns[df_search.iloc[row_idx] == '(f)'][0]  # (f) = Produção 2025

except IndexError:
    print("Errore: impossibile identificare le colonne usando la codifica (d) e (f).")
    exit()

# 3. ESTRAZIONE DATI E RIMOZIONE INTESTAZIONI
# Tagliamo via tutte le righe di intestazione: i dati iniziano subito sotto la riga delle lettere
df_data = df.iloc[row_idx + 1:].copy()

# Selezioniamo solo le 3 colonne trovate e le rinominiamo
df_data = df_data[[col_region, col_prod, col_yield]]
df_data.columns = ['region_raw', 'production_raw', 'yield_raw']

# 4. PULIZIA DEGLI STATI (Uso della Regex)
df_data = df_data.dropna(subset=['region_raw'])
df_data['region_raw'] = df_data['region_raw'].astype(str).str.strip()


# Usa un'espressione regolare per tenere *solo* le sigle di 2 lettere maiuscole.
# Questo elimina in un solo colpo: "NORTE", "BRASIL", "0", "Fonte: Conab.", "Outros", ecc.
df_data = df_data[df_data['region_raw'].str.match(r'^[A-Z]{2}$')]

# 5. MAPPATURA VERSO LO SCHEMA MONGODB
uf_map = {
    'MG': 'Minas Gerais', 'ES': 'Espirito Santo', 'SP': 'São Paulo',
    'PR': 'Paraná', 'BA': 'Bahia', 'RO': 'Rondônia', 'GO': 'Goiás',
    'MT': 'Mato Grosso', 'RJ': 'Rio de Janeiro', 'PE': 'Pernambuco',
    'AC': 'Acre', 'CE': 'Ceará', 'PA': 'Pará', 'AM': 'Amazonas'
}

df_data['region'] = df_data['region_raw'].map(uf_map).fillna(df_data['region_raw'])
df_data['country'] = 'BR'
df_data['season'] = '2025'

# Conversioni ( * 60 per portare 'mil sacas' a 'tonnellate', e 'sacas/ha' a 'kg/ha')
# errors='coerce' trasformerà eventuali stringhe sporche in NaN per permettere il calcolo
df_data['production_mt'] = pd.to_numeric(df_data['production_raw'], errors='coerce') * 60
df_data['yield_kgha'] = pd.to_numeric(df_data['yield_raw'], errors='coerce') * 60

df_data['export_mt'] = None
df_data['source'] = 'conab_pdf'
df_data['collected_at'] = datetime.now()

# 6. ORDINAMENTO COLONNE FINALE
mongo_schema_cols = [
    'region', 'country', 'season', 'production_mt', 
    'yield_kgha', 'export_mt', 'source', 'collected_at'
]
df_mongo = df_data[mongo_schema_cols]

print(df_mongo)