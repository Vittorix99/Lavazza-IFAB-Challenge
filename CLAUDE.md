# Lavazza — Esperto Globale delle Origini del Caffè

## Cos'è questo progetto

Piattaforma di intelligence automatizzata per Lavazza che monitora le condizioni nei paesi di origine del caffè e produce report narrativi e dashboard per i team interni.

**Deadline prototipo:** 20 aprile 2026
**Paese target fase 1:** Solo Brasile

---

## Architettura — due layer

### Layer 1 — Ingestion (n8n)
Workflow n8n schedulati raccolgono dati dalle fonti esterne e salvano in MongoDB o Qdrant.

Ogni documento salvato include tre campi fissi:
- `country`: sempre `"BR"`
- `macroarea`: uno tra `geo`, `colture`, `prices`, `environment`
- `collected_at`: ISO 8601 timestamp

Al termine di ogni run il connettore scrive in `ingestion_log` (MongoDB) con: `source`, `country`, `run_date`, `status: "done"`, `completed_at`.

### Layer 2 — Agenti (Python + LangGraph)
Grafo LangGraph triggerato quando tutti i connettori attesi hanno completato l'ingestion. Orchestratore paese → 4 sub-agenti paralleli → aggregazione score → report narrativo (Claude Sonnet) → aggiornamento DB.

---

## 11 Fonti dati attive (Brasile)

| # | Fonte | Macroarea | Tipo | Cadenza |
|---|-------|-----------|------|---------|
| 1 | GDELT Project | geo | Tipo 5 — API + Haiku | Ogni ora |
| 2 | WTO RSS | geo | Tipo 2 — RSS | Ogni 6 ore |
| 3 | CONAB PDF | colture | Tipo 4 — PDF + Haiku | Settimanale |
| 4 | USDA FAS PSD | colture | Tipo 1 — API JSON | Settimanale |
| 5 | IBGE SIDRA | colture | Tipo 1 — API JSON | Settimanale |
| 6 | Comex Stat | colture | Tipo 1 — API JSON | Mensile |
| 7 | World Bank Pink Sheet | prices | Tipo 3 — XLS download | Mensile |
| 8 | BCB PTAX | prices | Tipo 1 — API OData | Giornaliero |
| 9 | ECB Data Portal | prices | Tipo 1 — API SDMX | Giornaliero |
| 10 | NASA FIRMS | environment | Tipo 1 — API JSON | Ogni ora |
| 11 | NOAA ENSO Index | environment | Tipo 3 — file download | Mensile |

---

## Tipi di connettore

- **Tipo 1 — API REST JSON:** fetch HTTP GET → aggiungi 3 campi fissi → salva in MongoDB as-is. Zero LLM.
- **Tipo 2 — RSS feed:** feedparser → estrai titolo + link + testo → embedding in Qdrant + metadati in MongoDB. Zero LLM.
- **Tipo 3 — Bulk file download:** HTTP GET → pandas/openpyxl → estrai righe rilevanti → salva in MongoDB. Zero LLM.
- **Tipo 4 — PDF:** pdfplumber estrae testo → Claude Haiku struttura JSON → salva JSON in MongoDB + embedding in Qdrant.
- **Tipo 5 — API testuale con news:** fetch API → Claude Haiku estrae segnali → salva metadati in MongoDB + embedding in Qdrant.

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
lavazza-coffee-agent/
├── ingestion/
│   └── connectors/          # script Python standalone per test connettori
├── agents/
│   ├── state.py             # AgentState TypedDict
│   ├── orchestrator.py      # grafo LangGraph principale
│   ├── geo_agent.py
│   ├── environment_agent.py
│   ├── crops_agent.py
│   ├── prices_agent.py
│   └── report_node.py       # generate_report con Claude Sonnet
├── dashboard/
│   └── app.py               # Streamlit app
├── docker/
│   └── compose.yml          # MongoDB + Qdrant
├── .env.example
└── requirements.txt
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
| Claude Haiku | Extraction connettori Tipo 4/5 e sub-agenti geo/crops |
| Claude Sonnet | Nodo generate_report |
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
- No FAOSTAT, no ICO — escluse dalla fase 1
