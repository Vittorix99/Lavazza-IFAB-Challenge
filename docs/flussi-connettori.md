# Flussi Dati — Connettori n8n

Documentazione di ogni connettore attivo nel sistema Lavazza: cosa raccoglie, come funziona, cosa produce, dove salva.

---

## 1. BCB PTAX — Tasso di cambio BRL/USD

**Macroarea:** `prices` → MongoDB `raw_prices`  
**Cadenza:** giornaliera  
**`is_fresh` threshold:** 36 ore  

### Cosa raccoglie
Il tasso di cambio BRL/USD giornaliero pubblicato dalla Banca Centrale del Brasile (BCB) tramite API OData. Costruisce un URL OData dinamico su `olinda.bcb.gov.br` con lookback 10 giorni. Raccoglie quotazioni compra e vendita, calcola variazione vs fixing precedente, statistiche su finestra 10gg.

### Flusso
```
BCB PTAX Download (HTTP OData API — olinda.bcb.gov.br)
  → BCB PTAX Parse (Code)
      calcola: variazione vs giorno precedente, stats lookback (min/avg/max),
               serie storica 180gg, movement_label rule-based, signals rule-based
  → BCB AI Signals (chainLlm)
      input: quotazione attuale, variazione, stats
      output: movement_label, signals, summary_en (senza risk_level)
  → BCB Parse Signals (Code)
      fonde AI output + fallback rule-based
  → BCB MongoDB raw_prices
  → BCB MongoDB ingestion_log
```

### Documento MongoDB
```json
{
  "source": "BCB_PTAX",
  "country": "BR",
  "macroarea": "prices",
  "collected_at": "...",
  "is_fresh": true,
  "quote_date": "2026-04-08",
  "cotacaoCompra": 5.12,
  "cotacaoVenda": 5.13,
  "spread": 0.01,
  "change_pct_vs_previous": -0.3,
  "sell_stats_lookback": {"min": 4.8, "avg": 5.05, "max": 5.3, "range": 0.5},
  "movement_label": "brl_stable",
  "signals": ["BRL/USD unchanged for 3 consecutive sessions"],
  "summary_en": "...",
  "_chart_fields": ["recent_series"]
}
```

### Qdrant
Non utilizzato — dati numerici puri.

---

## 2. ECB Data Portal — Tasso di cambio EUR/BRL

**Macroarea:** `prices` → MongoDB `raw_prices`  
**Cadenza:** giornaliera  
**`is_fresh` threshold:** 36 ore  

### Cosa raccoglie
Il tasso di cambio EUR/BRL giornaliero dalla BCE tramite API SDMX. Serie `EXR.D.BRL.EUR.SP00.A`, lookback 10 giorni. Calcola variazione vs osservazione precedente, statistiche su finestra 10gg.

### Flusso
```
ECB Data Portal Download (HTTP SDMX-CSV API)
  → ECB Data Portal Parse (Code)
      calcola: variazione vs giorno precedente, stats lookback, serie storica, movement_label
  → ECB AI Signals (chainLlm)
  → ECB Parse Signals (Code)
  → ECB MongoDB raw_prices
  → ECB MongoDB ingestion_log
```

### Documento MongoDB
```json
{
  "source": "ECB_DATA_PORTAL",
  "country": "BR",
  "macroarea": "prices",
  "collected_at": "...",
  "is_fresh": true,
  "quote_date": "2026-04-08",
  "fx_rate_brl_per_eur": 6.32,
  "change_pct_vs_previous": 0.15,
  "fx_stats_lookback": {"min": 5.9, "avg": 6.1, "max": 6.5},
  "movement_label": "eur_stable",
  "signals": ["EUR/BRL rate within 6-month average range"],
  "summary_en": "...",
  "_chart_fields": ["recent_series"]
}
```

### Qdrant
Non utilizzato.

---

## 3. World Bank Pink Sheet — Prezzi internazionali caffè

