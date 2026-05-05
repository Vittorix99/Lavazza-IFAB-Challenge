# Lavazza Coffee Intelligence System
## Presentazione del Prototipo — IFAB Challenge 2026

---

## 1. Il Problema

Lavazza approvvigiona caffè arabica principalmente dal **Brasile**, il paese produttore numero uno al mondo. Ogni anno, variabili difficili da monitorare manualmente impattano i costi e la disponibilità:

- **Clima:** El Niño / La Niña, siccità, incendi nelle zone di coltivazione
- **Prezzi:** arabica spot, tassi di cambio EUR/BRL, EUR/USD, pressione fertilizzanti
- **Colture:** produzione stimata, stock globali, volumi export
- **Geopolitica:** tensioni commerciali, congestione portuale, instabilità politica

Oggi questo monitoraggio è frammentato, manuale, e arriva in ritardo.

**Obiettivo:** un sistema automatizzato che raccoglie, analizza e sintetizza questi segnali in tempo reale, producendo report narrativi e una dashboard operativa per i team interni.

---

## 2. Architettura del Sistema

Il sistema si articola in **due layer distinti**:

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1 — INGESTION                                        │
│  n8n (scheduler) → 13 workflow → MongoDB + Qdrant           │
└─────────────────────────────────┬───────────────────────────┘
                                  │ trigger automatico
