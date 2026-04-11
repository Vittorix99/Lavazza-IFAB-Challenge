# Architettura Sistema — Lavazza Esperto Globale delle Origini del Caffè

**Deadline prototipo:** 20 aprile 2026  
**Paese target fase 1:** Brasile (BR)

---

## Visione generale

Il sistema monitora continuamente le condizioni nei paesi di origine del caffè e produce tre tipi di output: una dashboard sempre aggiornata, alert giornalieri e report narrativi periodici destinati ai team interni Lavazza.

È composto da due layer:

- **Layer 1 — Ingestion (n8n):** workflow schedulati che raccolgono dati da 11 fonti esterne e li salvano in MongoDB e Qdrant.
- **Layer 2 — Agenti (Python + LangGraph):** grafo di agenti AI che analizza i dati, genera segnali e produce report narrativi.

---

## Layer 1 — Ingestion (n8n)

### 11 fonti dati attive

| # | Fonte | Macroarea | Tipo | Cadenza |
|---|---|---|---|---|
| 1 | GDELT Project | geo | API + Haiku estrae segnali | Ogni ora |
| 2 | WTO RSS | geo | RSS → embedding | Ogni 6 ore |
| 3 | CONAB PDF + XLS | colture | XLS → dati strutturati, PDF → Haiku + excerpt | Settimanale |
| 4 | USDA FAS PSD | colture | API JSON | Settimanale |
| 5 | IBGE SIDRA | colture | API JSON | Settimanale |
| 6 | Comex Stat | colture | 3 HTTP: State Series 12m + Port Snapshot 5m | Mensile |
| 7 | World Bank Pink Sheet | prices | XLS download | Mensile |
| 8 | BCB PTAX | prices | API OData | Giornaliero |
| 9 | ECB Data Portal | prices | API SDMX | Giornaliero |
| 10 | NASA FIRMS | environment | API JSON | Ogni ora |
| 11 | NOAA ENSO | environment | File download | Mensile |

### Struttura di ogni documento salvato

Ogni documento salvato in MongoDB include tre campi fissi:

```json
{
  "country": "BR",
  "macroarea": "geo | colture | prices | environment",
  "collected_at": "2026-04-08T07:00:00Z"
}
```

E un campo speciale che dichiara quali campi contengono array grandi (timeseries, detection lists):

```json
{
  "_chart_fields": ["recent_series", "top_destinations", "transport_series"]
}
```

Questo campo è fondamentale per il Layer 2: permette agli agenti di separare i dati analitici dalle timeseries senza conoscere a priori la struttura del documento.

### Ingestion log

Al termine di ogni run, ogni connettore scrive in `ingestion_log`:

```json
{
  "source": "COMEX_STAT",
  "country": "BR",
  "run_date": "2026-04-08T07:00:00Z",
  "status": "done",
  "completed_at": "2026-04-08T07:03:21Z"
}
```

Questo log è il trigger per il Layer 2.

### Storage

| Collection MongoDB | Contenuto |
|---|---|
| `raw_geo` | GDELT + WTO |
| `raw_crops` | CONAB + USDA + IBGE + Comex |
| `raw_prices` | World Bank + BCB + ECB |
| `raw_environment` | NASA FIRMS + NOAA ENSO |
| `ingestion_log` | stato run connettori |

| Collection Qdrant | Contenuto |
|---|---|
| `geo_texts` | embedding news GDELT + WTO RSS |
| `crops_texts` | embedding estratti CONAB PDF |
| `reports_archive` | embedding report narrativi (RAG) |

---

## Layer 2 — Agenti (Python + LangGraph)

### Trigger

Il grafo LangGraph si attiva quando tutti i connettori attesi hanno scritto `status: "done"` in `ingestion_log`.

Per il prototipo il trigger è **manuale** — il grafo viene avviato a mano con i dati già presenti in MongoDB, producendo report one-time da mostrare a Lavazza.

### AgentState

Lo stato condiviso tra tutti i nodi del grafo:

```python
class AgentState(TypedDict):
    country: str                  # "BR"
    report_type: str              # "alert" | "weekly" | "monthly"
    run_at: str                   # ISO 8601
    signals: list[dict]           # segnali estratti dai 4 sub-agenti
    summaries: dict               # {"geo": str, "crops": str, ...}
    data_freshness: dict          # {source: {days_old, is_fresh}}
    charts: list[dict]            # grafici attivi + testo interpretativo
    rag_context: str              # testo da Qdrant per RAG
    report_json: dict             # output finale strutturato
    delivery_targets: list[str]   # team destinatari
```

### I 6 nodi del grafo

