# Piano di Implementazione — Bottom Up

Ogni livello dipende da quello precedente. Non iniziare un livello finché quello sotto non è testato e funzionante.

---

## Livello 0 — Infrastruttura ✓ (già fatto)

- [x] Docker: MongoDB + Qdrant attivi (`docker/compose.yml`)
- [x] n8n workflows: tutti i connettori configurati e testati
- [x] Dati grezzi presenti in MongoDB (`raw_geo`, `raw_crops`, `raw_prices`, `raw_environment`)
- [x] Embedding in Qdrant (`geo_texts`, `crops_texts`)

**Verifica prima di procedere:**
```bash
# MongoDB ha dati
mongosh lavazza_ifab --eval "db.raw_crops.countDocuments()"
mongosh lavazza_ifab --eval "db.raw_prices.countDocuments()"

# Qdrant ha vettori
curl http://localhost:6333/collections/geo_texts
curl http://localhost:6333/collections/crops_texts
```

---

## Livello 1 — Setup progetto Python

**File da creare:**

```
lavazza-coffee-agent/
├── requirements.txt
├── .env
└── utils/
    ├── __init__.py
    ├── db.py
    ├── qdrant.py
    └── split_doc.py
```

### `requirements.txt`
```
langgraph
langchain
langchain-anthropic
anthropic
pymongo
qdrant-client
python-dotenv
streamlit
matplotlib
pandas
weasyprint
httpx
```

### `utils/db.py`
Client MongoDB singleton + helper per leggere i documenti più recenti per source e macroarea.

```python
# Funzioni chiave da implementare:
get_latest_doc(collection, source, country="BR") -> dict
get_recent_docs(collection, macroarea, country="BR", limit=10) -> list[dict]
save_agent_run(run_doc: dict) -> str
```

### `utils/qdrant.py`
Client Qdrant + helper per ricerca semantica con filtri.

```python
# Funzioni chiave:
search(collection, query_text, limit=5, filter=None) -> list[dict]
upsert(collection, id, vector, payload) -> None
```

### `utils/split_doc.py`
```python
def split_doc(doc: dict) -> tuple[dict, dict]:
    chart_fields = set(doc.get("_chart_fields", []))
    doc_for_llm    = {k: v for k, v in doc.items() if k not in chart_fields}
    doc_for_charts = {k: v for k, v in doc.items() if k in chart_fields}
    return doc_for_llm, doc_for_charts
```

**Test Livello 1:**
```python
# Verifica connessioni
from utils.db import get_latest_doc
from utils.qdrant import search

doc = get_latest_doc("raw_crops", "COMEX_STAT")
assert doc is not None

results = search("geo_texts", "coffee production Brazil")
assert len(results) > 0
```

---

## Livello 2 — AgentState

**File:** `agents/state.py`

```python
from typing import TypedDict

class AgentState(TypedDict):
    country: str                  # "BR"
    report_type: str              # "alert" | "weekly" | "monthly"
    run_at: str                   # ISO 8601
    signals: list[dict]           # [{source, area, fact, direction, intensity, explanation}]
    summaries: dict               # {"geo": str, "crops": str, ...}
    data_freshness: dict          # {source: {days_old, is_fresh}}
    docs_for_charts: list[dict]   # doc_for_charts da tutti i connettori
    charts: list[dict]            # [{chart_id, title, active, interpretive_text}]
    rag_context: str              # testo da Qdrant
    report_json: dict             # output finale
    delivery_targets: list[str]   # team destinatari
```

**Test Livello 2:**
```python
state = AgentState(
    country="BR", report_type="weekly", run_at="...",
    signals=[], summaries={}, data_freshness={},
    docs_for_charts=[], charts=[], rag_context="",
    report_json={}, delivery_targets=[]
)
```

---

## Livello 3 — Sub-agenti (implementa e testa uno per volta)

Ogni agente è una funzione `agent_name(state: AgentState) -> AgentState`.

Tutti usano **Haiku**. Tutti chiamano `split_doc()` sui documenti prima di passarli al modello. Tutti producono segnali nella forma `{source, area, fact, direction, intensity, explanation}` senza assegnare valenza.

### 3a. `agents/environment_agent.py`

**Inizia da questo** — è il più semplice, i dati sono già strutturati.

Legge da MongoDB:
- `raw_environment` → `NASA_FIRMS` (ultimo documento)
- `raw_environment` → `NOAA_ENSO` (ultimo documento)

Passa `doc_for_llm` a Haiku. Accumula `doc_for_charts` in `state.docs_for_charts`.

**Test:** esegui l'agente standalone, verifica che `state.signals` contenga almeno 2 segnali con `area: "environment"`.