┌─────────────────────────────────▼───────────────────────────┐
│  LAYER 2 — INTELLIGENCE                                     │
│  LangGraph (Python) → 4 agenti paralleli → Claude Sonnet   │
│  └─→ Report JSON → Streamlit Dashboard                      │
└─────────────────────────────────────────────────────────────┘
```

### Stack tecnologico

| Componente | Tecnologia |
|------------|-----------|
| Scheduling ingestion | n8n (Docker) |
| Storage strutturato | MongoDB 7.0 |
| Storage vettoriale | Qdrant 1.16 |
| Grafo agenti | LangGraph 0.2 |
| Analisi sub-agenti | Claude Haiku |
| Report narrativo | Claude Sonnet |
| Embedding news/PDF | OpenAI text-embedding-3-small |
| Dashboard | Streamlit + Plotly |
| Containerizzazione | Docker Compose (4 servizi) |

---

## 3. Layer 1 — Ingestion con n8n

### 13 Fonti Dati Attive (Brasile)

Ogni workflow n8n raccoglie dati da una sorgente specifica, li normalizza con 4 campi fissi (`country`, `macroarea`, `collected_at`, `collected_period`) e li salva in MongoDB. Nessun dato viene scartato: tutto finisce nel DB grezzo per massima flessibilità.

#### Ambiente
| # | Fonte | Cosa raccoglie | Cadenza |
|---|-------|----------------|---------|
| 1 | **NOAA ENSO** | Indice ONI e SOI — El Niño / La Niña storico | Mensile |
| 2 | **NASA FIRMS** | Incendi attivi rilevati da satellite (VIIRS SNPP) nel Brasile | Ogni ora |

#### Prezzi
| # | Fonte | Cosa raccoglie | Cadenza |
|---|-------|----------------|---------|
| 3 | **World Bank Pink Sheet** | Prezzi arabica e robusta spot (USD/kg) | Mensile |
| 4 | **ECB Data Portal** | Tasso EUR/BRL ufficiale BCE | Giornaliero |
| 5 | **BCB PTAX** | Tasso BRL/USD banca centrale brasiliana | Giornaliero |

#### Colture
| # | Fonte | Cosa raccoglie | Cadenza |
|---|-------|----------------|---------|
| 6 | **USDA FAS PSD** | Bilancio produzione / consumo / stock arabica mondiale | Settimanale |
| 7 | **IBGE SIDRA** | Produzione agricola Brasile per stato e prodotto | Settimanale |
| 8 | **Comex Stat** | Volumi e valori export caffè Brasile | Mensile |
| 9 | **CONAB PDF** | Report ufficiale previsioni raccolto caffè Brasile | Trimestrale |
| 10 | **FAOSTAT QCL** | Dati storici FAO: produzione, area raccolta, resa | Mensile |

#### Geopolitica
| # | Fonte | Cosa raccoglie | Cadenza |
|---|-------|----------------|---------|
| 11 | **GDELT Project** | News globali su Brasile/caffè/porti/proteste | Ogni ora |
| 12 | **WTO News** | Comunicati WTO su commercio e dazi | Ogni 6 ore |
| 13 | **AIS Port Probe** | Congestione portuale (Santos, Paranaguá, Rio) via AIS | Ogni ora |

### Tipi di Connettore

- **API REST JSON** (USDA, IBGE, BCB, ECB, NASA FIRMS): fetch HTTP → salvataggio diretto. Zero LLM.
- **Bulk file download** (NOAA, World Bank XLS): parsing righe → estrazione colonne rilevanti. Zero LLM.
- **PDF + LLM** (CONAB): estrazione testo con pdfplumber → OpenAI struttura JSON → embedding Qdrant.
- **News + LLM** (GDELT, WTO): fetch API → OpenAI estrae segnali strutturati → MongoDB + embedding Qdrant.

### Deduplicazione

Indice MongoDB `{source, collected_period}` su tutte le collection raw_*. Ogni run è idempotente: ri-eseguire lo stesso workflow non duplica dati.

---

## 4. Storage

### MongoDB — `lavazza_ifab`

| Collection | Contenuto |
|------------|-----------|
| `raw_environment` | NOAA ENSO, NASA FIRMS |
| `raw_prices` | WB Pink Sheet, ECB, BCB PTAX |
| `raw_crops` | USDA, IBGE, Comex, CONAB, FAOSTAT |
| `raw_geo` | GDELT, WTO News, Port Congestion |
| `ingestion_log` | Stato completamento ogni workflow (trigger Layer 2) |
| `agent_runs` | Storico score, final_score, report JSON per ogni run |
| `coffee_regions` | Poligoni GeoJSON comuni produttori caffè Brasile (L1+L2 IBGE) |

### Qdrant — Vector Store

| Collection | Contenuto |
|------------|-----------|
| `geo_texts` | Embedding news GDELT + WTO (per ricerca semantica) |
| `crops_texts` | Embedding PDF CONAB (per analisi qualitativa raccolto) |
| `reports_archive` | Embedding report narrativi generati (per RAG weekly/monthly) |

---

## 5. Layer 2 — Grafo LangGraph

Il cervello del sistema. Quando tutti i connettori n8n hanno completato l'ingestion, LangGraph viene triggerato e esegue il grafo.

### Topologia del Grafo

```
START
  │
  ▼
init_node          → imposta run_at, country, report_type
  │
  ▼ [Fan-out parallelo — Send API]
  ├──▶ environment_agent
  ├──▶ prices_agent
  ├──▶ crops_agent
  └──▶ geo_agent
  │
  ▼ [Convergenza — reducer accumula signals + summaries]
aggregation_node   → calcola final_score pesato
  │
  ▼
chart_node         → produce metadati grafici (source, title, interpretive_text) per ogni fonte con dati disponibili ⚠️ roadmap
  │
  ▼
rag_node           → recupera report precedenti da Qdrant (weekly/monthly)
  │
  ▼
report_node        → genera report narrativo con Claude Sonnet
  │
  ▼
save_node          → salva su MongoDB agent_runs + Qdrant reports_archive
  │
  ▼