**Macroarea:** `prices` → MongoDB `raw_prices`  
**Cadenza:** mensile  
**`is_fresh` threshold:** 35 giorni  

### Cosa raccoglie
I prezzi mensili di arabica e robusta dal Pink Sheet della World Bank (`CMO-Historical-Data-Monthly.xlsx`). Estrae le colonne `Coffee, Arabica` e `Coffee, Robusta`, calcola spread arabica-robusta, variazione MoM, statistiche su finestra 12 mesi.

> **Attenzione:** l'URL del file XLSX contiene un hash hardcoded che cambia ad ogni pubblicazione mensile — il nodo `World Bank Extract URL` lo estrae dinamicamente dalla pagina HTML, ma va verificato ad ogni aggiornamento.

### Flusso
```
World Bank Fetch Page (HTTP — pagina web)
  → World Bank Extract URL (Code)
      estrae il link diretto al file XLSX corrente dalla pagina HTML
  → World Bank Pink Sheet Download (HTTP)
  → World Bank Pink Sheet Extract (extractFromFile — XLSX)
  → World Bank Pink Sheet Parse (Code)
      estrae: arabica price, robusta price, spread arabica-robusta,
              variazioni MoM, serie storica 6 mesi
  → World Bank AI Signals (chainLlm)
  → World Bank Parse Signals (Code)
  → World Bank MongoDB raw_prices
  → World Bank MongoDB ingestion_log
```

### Documento MongoDB
```json
{
  "source": "WB_PINK_SHEET",
  "country": "BR",
  "macroarea": "prices",
  "collected_at": "...",
  "is_fresh": true,
  "report_period": "Mar-26",
  "coffee_arabica_price": 4.21,
  "coffee_robusta_price": 2.85,
  "arabica_robusta_spread": 1.36,
  "change_pct_mom_arabica": 2.1,
  "change_pct_mom_robusta": -0.5,
  "movement_label": "prices_rising",
  "signals": ["Arabica price up 2.1% MoM", "Spread widening for 3rd consecutive month"],
  "summary_en": "...",
  "_chart_fields": ["recent_series"]
}
```

### Qdrant
Non utilizzato.

---

## 4. NASA FIRMS — Rilevamenti incendi Brasile

**Macroarea:** `environment` → MongoDB `raw_environment`  
**Cadenza:** ogni ora  
**`is_fresh` threshold:** 3 ore  

### Cosa raccoglie
Rilevamenti di incendi attivi in Brasile dal sensore VIIRS SNPP NRT di NASA FIRMS, tramite la chiave `NASA_FIRMS_KEY`. Copre il bounding box geografico del Brasile (`-75,-35,-33,6`), lookback 5 giorni. Aggrega statistiche FRP (min/avg/max/p95), conta rilevamenti per giorno, identifica top 20 hotspot per intensità.

### Flusso
```
NASA FIRMS Download (HTTP CSV — API NASA)
  → NASA FIRMS Parse (Code)
      aggrega: totale rilevamenti, rilevamenti per giorno, FRP stats (min/avg/max/p95),
               top 20 rilevamenti per FRP, breakdown confidenza e giorno/notte
  → NASA AI Signals (chainLlm)
      input: totale, FRP stats, ultima giornata
      output: movement_label, signals, summary_en
  → NASA Parse Signals (Code)
  → NASA MongoDB raw_environment
  → NASA MongoDB ingestion_log
```

### Documento MongoDB
```json
{
  "source": "NASA_FIRMS",
  "country": "BR",
  "macroarea": "environment",
  "collected_at": "...",
  "is_fresh": true,
  "lookback_days": 5,
  "total_detections": 1243,
  "latest_day": "2026-04-08",
  "latest_day_count": 312,
  "frp_stats": {"min_mw": 6.2, "avg_mw": 45.1, "max_mw": 892.3, "p95_mw": 210.0},
  "confidence_counts": {"high": 800, "medium": 350, "low": 93},
  "movement_label": "fire_activity_normal",
  "signals": ["312 fire detections on latest day", "FRP p95 within seasonal norm"],
  "summary_en": "...",
  "_chart_fields": ["detections", "detections_by_day", "top_detections_by_frp"]
}
```