### 3b. `agents/prices_agent.py`

Legge da MongoDB:
- `raw_prices` → `BCB_PTAX`
- `raw_prices` → `ECB_DATA_PORTAL`
- `raw_prices` → `WB_PINK_SHEET`

Passa i 3 `doc_for_llm` in un unico prompt Haiku (o 3 chiamate separate).

**Test:** verifica segnali con `area: "prices"`.

### 3c. `agents/crops_agent.py`

Legge da MongoDB:
- `raw_crops` → `CONAB`, `USDA_FAS_PSD`, `IBGE_SIDRA_LSPA`, `COMEX_STAT`, `FAOSTAT_QCL`

Cerca anche in Qdrant `crops_texts` (embedding CONAB) per aggiungere contesto qualitativo.

**Test:** verifica segnali con `area: "crops"`, incluso testo CONAB dal RAG.

### 3d. `agents/geo_agent.py`

Legge da MongoDB:
- `raw_geo` → `WTO_RSS`, `GDELT`, `PORT_CONGESTION`

Cerca in Qdrant `geo_texts` i chunk più rilevanti.

**Test:** verifica segnali con `area: "geo"`.

---

## Livello 4 — Aggregation node

**File:** `agents/aggregation_node.py`

Raccoglie i segnali prodotti dai 4 agenti e calcola la freshness di ogni fonte.

```python
FRESHNESS_WINDOWS = {
    "alert":   {"raw_geo": 2h, "raw_environment": 2h, "raw_prices": 36h, "raw_crops": 8d},
    "weekly":  {"raw_geo": 2d, "raw_environment": 2d, "raw_prices": 2d,  "raw_crops": 8d},
    "monthly": {"raw_geo": 7d, "raw_environment": 35d,"raw_prices": 35d, "raw_crops": 35d},
}
```

Output: `state.signals` consolidato, `state.data_freshness` per fonte.

Per `report_type == "alert"`: filtra `state.signals` tenendo solo quelli con `is_fresh: true`.

**Test:** verifica che `state.data_freshness` contenga tutte le fonti con `days_old` e `is_fresh`.

---

## Livello 5 — Chart node e RAG node (implementa in parallelo, testali separatamente)

### 5a. `agents/chart_node.py`

Riceve `state.docs_for_charts` (gli array grandi di ogni documento).

Per ogni documento:
1. Cerca in MongoDB `chart_field_map` se il campo è già mappato (cache)
2. Se non trovato: invia metadati del campo a Haiku (nome, lunghezza, primo/ultimo valore)
3. Haiku decide quali dei 9 grafici pre-costruiti attivare
4. Haiku scrive una riga di testo interpretativo per ciascun grafico attivo

Output: `state.charts` → lista di `{chart_id, title, active: bool, interpretive_text}`.

**I 9 chart_id:**
```python
CHART_REGISTRY = [
    "wb_arabica_price_timeseries",
    "bcb_ecb_fx_timeseries",
    "noaa_enso_index",
    "nasa_firms_heatmap",
    "comex_export_volume",
    "comex_product_mix",
    "comex_destination_countries",
    "comex_transport_mode",
    "ibge_usda_production_forecast",
]
```

**Test:** verifica che `state.charts` abbia almeno 3 grafici con `active: true` e `interpretive_text` non vuoto.

### 5b. `agents/rag_node.py`

Usa i segnali in `state.signals` per costruire query semantiche mirate.

Interroga Qdrant su 3 collection:
- `reports_archive` (storico report, per weekly/monthly — skip per alert)
- `geo_texts` (se ci sono segnali geo)
- `crops_texts` (se ci sono segnali crops)

Costruisce `state.rag_context` come stringa di testo concatenata con separatori.

**Test:** verifica che `state.rag_context` sia non vuoto e contenga testo rilevante.

---

## Livello 6 — Report node

**File:** `agents/report_node.py`

Tre modalità in base a `state.report_type`:

### Alert (Haiku)
- Input: segnali freschi + nessun RAG
- Output: JSON con 3-5 bullet points
- Un'unica chiamata Haiku

### Weekly (3× Sonnet)
- Input: segnali + summaries + rag_context + charts attivi
- Una chiamata Sonnet per team: `Acquisti`, `Quality`, `Management`
- Ogni chiamata produce un `report_json` completo con sezioni per area

### Monthly (Sonnet + 3× Haiku)
- 1 Sonnet per l'analisi profonda
- 3 Haiku per riscrivere il report nel tono di ciascun team
- Output anche PDF via WeasyPrint