END
```

I 4 agenti girano **in parallelo** grazie alla Send API di LangGraph. Il risultato è uno stato aggregato che contiene i segnali di tutte le aree.

> **Nota — `chart_node` (roadmap):** il nodo è già presente nel grafo e produce correttamente `state.charts` — una lista di metadati per ogni fonte che ha restituito dati nel run (`chart_id`, `title`, `active`, `interpretive_text` estratto da `summary_en`). Nella versione attuale la Dashboard Visiva carica tutti gli 8 tab indipendentemente da questo output. Lo step successivo pianificato è usare `state.charts` per (a) mostrare solo i tab delle fonti con dati reali nel run e (b) aggiungere sotto ogni grafico il testo interpretativo generato dall'agente, contestualizzato allo score del momento.

### Formula Score di Rischio

```
final_score = (score_geo × 0.25)
            + (score_environment × 0.30)
            + (score_crops × 0.30)
            + (score_prices × 0.15)
```

| Range | Semaforo | Significato |
|-------|----------|-------------|
| 0–40  | 🟢 Verde  | Condizioni normali |
| 41–70 | 🟡 Giallo | Situazione da monitorare |
| 71–100| 🔴 Rosso  | Alert immediato per il team |

---

## 6. Dove Abbiamo Integrato l'AI

### Claude Haiku — Sub-Agenti (Analisi)

Ogni sub-agente passa i documenti MongoDB a **Claude Haiku** attraverso `utils/llm_analyzer.py`. Il prompt è **schema-agnostico**: Haiku riceve i documenti grezzi e capisce autonomamente cosa contiene ogni fonte, senza che il codice hardcodi i nomi dei campi. Questo significa che aggiungere una nuova fonte dati non richiede modifiche al codice degli agenti.

Ogni agente produce:
- `signals` — lista di fatti strutturati (`source`, `fact`, `direction`, `intensity`)
- `summary` — paragrafo narrativo sull'area
- `score` — punteggio 0-100 per quell'area

#### Contributo di ogni agente

| Agente | Fonti Analizzate | Peso Score |
|--------|-----------------|------------|
| `geo_agent` | Qdrant geo_texts (GDELT + WTO) + MongoDB raw_geo | 25% |
| `environment_agent` | NOAA ENSO + NASA FIRMS | 30% |
| `crops_agent` | USDA + IBGE + Comex + CONAB + FAOSTAT | 30% |
| `prices_agent` | World Bank + BCB + ECB | 15% |

#### Arricchimento geospaziale (NASA FIRMS)

Prima di passare i dati degli incendi a Haiku, il sistema li arricchisce con `geo_utils.tag_fires_with_coffee_zones()`: ogni coordinata GPS dell'incendio viene confrontata con i poligoni GeoJSON dei comuni brasiliani produttori di caffè (da `coffee_regions` MongoDB), e viene taggata con `in_coffee_zone: true/false`. Haiku vede quindi non solo "c'è un incendio" ma "c'è un incendio in zona di produzione caffè".

### Claude Sonnet — Report Node: gerarchia Daily → Weekly → Monthly

I report seguono una gerarchia a 3 livelli dove ogni livello si appoggia su quello precedente tramite RAG. Ogni report generato viene automaticamente embeddato e salvato in Qdrant `reports_archive` (`save_node`), costruendo nel tempo una base di conoscenza storica.

```
Daily  ──────────────────────────────────────────────────────
  nessun RAG — snapshot operativo del giorno
  → salvato in Qdrant reports_archive
         │
         ▼ (RAG: ultimi 7 daily)
Weekly ──────────────────────────────────────────────────────
  3 versioni persona-specific (Acquisti / Quality / Management)
  → salvato in Qdrant reports_archive
         │
         ▼ (RAG: ultimi 4 weekly)
Monthly ─────────────────────────────────────────────────────
  analisi strategica con visibilità sull'intero mese
