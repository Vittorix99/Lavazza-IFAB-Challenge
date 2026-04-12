# Lavazza — Esperto Globale delle Origini del Caffè

## Cos'è questo progetto

Piattaforma di intelligence automatizzata per Lavazza che monitora le condizioni nei paesi di origine del caffè e produce report narrativi e dashboard per i team interni.

**Deadline prototipo:** 20 aprile 2026
**Paese target fase 1:** Solo Brasile

---

## Architettura — due layer

### Layer 1 — Ingestion (n8n)
Workflow n8n schedulati raccolgono dati dalle fonti esterne e salvano in MongoDB o Qdrant.

Ogni documento salvato include quattro campi fissi:
- `country`: sempre `"BR"`
- `macroarea`: uno tra `geo`, `colture`, `prices`, `environment`
- `collected_at`: ISO 8601 timestamp
- `collected_period`: stringa derivata da `collected_at` + cadenza (`YYYY-MM-DDTHH` / `YYYY-MM-DD` / `YYYY-Www` / `YYYY-MM`) — usata per dedup

Al termine di ogni run il connettore scrive in `ingestion_log` (MongoDB) con: `source`, `country`, `run_date`, `status: "done"`, `completed_at`.

### Layer 2 — Agenti (Python + LangGraph)
Grafo LangGraph triggerato quando tutti i connettori attesi hanno completato l'ingestion. Orchestratore paese → 4 sub-agenti paralleli → aggregazione score → report narrativo (Claude Sonnet) → aggiornamento DB.

---

## 13 Fonti dati attive (Brasile)

| # | Fonte | Macroarea | Tipo | Cadenza |
|---|-------|-----------|------|---------|
| 1 | GDELT Project | geo | Tipo 5 — API + OpenAI | Ogni ora |
| 2 | WTO News | geo | Tipo 5 — API + OpenAI | Ogni 6 ore |
| 3 | Port Congestion (AIS interno) | geo | Tipo 1 — HTTP interno | Ogni ora |
| 4 | CONAB PDF | colture | Tipo 4 — PDF + OpenAI | Trimestrale |
| 5 | USDA FAS PSD | colture | Tipo 1 — API JSON | Settimanale |
| 6 | IBGE SIDRA | colture | Tipo 1 — API JSON | Settimanale |
| 7 | Comex Stat | colture | Tipo 1 — API JSON | Mensile |
| 8 | FAOSTAT QCL | colture | Tipo 1 — API JSON | Mensile |
| 9 | World Bank Pink Sheet | prices | Tipo 3 — XLS download | Mensile |
| 10 | BCB PTAX | prices | Tipo 1 — API OData | Giornaliero |
| 11 | ECB Data Portal | prices | Tipo 1 — API SDMX | Giornaliero |
| 12 | NASA FIRMS | environment | Tipo 1 — API JSON | Ogni ora |
| 13 | NOAA ENSO Index | environment | Tipo 3 — file download | Mensile |

---

## Tipi di connettore

- **Tipo 1 — API REST JSON:** fetch HTTP GET → aggiungi 4 campi fissi → salva in MongoDB as-is. Zero LLM.
- **Tipo 3 — Bulk file download:** HTTP GET → estrai righe rilevanti → salva in MongoDB. Zero LLM.
- **Tipo 4 — PDF:** estrai testo → OpenAI struttura JSON → salva JSON in MongoDB + embedding in Qdrant.
- **Tipo 5 — API testuale con news:** fetch API → OpenAI estrae segnali → salva metadati in MongoDB + embedding in Qdrant.

**Nota:** LLM usato nei connettori è OpenAI (gpt-5.4 / gpt-5.4-mini / gpt-5-mini), non Claude Haiku. Claude Haiku/Sonnet è usato solo nel Layer 2 (agenti Python).

**Port Congestion:** microservizio interno `ais-port-probe` (container Docker `docker/ais-port-probe/`) che espone `http://ais-port-probe:8080/snapshot`. Salva in `raw_geo` + embedding in Qdrant `geo_texts`.

---

## Storage