### Qdrant
Non utilizzato.

---

## 5. NOAA ENSO — Indice climatico ONI

**Macroarea:** `environment` → MongoDB `raw_environment`  
**Cadenza:** mensile  
**`is_fresh` threshold:** 35 giorni  

### Cosa raccoglie
L'indice ONI (Oceanic Niño Index) mensile da NOAA. Scarica il file testuale `oni.data` da PSL NOAA, parsifica tutte le righe storiche (anno + 12 mesi ONI), estrae la lettura più recente. Classifica la fase ENSO con soglie ±0.5 (weak) e ±1.5 (strong). Genera impatto previsto per Nord-Nordest e Sud Brasile, alert level (LOW / MODERATE / CRITICAL). Storico 6 mesi.

### Flusso
```
NOAA ENSO Download (HTTP — file testuale psl.noaa.gov)
  → NOAA ENSO Parse (Code)
      parsifica il file formato fisso, classifica la fase ENSO,
      calcola l'impatto previsto per Nord-Nordest Brasile e Sud Brasile,
      costruisce serie storica 6 mesi
  → NOAA AI Signals (chainLlm)
      input: ONI value, fase, fase strength, impact forecast
      output: movement_label, signals, summary_en
  → NOAA Parse Signals (Code)
  → NOAA MongoDB raw_environment
  → NOAA MongoDB ingestion_log
```

### Documento MongoDB
```json
{
  "source": "NOAA_ENSO",
  "country": "BR",
  "macroarea": "environment",
  "collected_at": "...",
  "is_fresh": true,
  "oni_value": -1.2,
  "enso_phase": "La Niña",
  "phase_strength": "strong",
  "alert_level": "high",
  "impact_forecast": "Reduced rainfall expected in Minas Gerais and Espírito Santo",
  "brazil_impact_north_northeast": "Drought risk elevated",
  "brazil_impact_south": "Erratic rainfall pattern",
  "movement_label": "la_nina_active",
  "signals": ["ONI at -1.2, strong La Niña phase active", "Drought risk for arabica regions"],
  "summary_en": "...",
  "_chart_fields": ["recent_series"]
}
```

### Qdrant
Non utilizzato.

---

## 6. CONAB — Bollettino produzione caffè Brasile

**Macroarea:** `colture` → MongoDB `raw_crops` + Qdrant `crops_texts`  
**Cadenza:** settimanale (quando esce un nuovo levantamento)  

### Cosa raccoglie
Il bollettino ufficiale CONAB sulla produzione di caffè brasiliano. È la fonte qualitativa più ricca: contiene analisi degli esperti, stime di produzione per stato, breakdown arabica/conilon, e outlook stagionale. Pipeline in 6 step che unisce dati quantitativi XLS + analisi qualitativa PDF.

### Flusso
```
CONAB Index Download (HTTP — pagina indice gov.br)
  → CONAB Extract Levantamento URL (Code)
      trova il link all'ultimo levantamento disponibile
  → CONAB Fetch Levantamento Page (HTTP)
      scarica la pagina HTML del levantamento specifico
  → CONAB Parse Latest Release (Code)
      estrae: URL del PDF, URL dell'XLS, numero levantamento, stagione
  → CONAB Download Table (HTTP — file XLS)
  → CONAB Extract Table (extractFromFile)
  → CONAB Parse Table (Code)
      parsifica XLS: snapshot nazionale, stati foco (MG/ES/BA/RO),
                     top stati per produzione, arabica vs conilon
  → CONAB Download PDF (HTTP)
  → CONAB Extract PDF (extractFromFile)
      estrae testo grezzo dal PDF (pdfplumber)
  → CONAB AI Signals (chainLlm)
      input: dati XLS strutturati + primi 14.000 char del PDF
      output: movement_label, signals, summary_en
  → CONAB Parse Signals (Code)
      fonde tutto + salva pdf_excerpt (6.000 char) per MongoDB
  → CONAB MongoDB raw_crops
  → CONAB OpenAI Embeddings (HTTP — text-embedding-3-small)
      testo: summary_en + signals + 1.200 char PDF
  → CONAB Qdrant Upsert
  → CONAB MongoDB ingestion_log
```