```
ingestion_log / trigger manuale
        │
  [1] agents_node
        │
  [2] aggregation_node
        │
    ┌───┴───┐
[3] chart   [4] rag
    node        node
    └───┬───┘
        │
  [5] report_node
        │
  [6] persist_node
```

---

### [1] agents_node

4 sub-agenti girano in parallelo. Prima di ricevere i documenti, ogni documento viene splittato con `split_doc()`:

```python
def split_doc(doc: dict) -> tuple[dict, dict]:
    chart_fields = set(doc.get("_chart_fields", []))
    doc_for_llm    = {k: v for k, v in doc.items() if k not in chart_fields}
    doc_for_charts = {k: v for k, v in doc.items() if k in chart_fields}
    return doc_for_llm, doc_for_charts
```

- `doc_for_llm` va all'agente: documento pulito senza timeseries grandi.
- `doc_for_charts` va al `chart_node`: solo gli array da plottare.

**I 4 sub-agenti usano tutti Haiku.**

Gli agenti **non conoscono a priori i campi dei documenti**. Haiku riceve `doc_for_llm` e scopre autonomamente cosa significano i campi leggendo nomi e valori. Se trova `enso_phase: "La Niña"` e `oni_value: -1.2` capisce da solo il significato senza che sia hardcoded. Se trova `mom_exports_kg_pct: -8.3` lo interpreta nel contesto dell'intero documento.

Questo rende il sistema **schema-agnostico**: se un connettore cambia i nomi dei campi o ne aggiunge di nuovi, gli agenti non si rompono.

| Sub-agente | Fonte MongoDB | Qdrant | Output |
|---|---|---|---|
| `geo_agent` | `raw_geo` | `geo_texts` | segnali geo |
| `environment_agent` | `raw_environment` | — | segnali environment |
| `crops_agent` | `raw_crops` | `crops_texts` | segnali crops |
| `prices_agent` | `raw_prices` | — | segnali prices |

Ogni segnale ha forma:

```python
{
    "source": "NOAA_ENSO",
    "area": "environment",
    "fact": "ONI index a -1.2, fase La Niña attiva",
    "direction": "negative",
    "intensity": "high",
    "explanation": "La Niña tende a ridurre le precipitazioni nel sud del Brasile..."
}
```

**Nessun score numerico.** Haiku non sa se un segnale è positivo o negativo per Lavazza senza il contesto del buyer — un aumento delle esportazioni brasiliane può essere buono (disponibilità) o cattivo (aumento prezzi) a seconda della posizione di acquisto. La valenza viene lasciata al report_node che ha il contesto completo.

---

### [2] aggregation_node

Consolida i segnali dai 4 sub-agenti in `state.signals` e calcola la **freshness** di ogni fonte rispetto al tipo di report:

```python
FRESHNESS_WINDOWS = {
    "alert": {
        "raw_geo":         timedelta(hours=2),
        "raw_environment": timedelta(hours=2),
        "raw_prices":      timedelta(hours=36),
        "raw_crops":       timedelta(days=8),
    },
    "weekly": {
        "raw_geo":         timedelta(days=2),
        "raw_environment": timedelta(days=2),
        "raw_prices":      timedelta(days=2),
        "raw_crops":       timedelta(days=8),
    },
    "monthly": {
        "raw_geo":         timedelta(days=7),
        "raw_environment": timedelta(days=35),
        "raw_prices":      timedelta(days=35),
        "raw_crops":       timedelta(days=35),
    },
}
```

Ogni segnale riceve `is_fresh` e `days_old`. Il `report_node` usa queste informazioni per contestualizzare i dati ("prezzi al 3 aprile, dato Comex fermo a febbraio") e per il tipo alert esclude completamente i segnali non freschi.

---

### [3] chart_node

Riceve i `doc_for_charts` di tutti i documenti (le timeseries grandi).

**Haiku non riceve le timeseries complete** — riceve solo i metadati di ogni campo (nome, lunghezza array, primo e ultimo elemento, tipo di valori). Questo evita di saturare la context window con 24 mesi di dati.

I metadati dei campi vengono cachati in MongoDB (`chart_field_map`): se Haiku ha già "imparato" cosa significa `recent_series` per la fonte `COMEX_STAT`, non viene rilasciata una nuova chiamata.

Haiku decide:
1. Quali dei 9 grafici pre-costruiti attivare in base ai dati disponibili
2. Una riga di testo interpretativo per ciascun grafico attivo

I grafici veri vengono poi costruiti da Streamlit/Matplotlib con i dati raw.

**9 grafici pre-costruiti:**