### MongoDB (database: `lavazza_ifab`)
- `raw_geo` — dati geopolitici (GDELT, WTO)
- `raw_crops` — dati colture (USDA, IBGE, Comex, CONAB)
- `raw_prices` — dati prezzi (World Bank, BCB, ECB)
- `raw_environment` — alert ambientali (NASA FIRMS, NOAA ENSO)
- `ingestion_log` — stato run connettori (trigger LangGraph)
- `agent_runs` — storico score e final_score

### Qdrant
- `geo_texts` — embedding news GDELT + WTO RSS
- `crops_texts` — embedding PDF CONAB
- `reports_archive` — embedding report narrativi (RAG weekly/monthly)

---

## 4 Sub-agenti LangGraph

| Agente | Fonte | LLM | Output |
|--------|-------|-----|--------|
| `geo_agent` | Qdrant `geo_texts` | Claude Haiku | `score_geo` (0-100) + `summary_geo` |
| `environment_agent` | MongoDB `raw_environment` | Nessuno | `score_environment` (0-100) |
| `crops_agent` | MongoDB `raw_crops` + Qdrant `crops_texts` | Claude Haiku | `score_crops` (0-100) + `summary_crops` |
| `prices_agent` | MongoDB `raw_prices` | Nessuno | `score_prices` (0-100) |

### Formula Score di Rischio

```
final_score = (score_geo × 0.25) + (score_environment × 0.30) + (score_crops × 0.30) + (score_prices × 0.15)
```

Soglie: `0-40` = verde (normale) · `41-70` = giallo (watch) · `71-100` = rosso (alert immediato)

---

## AgentState (TypedDict LangGraph)

```python
class AgentState(TypedDict):
    country: str           # "BR"
    report_type: str       # "daily" | "weekly" | "monthly"
    run_at: str            # ISO 8601 timestamp
    scores: dict           # {"geo": float, "environment": float, "crops": float, "prices": float}
    summaries: dict        # {"geo": str, "crops": str}
    raw_data: dict         # dati numerici selezionati dai sub-agenti
    final_score: float     # 0-100
    alerts: list[str]      # segnali critici
    rag_context: str       # testo report precedenti da Qdrant (weekly/monthly)
    report_json: dict      # JSON output di Claude Sonnet
    delivery_targets: list[str]  # team destinatari filtrati
```

---

## Output generate_report (JSON)

```json
{
  "headline": "...",
  "executive_summary": "...",
  "sections": [
    {"area": "geo", "score": 67, "text": "...", "signals": ["..."]},
    {"area": "environment", "score": 45, "text": "...", "signals": []},
    {"area": "crops", "score": 71, "text": "...", "signals": ["..."]},
    {"area": "prices", "score": 55, "text": "...", "signals": ["..."]}
  ],
  "correlations": ["..."],
  "risk_score": 62.0,
  "alerts": [],
  "outlook": "...",
  "report_type": "daily",
  "country": "BR",
  "run_at": "2026-03-25T07:00:00Z"
}
```

---

## Strategie LLM per report_type

- **Daily:** 1 chiamata Claude Sonnet. No RAG. Target 300-400 parole.
- **Weekly:** 3 chiamate Claude Sonnet (Acquisti / Quality / Management). RAG su ultimi 7 daily.
- **Monthly:** 1 Sonnet deep analysis + 3 Haiku per riscrittura per team. RAG su ultimi 4 weekly. PDF via WeasyPrint.

---

## Struttura directory