### Documento MongoDB
```json
{
  "source": "CONAB",
  "country": "BR",
  "macroarea": "colture",
  "collected_at": "...",
  "survey_number": 3,
  "season": "2025/26",
  "national_snapshot": {"arabica_production_bags": 38500000, "conilon_production_bags": 16000000},
  "focus_states": [{"state": "Minas Gerais", "production_bags": 25000000}, "..."],
  "pdf_excerpt": "O terceiro levantamento da safra 2025/26...",
  "movement_label": "supply_tightening",
  "signals": ["Arabica production revised down 3% vs previous survey", "Minas Gerais yield below 5-year avg"],
  "summary_en": "...",
  "_chart_fields": []
}
```

### Qdrant (`crops_texts`)
Embedding di: `summary_en + signals + 1.200 char PDF`. Usato dal `crops_agent` nel RAG.

---

## 7. USDA FAS PSD — Dati produzione/consumo caffè

**Macroarea:** `colture` → MongoDB `raw_crops`  
**Cadenza:** settimanale  

### Cosa raccoglie
I dati PSD (Production, Supply & Distribution) dell'USDA FAS per caffè verde brasiliano (commodity `0711100`, country `BR`). Costruisce una lista di 12 anni, itera con HTTP Request per anno sull'API `api.fas.usda.gov`. Include produzione, consumo domestico, export, stock di fine anno.

### Flusso
```
USDA Build Year List (Code)
  costruisce la lista degli anni da scaricare (12 anni)
  → USDA Fetch Year Data (HTTP — api.fas.usda.gov, un call per anno)
  → USDA Parse PSD (Code)
      aggrega anni, costruisce: latest marketing year, confronto anno precedente,
                                serie storica 6 anni, metrics derivate
  → USDA AI Signals (chainLlm)
  → USDA Parse Signals (Code)
  → USDA MongoDB raw_crops
  → USDA MongoDB ingestion_log
```

### Documento MongoDB
```json
{
  "source": "USDA_FAS_PSD",
  "country": "BR",
  "macroarea": "colture",
  "collected_at": "...",
  "commodity_name": "Coffee, Green",
  "market_year_label": "2025/26",
  "latest": {"production_1000_bags": 67300, "domestic_consumption": 23800, "exports": 42000},
  "previous": {"production_1000_bags": 66500, "...": "..."},
  "derived_metrics": {"yoy_production_pct": 1.2, "export_ratio_pct": 62.4},
  "movement_label": "supply_expanding",
  "signals": ["Production up 1.2% YoY", "Export ratio at 62% of production"],
  "summary_en": "...",
  "_chart_fields": ["yearly_series", "monthly_series"]
}
```

### Qdrant
Non utilizzato.

---

## 8. IBGE SIDRA — Previsione raccolta stati brasiliani

**Macroarea:** `colture` → MongoDB `raw_crops`  
**Cadenza:** settimanale  

### Cosa raccoglie
I dati LSPA (Levantamento Sistemático da Produção Agrícola) dell'IBGE tramite API SIDRA (`apisidra.ibge.gov.br`). Fornisce stime di produzione di arabica e conilon per i 4 stati focus: Minas Gerais, Espírito Santo, Bahia, Rondônia. Calcola confronto con il periodo precedente e classifica risk level.