```

| Tipo | LLM | RAG | Output | Stato |
|------|-----|-----|--------|-------|
| **Daily** | 1× Sonnet | No | Headline + 4 sezioni + outlook | ✅ Completo |
| **Weekly** | 3× Sonnet in sequenza | Sì — ultimi 7 daily | 3 report per team (Acquisti / Quality / Management) | ✅ Completo |
| **Monthly** | 3× Sonnet (= weekly) | Sì — ultimi 4 weekly | Stessa struttura weekly, `report_type: monthly` | ⚠️ Stub (alias weekly) |

> **Nota monthly:** nella versione attuale `report_node` chiama `_generate_weekly()` anche per il monthly — stesse 3 chiamate Sonnet, stessa struttura JSON. La differenza è solo nel campo `report_type` e nel numero di documenti RAG recuperati (4 invece di 7). La versione completa con deep analysis separata e PDF WeasyPrint è in roadmap.

Per il weekly e monthly, il sistema genera **3 versioni persona-specific** dello stesso report:
- **Team Acquisti** — price outlook, FX risk, finestra di hedging, supply risk
- **Team Quality** — impatto ambientale sulla qualità del chicco, analisi regionale, sensory risk
- **Management** — executive summary C-level, correlazioni strategiche, business impact, decisioni

### OpenAI text-embedding-3-small — Embedding

Usato nei connettori n8n (Tipo 4 e Tipo 5) per indicizzare news GDELT, comunicati WTO e PDF CONAB in Qdrant. Questo abilita la ricerca semantica nel chatbot e il RAG per i report weekly/monthly.

---

## 7. Dashboard Streamlit

La dashboard ha **4 tab principali**:

### Tab 1 — Daily Report
Il cuore operativo del sistema:
- **Bottone "Avvia Analisi"** → lancia il grafo LangGraph in streaming
- **Score Gauge** — termometro visivo verde/giallo/rosso con final_score
- **Executive Summary** — paragrafo narrativo generato da Sonnet
- **Area Scores** — barre per geo, environment, crops, prices con testo Haiku
- **Segnali Dettagliati** — tabella di tutti i signals dai 4 agenti
- **Alerts Attivi** — segnali critici evidenziati
- **Data Freshness** — tabella per ogni fonte: cadenza, giorni dall'ultimo aggiornamento, stato Fresh/Stale

### Tab 2 — Weekly Reports
3 colonne affiancate, una per team (Acquisti / Quality / Management):
- Ogni colonna mostra la versione persona-specific del report Sonnet
- Sezioni specifiche per area e correlazioni cross-area

### Tab 3 — Chat Intelligente
Chatbot con RAG:
- Input testuale dell'utente
- Embedding query → ricerca Qdrant `reports_archive` + `geo_texts`
- Contesto recuperato + streaming Claude Sonnet
- Storico conversazione in sessione

### Tab 4 — Dashboard Visiva
8 tab di grafici Plotly interattivi, con toggle **MongoDB / API Diretta** nella sidebar:

| Tab | Contenuto |
|-----|-----------|
| 🌦️ **Clima & ENSO** | Serie storica ONI (El Niño/La Niña) con bande colorate, SOI overlay, interpretazione segnale |
| 🔥 **Incendi** | Mappa scatter geografica degli incendi attivi, colorata per zona caffè, dimensione proporzionale a FRP (Fire Radiative Power) |
| 📈 **Prezzi di Mercato** | Arabica spot EUR/kg e BRL/kg storico 10 anni, tasso EUR/BRL, pressione margini fertilizzanti |
| 🌾 **Produttività Raccolti** | Produzione IBGE per stato brasiliano, trend annuale arabica vs robusta |
| 🌧️ **Precipitazioni** | Anomalie climatiche nelle regioni produttrici |
| 📦 **IBGE + Comex Export** | Volumi export caffè Brasile, breakdown per destinazione, confronto IBGE vs Comex |
| ⚓ **Porti & Trasporti** | Status congestione portuale Santos / Paranaguá / Rio, tempi attesa stimati |
| 🌱 **Fertilizzanti** | Prezzi DAP, Urea, MOP (USD/t), indice pressione sui margini del produttore brasiliano |

#### Architettura dei Grafici

Ogni grafico segue una catena di fallback a 3 livelli:
1. **MongoDB first** — legge i dati già raccolti da n8n
2. **API fallback** — chiama direttamente le API esterne (NOAA, yfinance, WB) se MongoDB è vuoto
3. **Dati simulati** — dataset deterministici come ultimo fallback, per garantire che la demo non sia mai vuota

---

## 8. Infrastruttura Docker

4 container in rete interna `lavazza_internal`:

```
┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌───────────────┐
│  n8n     │  │ MongoDB  │  │    Qdrant    │  │ ais-port-probe│
│ :5678    │  │  :27017  │  │ :6333/:6334  │  │  :8080 (int)  │
│ editor   │  │ raw data │  │ vector store │  │  AIS snapshot │
└──────────┘  └──────────┘  └──────────────┘  └───────────────┘
```

- **ais-port-probe** — microservizio custom (Go/Python) che interroga AISSTREAM per i 3 porti principali del caffè brasiliano e restituisce uno snapshot JSON della congestione
- **Tutti i servizi** hanno health check, restart policy e volume persistente

---

## 9. Punti di Forza del Design

### Schema-agnostico
Gli agenti LangGraph non hardcodano nomi di campi MongoDB. Haiku riceve i documenti grezzi e interpreta autonomamente. Aggiungere una fonte = attivare il connettore n8n. Il codice Python non cambia.

### Separazione LLM / dati
`split_doc()` divide ogni documento in due: la parte testuale/aggregata va a Haiku, la parte time-series (array grandi) va al chart_node. Haiku non spreca token su dati numerici non interpretabili; il chart engine ha tutto ciò che serve per i grafici.

### Fallback a 3 livelli per i grafici
MongoDB → API → Simulato. La demo funziona sempre, anche senza dati reali in MongoDB.

### RAG incrementale
Ogni report generato viene salvato in Qdrant `reports_archive`. Questo costruisce automaticamente una base di conoscenza storica che migliora i report weekly/monthly nel tempo.

### Multi-team output
Un singolo run LangGraph produce 3 versioni diverse dello stesso report, ottimizzate per Acquisti, Quality e Management. Stesso costo computazionale, tripla utilità.

---

## 10. Limiti e Roadmap

### Fase 1 (prototipo attuale)
- Solo Brasile
- Report daily + weekly funzionanti; monthly stub presente
- Nessun invio email (report su Streamlit)
- Nessun PostgreSQL — tutto MongoDB

### Fase 2 (roadmap)
- Aggiungere Vietnam come secondo paese origine
- Report monthly completo con PDF WeasyPrint
- Invio email automatico (Resend/SendGrid) al completamento del report
- Dashboard pubblica Lavazza con autenticazione
- Estensione fonti: ICO (International Coffee Organization), Open-Meteo per meteo operativo
- Confidence interval sullo score di rischio (Monte Carlo o Bayesian weighting)
- **`chart_node` → Dashboard Visiva**: usare `state.charts` per filtrare i tab mostrando solo le fonti con dati reali nel run, e visualizzare l'`interpretive_text` generato dall'agente come didascalia contestuale sotto ogni grafico

---

## Riepilogo in 5 punti

1. **13 fonti dati** raccolte automaticamente ogni ora/giorno/mese da n8n in MongoDB + Qdrant
2. **4 agenti LangGraph paralleli** (geo, ambiente, colture, prezzi) analizzano i dati con Claude Haiku — schema-agnostico
3. **Score di rischio 0-100** aggregato con pesi per area → semaforo verde/giallo/rosso
4. **Claude Sonnet** genera report narrativi in 3 versioni team-specific con RAG incrementale
5. **Dashboard Streamlit** con 4 tab: daily report, weekly per team, chatbot RAG, 8 grafici Plotly interattivi

---

*Prototipo — Deadline 20 Aprile 2026 — Paese target: Brasile*