```
Lavazza-IFAB-Challenge/
├── lavazza-coffee-agent/
│   ├── agents/
│   │   ├── state.py             # AgentState TypedDict
│   │   ├── orchestrator.py      # grafo LangGraph principale
│   │   ├── geo_agent.py
│   │   ├── environment_agent.py
│   │   ├── crops_agent.py
│   │   ├── prices_agent.py
│   │   └── report_node.py       # generate_report con Claude Sonnet
│   ├── utils/
│   │   ├── db.py                # helper MongoDB
│   │   ├── geo_utils.py         # tagging geospaziale fuochi (L2 comuni caffè)
│   │   ├── qdrant.py            # helper Qdrant
│   │   ├── llm_analyzer.py      # wrapper Claude Haiku/Sonnet
│   │   └── split_doc.py         # chunking documenti lunghi
│   └── dashboard/
│       └── app.py               # Streamlit app (Layer 2)
├── dashboard/
│   └── dashboard.py             # Streamlit alternativo (standalone)
├── data_sources/                # script Python standalone test connettori
│   ├── colture/conab/
│   ├── colture/faostat/
│   ├── colture/usda/
│   ├── geo/gdelt/
│   └── prices/world_bank/
├── scripts/
│   └── setup_coffee_regions.py  # popola MongoDB coffee_regions (IBGE L1+L2)
├── docker/
│   ├── compose.yml              # MongoDB + Qdrant + n8n + ais-port-probe
│   ├── ais-port-probe/          # microservizio interno congestionamento porti
│   └── local-files/
│       └── workflows/
│           ├── split/           # 13 sub-workflow n8n (JSON)
│           └── Lavazza-MASTER-RUN.json
└── CLAUDE.md
```

---

## Variabili d'ambiente

```
ANTHROPIC_API_KEY=     # Claude API key
MONGODB_URI=           # mongodb://localhost:27017
MONGODB_DB=            # lavazza_ifab
QDRANT_URL=            # http://localhost:6333
NASA_FIRMS_KEY=        # MAP_KEY gratuita NASA
NOAA_TOKEN=            # token gratuito NOAA CDO
USDA_API_KEY=          # api.data.gov key gratuita
```

---

## Servizi locali

- n8n editor: `http://localhost:5678`
- Qdrant REST API: `http://localhost:6333`
- MongoDB: `mongodb://localhost:27017`
- Qdrant gRPC: `localhost:6334`

Credenziali MongoDB in `docker/.env`.

---

## Stack tecnologico

| Componente | Ruolo |
|------------|-------|
| n8n | Scheduling workflow ingestion (Docker) |
| LangGraph | Grafo agenti Python |
| OpenAI gpt-5.4 / gpt-5.4-mini / gpt-5-mini | Extraction n8n connettori Tipo 4/5 |
| Claude Haiku | Sub-agenti geo/crops (Layer 2 Python) |
| Claude Sonnet | Nodo generate_report (Layer 2 Python) |
| MongoDB 7 | Storage dati grezzi schemaless (Docker) |
| Qdrant | Vector store (Docker) |
| Streamlit | Dashboard prototipo |
| httpx | HTTP client async Python |
| feedparser | Parsing RSS |
| pdfplumber | Estrazione testo PDF |
| pandas | Parsing XLS/CSV bulk file |
| python-dotenv | Gestione variabili d'ambiente |

---

## Cosa NON è nel sistema

- No PostgreSQL — tutto su MongoDB
- No Metabase — Streamlit per il prototipo
- No invio email (Resend) — il report rimane su Streamlit
- No Vietnam — solo Brasile nella fase 1
- No meteo operativo (Open-Meteo escluso)
- No Gov.br RSS — feed fermo al 2023, scartato
- No ICO — esclusa dalla fase 1
- No WTO RSS classico — sostituito da WTO News (Tipo 5, con estrazione OpenAI)
- **FAOSTAT QCL è attivo** (contrariamente alla versione iniziale del doc) — incluso come fonte colture

## n8n — note implementative

- Tutti i sub-workflow usano `executeWorkflowTrigger` come entry point (obbligatorio per Master Run)
- Nessun sub-workflow ha nodi `Webhook Trigger` o `Respond to Webhook` (incompatibili con `executeWorkflow`)
- Master Run chiama i 13 sub-workflow in **catena seriale** con `waitForSubWorkflow: true` e `continueOnFail: true`
- `workflowId` nel Master Run usa formato `{__rl: true, value: "<id>", mode: "id"}`
- MongoDB dedup: indice `{source:1, collected_period:1}` con `partialFilterExpression: {collected_period: {$exists: true, $type: "string"}}` su tutte e 4 le collection raw_*
- MongoDB `coffee_regions`: collection con poligoni GeoJSON + indice 2dsphere, popolata da `scripts/setup_coffee_regions.py` (1 run manuale)