### Flusso
```
IBGE SIDRA Download (HTTP — apisidra.ibge.gov.br)
  → IBGE SIDRA Parse (Code)
      aggrega per stato e specie (arabica/canephora),
      costruisce: snapshot nazionale, confronto, stati focus (MG/ES/BA/RO), serie storica
  → IBGE AI Signals (chainLlm)
      input: snapshot nazionale, stati focus, metriche derivate
      output: movement_label, signals, summary_en
  → IBGE Parse Signals (Code)
  → IBGE MongoDB raw_crops
  → IBGE MongoDB ingestion_log
```

### Documento MongoDB
```json
{
  "source": "IBGE_SIDRA_LSPA",
  "country": "BR",
  "macroarea": "colture",
  "collected_at": "...",
  "latest_period_label": "Mar/2026",
  "national_latest": {"arabica_t": 2450000, "canephora_t": 980000},
  "state_focus_latest": [
    {"state": "Minas Gerais", "arabica_t": 1600000, "canephora_t": 0}
  ],
  "derived_metrics": {"yoy_arabica_pct": -2.1, "yoy_canephora_pct": 3.5},
  "movement_label": "regional_shift",
  "signals": ["Arabica down 2.1% YoY nationally", "Conilon up 3.5% in Rondônia"],
  "summary_en": "...",
  "_chart_fields": ["recent_series", "state_focus_latest"]
}
```

### Qdrant
Non utilizzato.

---

## 9. Comex Stat — Export caffè brasiliano

**Macroarea:** `colture` → MongoDB `raw_crops`  
**Cadenza:** mensile  
**`is_fresh` threshold:** 35 giorni  

### Cosa raccoglie
I dati di export di caffè brasiliano dal sistema Comex Stat del Ministério do Desenvolvimento (MDIC). Controlla prima la data di ultimo aggiornamento API. Monitora 8 codici NCM specifici per caffè verde, tostato e solubile. **3 chiamate HTTP** in sequenza con un wait di 7 secondi tra la prima e la seconda.

### NCM codes monitorati
- Verde: `09011110`, `09011190`, `09011200`
- Tostato: `09012100`, `09012200`
- Solubile: `21011110`, `21011190`, `21011200`

### Flusso
```
Comex Updated Check (HTTP — verifica data aggiornamento API)
  → Comex Build Query Params (Code)
      costruisce i parametri per le 3 chiamate:
      - state_series_request (6 mesi, country+ncm)
      - port_snapshot_request (5 mesi, via+ncm)
  → Comex Fetch State Series Window (HTTP — serie storica 6 mesi)
  → Comex Wait (7s)
  → Comex Port Snapshot (HTTP — modalità trasporto 5 mesi)
  → Comex Parse (Code)
      aggrega: export totale mensile, product mix (verde/tostato/solubile),
               top 10 paesi destinatari, timeseries destinazioni 5 mesi,
               timeseries trasporto 5 mesi, top porti, variazioni MoM/YoY
  → Comex AI Signals (chainLlm)
  → Comex Parse Signals (Code)
  → Comex MongoDB raw_crops
  → Comex MongoDB ingestion_log
```

### Documento MongoDB
```json
{
  "source": "COMEX_STAT",
  "country": "BR",
  "macroarea": "colture",
  "collected_at": "...",
  "is_fresh": true,
  "latest_month": {"period": "2026-02", "total_exports_fob_usd": 890000000, "total_exports_kg": 210000000},
  "product_mix": {"green": {"share_kg_pct": 74.2}, "roasted": {"share_kg_pct": 18.1}, "soluble": {"share_kg_pct": 7.7}},
  "top_destinations": [{"country": "USA", "fob_usd": 180000000, "share_fob_pct": 20.2}],
  "derived_metrics": {"yoy_exports_kg_pct": -3.1, "avg_price_yoy_pct": 8.4},
  "movement_label": "mixed",
  "signals": ["Export volume down 3.1% YoY", "Average export price up 8.4% YoY"],
  "summary_en": "...",
  "_chart_fields": ["recent_series", "destinations_series", "transport_series", "top_ports"]
}
```

### Qdrant
Non utilizzato.

---