**Struttura `report_json`:**
```json
{
  "headline": "...",
  "executive_summary": "...",
  "sections": [
    {"area": "geo",         "text": "...", "signals": ["..."]},
    {"area": "environment", "text": "...", "signals": ["..."]},
    {"area": "crops",       "text": "...", "signals": ["..."]},
    {"area": "prices",      "text": "...", "signals": ["..."]}
  ],
  "correlations": ["..."],
  "outlook": "...",
  "report_type": "weekly",
  "country": "BR",
  "run_at": "...",
  "data_freshness": {"...": "..."},
  "team": "acquisti"
}
```

**Test:** esegui con dati reali da MongoDB. Verifica che il JSON sia completo e le sezioni abbiano testo > 100 caratteri.

---

## Livello 7 — Persist node

**File:** `agents/persist_node.py`

1. Salva `state.report_json` + `state.signals` + `state.charts` in MongoDB `agent_runs`
2. Crea embedding del testo narrativo del report
3. Upserta in Qdrant `reports_archive` con metadati: `{report_type, country, run_at, team}`

**Test:** verifica che dopo il run il documento sia in `agent_runs` e il vettore sia in `reports_archive`.

---

## Livello 8 — Orchestratore LangGraph

**File:** `agents/orchestrator.py`

Assembla il grafo:

```python
from langgraph.graph import StateGraph

graph = StateGraph(AgentState)

graph.add_node("agents",      run_agents_parallel)   # geo+env+crops+prices in parallelo
graph.add_node("aggregation", aggregation_node)
graph.add_node("chart",       chart_node)
graph.add_node("rag",         rag_node)
graph.add_node("report",      report_node)
graph.add_node("persist",     persist_node)

graph.set_entry_point("agents")
graph.add_edge("agents",      "aggregation")
graph.add_edge("aggregation", "chart")        # chart e rag in parallelo
graph.add_edge("aggregation", "rag")
graph.add_edge("chart",       "report")
graph.add_edge("rag",         "report")
graph.add_edge("report",      "persist")
graph.set_finish_point("persist")

app = graph.compile()
```

**Trigger manuale per il prototipo:**
```python
result = app.invoke({
    "country": "BR",
    "report_type": "weekly",
    "run_at": datetime.utcnow().isoformat(),
    "signals": [], "summaries": {}, "data_freshness": {},
    "docs_for_charts": [], "charts": [], "rag_context": "",
    "report_json": {}, "delivery_targets": ["acquisti", "quality", "management"]
})
```

**Test:** esegui il grafo completo end-to-end. Verifica che ogni nodo produca output atteso e il report finale sia in MongoDB.

---

## Livello 9 — Dashboard Streamlit

**File:** `dashboard/app.py`

Tre schermate, nessun LLM coinvolto — solo lettura da MongoDB.

### Schermata 1 — Dashboard
- Legge l'ultimo `agent_run` da MongoDB
- Mostra segnali per area (geo / environment / crops / prices)
- Renderizza i grafici con `active: true` usando Matplotlib/Plotly
- Mostra `data_freshness` per ogni fonte

### Schermata 2 — Daily Alerts
- Legge gli ultimi `agent_run` con `report_type: "alert"`
- Mostra i bullet points in ordine cronologico inverso

### Schermata 3 — Reports
- Selettore team (Acquisti / Quality / Management)
- Selettore tipo (Weekly / Monthly)
- Renderizza il `report_json` formattato con sezioni e grafici inline
- Per Monthly: bottone "Scarica PDF"

**Test:** avvia Streamlit con `streamlit run dashboard/app.py`. Verifica che tutte e 3 le schermate carichino dati reali da MongoDB.

---

## Livello 10 — Demo prototipo

**Preparazione per Lavazza (deadline 20 aprile 2026):**

1. Triggera manualmente il grafo per `report_type: "weekly"` → tutti e 3 i team
2. Triggera manualmente per `report_type: "monthly"` → genera PDF
3. Verifica dashboard con dati reali
4. Prepara 2-3 alert di esempio
5. Test presentazione: scorri le 3 schermate Streamlit live

---

## Ordine di implementazione raccomandato

| Settimana | Cosa fare |
|---|---|
| **Ora → 10 apr** | Livelli 1-2: setup progetto, utils, state |
| **10-13 apr** | Livello 3: 4 agenti (uno per giorno, testa ogni volta) |
| **13-15 apr** | Livello 4-5: aggregation + chart + rag |
| **15-17 apr** | Livello 6-7: report node + persist |
| **17-18 apr** | Livello 8: orchestratore LangGraph end-to-end |
| **18-19 apr** | Livello 9: Streamlit dashboard |
| **19-20 apr** | Livello 10: polish demo, test presentazione |