| # | Grafico | Fonte |
|---|---|---|
| 1 | Prezzi caffè timeseries | World Bank |
| 2 | BRL/USD + BRL/EUR timeseries | BCB + ECB |
| 3 | ENSO index con phase annotation | NOAA |
| 4 | NASA FIRMS fuochi per giorno | NASA |
| 5 | Comex export volume 12 mesi | Comex |
| 6 | Comex product mix verde/tostato/solubile | Comex |
| 7 | Comex top destination countries 5 mesi | Comex |
| 8 | Comex transport mode breakdown 5 mesi | Comex |
| 9 | IBGE/USDA production forecast timeseries | IBGE + USDA |

---

### [4] rag_node

Gira in parallelo al `chart_node`. Interroga Qdrant **guidato dai segnali** prodotti dall'`aggregation_node` — non è una query generica ma cerca contesto rilevante rispetto a quello che gli agenti hanno trovato.

Interroga 3 collection:

- `reports_archive` — report narrativi precedenti (contesto storico)
- `geo_texts` — news GDELT + WTO recenti
- `crops_texts` — estratti CONAB recenti

Produce `state.rag_context` (stringa di testo) che viene passato al `report_node`.

---

### [5] report_node

Riceve: `signals`, `summaries`, `data_freshness`, `charts`, `rag_context`.

Produce output diversi in base al `report_type`.

---

#### La piramide di sintesi progressiva

Il sistema è stratificato: ogni livello di report **ingloba quello sotto** tramite RAG. I dati grezzi non vengono riletti — vengono ereditati attraverso i report precedenti già sintetizzati.

```
    [monthly]  ← legge i 4 weekly del mese via RAG
        │          + dati mensili nuovi (Comex, NOAA, WB)
        │
    [weekly]   ← legge i 7 alert della settimana via RAG
        │          + tutti i dati della settimana (BCB, NASA, USDA...)
        │
    [alert]    ← legge solo i dati freschi delle ultime ore
                   (BCB di oggi, NASA di stamattina, GDELT recente)
```

**Alert** risponde a: *"cosa sta succedendo adesso?"*
**Weekly** risponde a: *"cosa è successo questa settimana, qual è il trend?"*
**Monthly** risponde a: *"qual è la situazione strutturale, cosa prevediamo?"*

Il monthly non butta via i dati giornalieri — li vede attraverso i weekly che li hanno già sintetizzati. Il weekly non rilancia le query sui dati raw — li eredita dagli alert. È una piramide di contesto crescente, non tre sistemi separati.

---

**Alert (giornaliero)**
- Modello: Haiku
- No RAG
- Solo segnali con `is_fresh: true` nelle ultime 24h
- Output: 3-5 bullet points
- Formato: JSON leggero

**Weekly (3 versioni per team)**
- Modello: 3 chiamate Sonnet — una per team (Acquisti / Quality / Management)
- RAG: ultimi 7 alert da `reports_archive` → eredita la narrativa dei 7 giorni
- Dati diretti: BCB/ECB 7 giorni, NASA cumulato, USDA/IBGE/CONAB se usciti
- Output: report narrativo strutturato per sezioni + grafici

**Monthly (3 versioni per team)**
- Modello: 1 Sonnet deep analysis + 3 Haiku per riscrittura per team
- RAG: ultimi 4 weekly da `reports_archive` → eredita il mese intero
- Dati diretti: Comex (export mese), NOAA (ENSO aggiornato), World Bank (prezzi)
- Output: report approfondito + grafici + PDF via WeasyPrint

**Struttura JSON del report:**

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
  "alerts": ["..."],
  "outlook": "...",
  "report_type": "weekly",
  "country": "BR",
  "run_at": "2026-04-08T07:00:00Z",
  "data_freshness": {"COMEX_STAT": {"days_old": 22, "is_fresh": false}},
  "team": "acquisti"
}
```

---

### [6] persist_node

- Salva report e segnali in MongoDB `agent_runs`
- Fa embedding del testo narrativo → Qdrant `reports_archive` (diventa RAG per i report futuri)

---

## Output — 4 superfici (Streamlit)

Le dashboard sono **completamente indipendenti dal grafo LangGraph**. Leggono direttamente da MongoDB senza passare per gli agenti. Nessun LLM viene chiamato a runtime nelle prime 3 superfici — zero latenza, zero costi API per visualizzare.

Se il grafo crasha, le dashboard rimangono funzionanti mostrando l'ultimo stato salvato.

```
MongoDB ←── n8n (ingestion)
   │
   └── Streamlit (lettura diretta, no LLM)
          ├── Tab 1: Dashboard
          ├── Tab 2: Alerts
          ├── Tab 3: Reports
          └── Tab 4: Chat (unico con LLM a runtime)