## 10. FAOSTAT QCL — Dati produzione FAO

**Macroarea:** `colture` → MongoDB `raw_crops`  
**Cadenza:** mensile  

### Cosa raccoglie
I dati di produzione agricola del Brasile dal dataset QCL (Crops and Livestock Products) della FAO. Include: produzione (tonnellate), resa (kg/ha), area raccolta (ha), export. Raccoglie gli ultimi **6 anni** disponibili. Richiede autenticazione con token JWT.

### Flusso
```
FAOSTAT Auth Login (HTTP — ottiene token JWT)
  → FAOSTAT Extract Token (Code)
  → FAOSTAT QCL Download (HTTP — API con token)
  → FAOSTAT Parse QCL (Code)
      aggrega per anno: produzione, resa, area, export
      calcola: YoY changes, movement_label, serie storica 6 anni
  → FAOSTAT AI Signals (chainLlm)
  → FAOSTAT Parse Signals (Code)
  → FAOSTAT MongoDB raw_crops
  → FAOSTAT MongoDB ingestion_log
```

### Documento MongoDB
```json
{
  "source": "FAOSTAT_QCL",
  "country": "BR",
  "macroarea": "colture",
  "collected_at": "...",
  "item_name": "Coffee, green",
  "latest_year": 2024,
  "latest": {"production_t": 3200000, "yield_kgha": 1580, "export_t": 2100000},
  "previous": {"production_t": 3050000, "yield_kgha": 1520},
  "derived_metrics": {"yoy_production_pct": 4.9, "yoy_yield_pct": 3.9},
  "movement_label": "supply_expanding",
  "signals": ["Production up 4.9% YoY", "Yield per hectare at 6-year high"],
  "summary_en": "...",
  "_chart_fields": ["yearly_series"]
}
```

### Qdrant
Non utilizzato.

---

## 11. WTO RSS — Notizie commercio internazionale

**Macroarea:** `geo` → MongoDB `raw_geo` + Qdrant `geo_texts`  
**Cadenza:** ogni 6 ore  

### Cosa raccoglie
Articoli e comunicati dal feed RSS del WTO rilevanti per il commercio di caffè e le relazioni commerciali Brasile-mondo. Usa il nodo nativo `rssFeedRead`. Ogni articolo viene filtrato da AI (rilevanza) e arricchito con segnali estratti. Embedding OpenAI `text-embedding-3-small`.

### Flusso
```
WTO HTTP Fetch (HTTP — RSS feed)
  → WTO Parse RSS (Code)
      parsifica il feed, estrae titolo/link/testo
  → WTO Loop (splitInBatches — processa un articolo per volta)
      → WTO Scrape Article (HTTP — scarica testo completo)
      → WTO Strip HTML (Code)
      → WTO LLM Filter (chainLlm)
            valuta se l'articolo è rilevante per caffè brasiliano
      → WTO If (condizionale — scarta se non rilevante)
      → WTO Extract Signals (chainLlm)
            estrae segnali geopolitici/commerciali dall'articolo
      → WTO Parse Signals (Code)
      → WTO MongoDB raw_geo
      → WTO OpenAI Embeddings (HTTP — text-embedding-3-small)
      → WTO Qdrant Upsert
  → WTO MongoDB ingestion_log
```

### Documento MongoDB
```json
{
  "source": "WTO_RSS",
  "country": "BR",
  "macroarea": "geo",
  "collected_at": "...",
  "title": "WTO members reach agreement on agricultural subsidies",
  "url": "...",
  "signals": ["New WTO ruling may affect Brazilian coffee export tariffs"],
  "movement_label": "trade_risk_emerging",
  "summary_en": "...",
  "_chart_fields": []
}
```

### Qdrant (`geo_texts`)
Embedding del testo completo dell'articolo. Usato dal `geo_agent`.

---

## 12. GDELT — Notizie geopolitiche

