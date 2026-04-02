# Flussi Ingestion — Lavazza IFAB

## 1. GDELT Project
**Macroarea:** `geo` | **Cadenza:** ogni ora

Esegue 5 query sequenziali all'API GDELT v2 con 4s di attesa tra una e l'altra (caffè, proteste, porti, politica, disastri naturali in Brasile). Raccoglie articoli di news, li deduplica per URL, li filtra con GPT via LLM chain (rilevanza caffè/Brasile), scrape del corpo articolo, estrazione segnali strutturati (topic, sentiment, entities, signals), embedding OpenAI `text-embedding-3-small`.

**Salva in:** `MongoDB raw_geo` · `Qdrant geo_texts` · `MongoDB ingestion_log`

---

## 2. WTO RSS
**Macroarea:** `geo` | **Cadenza:** ogni 6 ore

Legge il feed RSS ufficiale WTO via nodo nativo `rssFeedRead`. Loop sugli item, filtra con LLM (rilevanza commercio/Brasile), estrae segnali strutturati, embedding OpenAI.

**Salva in:** `MongoDB raw_geo` · `Qdrant geo_texts` · `MongoDB ingestion_log`

---

## 3. NOAA ENSO
**Macroarea:** `environment` | **Cadenza:** mensile

Scarica il file testo `oni.data` da PSL NOAA. Parsa tutte le righe storiche (anno + 12 mesi ONI), estrae la lettura più recente, calcola la fase ENSO (El Niño / La Niña / Neutro) con soglie ±0.5 e ±1.5, genera impatto sul Brasile (Nord-Nordest vs Sud), alert level (LOW / MODERATE / CRITICAL).

**Salva in:** `MongoDB raw_environment` · `MongoDB ingestion_log`

---

## 4. NASA FIRMS
**Macroarea:** `environment` | **Cadenza:** ogni ora

Chiama l'API FIRMS con la chiave `NASA_FIRMS_KEY` per il bounding box del Brasile (`-75,-35,-33,6`), lookback 5 giorni, sensore VIIRS SNPP NRT. Parsa il CSV, calcola statistiche FRP (min/avg/max/p95), conta rilevamenti per giorno, identifica i top 20 hotspot per intensità.

**Salva in:** `MongoDB raw_environment` · `MongoDB ingestion_log`

---

## 5. BCB PTAX
**Macroarea:** `prices` | **Cadenza:** giornaliero

Costruisce URL OData dinamico con lookback 10 giorni su `olinda.bcb.gov.br`. Parsa le quotazioni USD/BRL (compra/vendita), calcola variazione vs fixing precedente, etichetta il movimento (brl_weaker / brl_stronger), statistiche su finestra 10gg.

**Salva in:** `MongoDB raw_prices` · `MongoDB ingestion_log`

---

## 6. ECB Data Portal
**Macroarea:** `prices` | **Cadenza:** giornaliero

Scarica la serie SDMX-CSV `EXR.D.BRL.EUR.SP00.A` dall'API ECB, lookback 10 giorni. Parsa il CSV, estrae il tasso EUR/BRL, calcola variazione vs osservazione precedente, statistiche su finestra 10gg.

**Salva in:** `MongoDB raw_prices` · `MongoDB ingestion_log`

---

## 7. World Bank Pink Sheet
**Macroarea:** `prices` | **Cadenza:** mensile

Scarica il file XLSX `CMO-Historical-Data-Monthly.xlsx` da World Bank. Estrae le colonne `Coffee, Arabica` e `Coffee, Robusta`, parsa i valori mensili, calcola spread Arabica-Robusta, variazione MoM, statistiche su finestra 12 mesi.

**Salva in:** `MongoDB raw_prices` · `MongoDB ingestion_log`

> **Attenzione:** l'URL contiene un hash hardcoded che cambia ad ogni pubblicazione mensile — va aggiornato manualmente.

---

## 8. USDA FAS PSD
**Macroarea:** `colture` | **Cadenza:** settimanale

Costruisce una lista di anni (12 anni), itera con HTTP Request per anno sull'API `api.fas.usda.gov` (commodity `0711100` = caffè, country `BR`). Parsa gli attributi PSD (produzione, consumo, export, stock), calcola metriche derivate e variazioni YoY. GPT genera segnali narrativi.

**Salva in:** `MongoDB raw_crops` · `MongoDB ingestion_log`

---

## 9. IBGE SIDRA
**Macroarea:** `colture` | **Cadenza:** settimanale

Chiama l'API SIDRA IBGE per produzione agricola di caffè per stato. Parsa i periodi e i valori, focalizza su stati chiave (MG, ES, BA, RO), calcola confronto con periodo precedente e metriche derivate, classifica risk level.

**Salva in:** `MongoDB raw_crops` · `MongoDB ingestion_log`

---

## 10. CONAB PDF
**Macroarea:** `colture` | **Cadenza:** settimanale

Pipeline in 6 step: (1) scarica la pagina indice CONAB, (2) estrae link PDF + XLS dell'ultimo bollettino, (3) scarica e parsa la tabella XLS (produzione e resa per stato), (4) scarica il PDF, (5) estrae testo, (6) GPT struttura segnali narrativi + embed_text. L'output unisce dati quantitativi XLS + analisi qualitativa PDF.

**Salva in:** `MongoDB raw_crops` · `Qdrant crops_texts` · `MongoDB ingestion_log`

---

## 11. Comex Stat
**Macroarea:** `colture` | **Cadenza:** mensile

Controlla la data di ultimo aggiornamento Comex, costruisce query parametrizzate per esportazioni caffè brasiliane (per NCM code, per stato, per destinazione). Parsa i dati MoM e YoY, identifica top destinazioni, calcola metriche derivate. GPT genera segnali narrativi.

**Salva in:** `MongoDB raw_crops` · `MongoDB ingestion_log`

---

## Riepilogo

| Flusso | Collection | Qdrant | Cadenza | LLM |
|--------|-----------|--------|---------|-----|
| GDELT | raw_geo | geo_texts | ora | GPT filter + signals |
| WTO RSS | raw_geo | geo_texts | 6h | GPT filter + signals |
| NOAA ENSO | raw_environment | — | mensile | no |
| NASA FIRMS | raw_environment | — | ora | no |
| BCB PTAX | raw_prices | — | giornaliero | no |
| ECB | raw_prices | — | giornaliero | no |
| World Bank | raw_prices | — | mensile | no |
| USDA | raw_crops | — | settimanale | GPT signals |
| IBGE | raw_crops | — | settimanale | GPT signals |
| CONAB | raw_crops | crops_texts | settimanale | GPT signals + embed |
| Comex | raw_crops | — | mensile | GPT signals |