```

---

### Tab 1 — Dashboard

Legge i dati raw direttamente dalle collection MongoDB (`raw_environment`, `raw_crops`, `raw_prices`, `raw_geo`). Sempre live — si aggiorna ogni volta che n8n porta nuovi dati, senza aspettare che il grafo giri.

Mostra:
- Grafici attivi (timeseries prezzi, fuochi NASA, export Comex, ENSO index...)
- Segnali per area con direzione e intensità
- Freshness di ogni fonte dati

---

### Tab 2 — Alerts

Lista degli alert giornalieri in ordine cronologico inverso. Legge da `agent_runs` filtrato per `report_type: "alert"`.

Ogni card mostra: data, bullet points generati da Haiku, quali fonti erano fresche quel giorno.

---

### Tab 3 — Reports

Selettore team (Acquisti / Quality / Management) + selettore tipo (Weekly / Monthly). Legge da `agent_runs` il `report_json` corrispondente.

Renderizza:
- Sezioni narrative per area (geo, environment, crops, prices)
- **Grafici inline** — vedi sezione dedicata sotto
- Indicatori di freshness per fonte
- Monthly: bottone "Scarica PDF"

#### Grafici inline nei report

I grafici non sono immagini statiche salvate — vengono **costruiti a runtime da Streamlit** usando i dati raw in MongoDB, guidati dalle istruzioni del `chart_node`.

Il flusso è:

```
chart_node (durante il run del grafo)
     │
     ▼
state.charts = [
  {
    "chart_id":          "comex_export_volume",
    "active":            True,
    "interpretive_text": "Le esportazioni sono calate del 12% MoM..."
  },
  {
    "chart_id":          "noaa_enso_index",
    "active":            True,
    "interpretive_text": "La Niña attiva, ONI a -1.2..."
  },
  ...
]
     │
     ▼ (salvato in agent_runs insieme al report_json)

Streamlit (Tab 3, a runtime)
     │
     ▼
Per ogni chart con active: True:
  1. Legge i dati raw da MongoDB (es. raw_environment per NOAA)
  2. Costruisce il grafico con Plotly/Matplotlib
  3. Mostra il grafico + l'interpretive_text sotto
```

Questo approccio ha tre vantaggi:
- I dati dei grafici non vengono duplicati in `agent_runs` — rimangono nelle collection raw
- Se i dati raw vengono aggiornati, il grafico nel report vecchio mostra i dati aggiornati
- Haiku decide *quali* grafici attivare e *cosa scrivere* — Streamlit decide solo *come disegnarli*

I 9 grafici pre-costruiti disponibili sono fissi nel codice Streamlit. Haiku non genera codice — sceglie da questa lista e scrive il testo interpretativo.

---

### Tab 4 — Chat

L'unica superficie con LLM a runtime. L'utente fa domande in linguaggio naturale (*"come stanno andando le esportazioni di arabica?"*) e il sistema risponde grounded sui dati reali.

Flusso:
1. La domanda viene embeddato
2. Cerca in Qdrant: `crops_texts`, `geo_texts`, `reports_archive`
3. Legge i dati raw più recenti da MongoDB per la fonte rilevante
4. Passa tutto a Claude Sonnet che risponde citando le fonti

Nessun stato persistente tra una domanda e l'altra nella versione prototipo.

---

## Stack tecnologico

| Componente | Ruolo |
|---|---|
| n8n | Scheduling workflow ingestion |
| LangGraph | Orchestrazione grafo agenti |
| Claude Haiku | Sub-agenti, chart_node, alert, riscrittura monthly |
| Claude Sonnet | Report narrativo weekly/monthly |
| MongoDB 7 | Storage dati raw + agent_runs + chart_field_map |
| Qdrant | Vector store + RAG |
| Streamlit | Dashboard + alert + report viewer |
| WeasyPrint | Generazione PDF monthly |
| httpx | HTTP client async Python |
| feedparser | Parsing RSS WTO |
| pdfplumber | Estrazione testo PDF CONAB |
| pandas | Parsing XLS (CONAB, World Bank) |

---

## Struttura directory

```
lavazza-coffee-agent/
├── ingestion/
│   └── connectors/          # script Python standalone per test
├── agents/
│   ├── state.py             # AgentState TypedDict
│   ├── orchestrator.py      # grafo LangGraph
│   ├── geo_agent.py
│   ├── environment_agent.py
│   ├── crops_agent.py
│   ├── prices_agent.py
│   ├── chart_node.py
│   ├── rag_node.py
│   ├── aggregation_node.py
│   ├── report_node.py
│   └── persist_node.py
├── dashboard/
│   └── app.py               # Streamlit
├── utils/
│   ├── db.py                # MongoDB client
│   ├── qdrant.py            # Qdrant client
│   └── split_doc.py         # split_doc()
├── docker/
│   └── compose.yml
├── .env.example
└── requirements.txt
```