**Macroarea:** `geo` → MongoDB `raw_geo` + Qdrant `geo_texts`  
**Cadenza:** ogni ora  
**Stato:** ⚠️ parzialmente incompleto — Multi-Query presente ma salvataggio MongoDB da verificare

### Cosa raccoglie
Articoli da GDELT v2 su 5 temi: caffè brasiliano, proteste/instabilità politica, congestione porti, politica commerciale, disastri naturali. **5 query sequenziali** con wait di 4 secondi tra una e l'altra. Deduplica articoli per URL, filtra con LLM chain (rilevanza caffè/Brasile), scrape corpo articolo, estrazione segnali strutturati (topic, sentiment, entities, signals), embedding OpenAI `text-embedding-3-small`.

### Flusso
```
GDELT caffè (HTTP) → Wait 4s
  → GDELT proteste (HTTP) → Wait 4s
      → GDELT porti (HTTP) → Wait 4s
          → GDELT politica (HTTP) → Wait 4s
              → GDELT disastri (HTTP)
                  → GDELT Multi-Query (Code)
                      aggrega i risultati delle 5 query, deduplica per URL
                  → [salvataggio MongoDB + Qdrant da completare]
```

### Documento MongoDB (struttura attesa)
```json
{
  "source": "GDELT",
  "country": "BR",
  "macroarea": "geo",
  "collected_at": "...",
  "query_topic": "coffee_prices",
  "articles": [{"title": "...", "url": "...", "date": "..."}],
  "signals": ["..."],
  "summary_en": "...",
  "_chart_fields": []
}
```

### Qdrant (`geo_texts`)
Embedding articoli rilevanti. Usato dal `geo_agent`.

---

## 13. Port Congestion — Congestione porti brasiliani

**Macroarea:** `geo` → MongoDB `raw_geo` + Qdrant `geo_texts`  
**Cadenza:** da definire  
**Stato:** ⚠️ usa servizio interno `ais-port-probe` — da verificare disponibilità

### Cosa raccoglie
Snapshot della congestione nei principali porti brasiliani (Santos, Paranaguá, Vitória) tramite un probe AIS interno. Rilevante per identificare blocchi logistici che potrebbero ritardare le spedizioni di caffè.

### Flusso
```
Port Congestion Snapshot (HTTP — http://ais-port-probe:8080/snapshot)
  → Port Congestion Parse (Code)
  → Port MongoDB raw_geo
  → Port OpenAI Embeddings (HTTP)
  → Port Qdrant Upsert
  → Port MongoDB ingestion_log
```

> **Nota:** questo connettore non ha ancora un nodo AI Signals. Da aggiungere seguendo le regole in `regole-ingestion.md`.

---

## Riepilogo storage

| Connettore | Macroarea | MongoDB | Qdrant | Cadenza | AI Signals |
|---|---|---|---|---|---|
| BCB PTAX | prices | `raw_prices` | — | giornaliero | ✓ |
| ECB Data Portal | prices | `raw_prices` | — | giornaliero | ✓ |
| World Bank Pink Sheet | prices | `raw_prices` | — | mensile | ✓ |
| NASA FIRMS | environment | `raw_environment` | — | ogni ora | ✓ |
| NOAA ENSO | environment | `raw_environment` | — | mensile | ✓ |
| CONAB | colture | `raw_crops` | `crops_texts` | settimanale | ✓ |
| USDA FAS PSD | colture | `raw_crops` | — | settimanale | ✓ |
| IBGE SIDRA | colture | `raw_crops` | — | settimanale | ✓ |
| Comex Stat | colture | `raw_crops` | — | mensile | ✓ |
| FAOSTAT QCL | colture | `raw_crops` | — | mensile | ✓ |
| WTO RSS | geo | `raw_geo` | `geo_texts` | ogni 6 ore | ✓ |
| GDELT | geo | `raw_geo` | `geo_texts` | ogni ora | ⚠️ da completare |
| Port Congestion | geo | `raw_geo` | `geo_texts` | da definire | ✗ mancante |
