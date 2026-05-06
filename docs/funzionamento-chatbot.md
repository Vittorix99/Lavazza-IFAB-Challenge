# Funzionamento Chatbot RAG

Questo documento spiega come funziona il chatbot della dashboard Lavazza Coffee Intelligence, quali componenti usa e come viene costruito il contesto passato a Claude.

Il chatbot non invia tutte le fonti disponibili al modello. La pipeline seleziona prima le aree e le fonti piu rilevanti, recupera solo il contesto necessario e applica un budget massimo di testo.

---

## Obiettivo

Il chatbot risponde a domande su Brasile, filiera caffe, prezzi, logistica, colture, clima e rischi geopolitici usando i dati gia presenti nel sistema.

Le risposte vengono costruite combinando:

- catalogo dinamico delle source in MongoDB;
- ricerca semantica su Qdrant Cloud;
- documenti raw selezionati da MongoDB Atlas;
- ultimo report agente salvato in `agent_runs`;
- sintesi finale generata da Claude.

---

## Pipeline

```text
Domanda utente
  -> embedding della domanda
  -> semantic routing su source_catalog MongoDB
  -> semantic search Qdrant sulle collection coerenti
  -> merge ranking source/area con evidenze Qdrant
  -> recupero MongoDB solo per source/aree selezionate
  -> context budget
  -> Claude
  -> risposta finale
```

I file principali sono:

| File | Ruolo |
|---|---|
| `lavazza-coffee-agent/dashboard/app.py` | Costruisce il contesto RAG e chiama Claude |
| `lavazza-coffee-agent/utils/chat_router.py` | Router semantico source/area |
| `lavazza-coffee-agent/utils/chat_router_config.py` | Macro di configurazione del router |
| `scripts/build_source_catalog.py` | Crea o aggiorna il catalogo dinamico delle source |
| `lavazza-coffee-agent/source_configs/sources.py` | Configurazioni generali delle source |
| `lavazza-coffee-agent/utils/qdrant.py` | Client Qdrant Cloud e funzioni di ricerca |

---

## 1. Embedding della domanda

Quando l'utente invia una domanda, la dashboard genera un embedding della domanda con OpenAI.

Questo embedding viene usato due volte:

- per confrontare semanticamente la domanda con il catalogo source in MongoDB;
- per cercare chunk testuali simili in Qdrant.

Se l'embedding non e disponibile, il router usa un fallback piu largo, ma sempre con budget di contesto.

---

## 2. Source catalog dinamico in MongoDB

La collection MongoDB `source_catalog` contiene una scheda sintetica per ogni source reale presente nelle raw collection.

Ogni record contiene, tra gli altri campi:

```json
{
  "source": "BCB_PTAX",
  "country": "BR",
  "area": "prices",
  "raw_collection": "raw_prices",
  "title": "Tasso di cambio BRL/USD - BCB PTAX",
  "cadence": "daily",
  "doc_count": 15,
  "latest_collected_at": "...",
  "description": "...",
  "embedding": [...]
}
```

Il catalogo viene generato dallo script:

```bash
lavazza-coffee-agent/.venv/bin/python3 scripts/build_source_catalog.py
```

Dry run senza scrivere su MongoDB:

```bash
lavazza-coffee-agent/.venv/bin/python3 scripts/build_source_catalog.py --dry-run --no-embeddings
```

Il modello embedding usato per il catalogo e configurato come macro in:

```text
lavazza-coffee-agent/utils/chat_router_config.py
```

---

## 3. Semantic routing

Il router confronta l'embedding della domanda con gli embedding delle source nel `source_catalog`.

Output principale del router:

```json
{
  "mode": "semantic_source_catalog",
  "areas": ["prices", "crops", "environment"],
  "selected_sources": ["BCB_PTAX", "WB_PINK_SHEET", "CONAB_CAFE_SAFRA"],
  "mongo_plan": {
    "raw_prices": ["BCB_PTAX", "WB_PINK_SHEET"],
    "raw_crops": ["CONAB_CAFE_SAFRA"]
  },
  "qdrant_collections": ["reports_archive", "crops_texts"],
  "context_max_chars": 14000
}
```

Questo passaggio evita di caricare tutte le raw collection nel prompt.

Le macro principali sono in `chat_router_config.py`:

```python
SOURCE_CATALOG_EMBEDDING_MODEL = "text-embedding-3-small"
CHAT_ROUTER_TOP_SOURCES = 6
CHAT_ROUTER_MIN_SOURCE_SCORE = 0.18
CHAT_ROUTER_AREA_COVERAGE_MIN_SCORE = 0.30
CHAT_ROUTER_MAX_AREAS = 3
CHAT_CONTEXT_MAX_CHARS = 14000
```

Questi valori non sono variabili d'ambiente. Sono parametri applicativi e non segreti.

---

## 4. Ruolo di Qdrant

Qdrant e usato per recuperare evidenze testuali semanticamente vicine alla domanda.

Non e il router principale delle source. Il router principale e il `source_catalog` in MongoDB.

Qdrant opera in due modalita.

### Semantic search generale

E la modalita principale.

Usa solo l'embedding della domanda e cerca i chunk testuali piu simili nelle collection Qdrant selezionate dal router.

Esempio:

```text
Domanda su raccolto e produzione
  -> router seleziona area crops
  -> Qdrant cerca in crops_texts e reports_archive
```

Non richiede che l'utente nomini una fonte specifica.

### Source-targeted search

Parte solo se la domanda nomina esplicitamente una fonte o un alias riconosciuto.

Esempi:

- "Cosa dice GDELT?"
- "Mostrami i segnali CONAB"
- "Ci sono eventi NASA FIRMS rilevanti?"

In questo caso Qdrant usa lo stesso embedding della domanda ma aggiunge un filtro payload:

```python
filters={"source": "GDELT"}
```

Questa modalita richiede che Qdrant abbia un payload index sul campo `source`.

---

## 5. Merge ranking source/area

Dopo la semantic search generale, le hit Qdrant vengono usate come evidenza aggiuntiva.

Il merge serve a:

- rinforzare aree gia selezionate dal catalogo;
- aggiungere source trovate nei payload Qdrant;
- allargare leggermente il piano MongoDB se Qdrant trova evidenze utili.

Questo non sostituisce il catalogo MongoDB: lo arricchisce.

---

## 6. Recupero selettivo da MongoDB

MongoDB contiene i dati raw aggiornati dalle ingestion n8n.

Il chatbot non legge tutte le collection e tutte le source. Usa il `mongo_plan` prodotto dal router.

Esempio:

```json
{
  "raw_prices": ["BCB_PTAX", "WB_PINK_SHEET"],
  "raw_environment": ["NOAA_ENSO"]
}
```

In questo caso il chatbot recupera solo gli ultimi documenti per quelle source.

Se il router entra in fallback, il sistema puo leggere piu collection, ma resta comunque limitato dal budget di contesto.

---

## 7. Context budget

Tutto il contesto viene aggiunto progressivamente rispettando `CHAT_CONTEXT_MAX_CHARS`.

Ordine tipico del contesto:

1. ultimo report agente da `agent_runs`;
2. chunk Qdrant da semantic search generale;
3. chunk Qdrant da source-targeted search, se attivata;
4. documenti raw MongoDB delle source selezionate.

Se il testo supera il budget, viene troncato prima di arrivare a Claude.

Questo protegge da:

- prompt troppo grandi;
- costi inutili;
- risposte confuse per eccesso di contesto;
- latenza piu alta.

---

## 8. Prompt e risposta Claude

Claude riceve:

- domanda utente;
- cronologia recente;
- contesto RAG gia selezionato;
- istruzioni di accuratezza.

Le regole principali sono:

- rispondere sempre in italiano;
- usare solo il contesto fornito;
- non inventare numeri, date o fonti;
- distinguere fatti osservati, interpretazione e confidenza;
- citare fonte e data quando disponibili;
- spiegare cosa manca se il contesto e insufficiente.

---

## Debug

La dashboard espone informazioni RAG nel pannello debug.

Le informazioni piu utili sono:

| Campo | Significato |
|---|---|
| `route.mode` | Modalita router, normalmente `semantic_source_catalog` |
| `route.areas` | Aree selezionate |
| `route.selected_sources` | Fonti scelte dal catalogo |
| `route.mongo_plan` | Piano di lettura MongoDB |
| `route.qdrant_collections` | Collection Qdrant interrogate |
| `qdrant.semantic:*` | Numero hit Qdrant per collection |
| `qdrant.source_targeted:*` | Hit filtrate per source esplicita |
| `mongodb.*.documents` | Numero snippet MongoDB aggiunti |
| `total_chars` | Dimensione finale del contesto |

---

## Comandi operativi

Ricostruire il source catalog:

```bash
lavazza-coffee-agent/.venv/bin/python3 scripts/build_source_catalog.py
```

Verificare MongoDB Atlas:

```bash
lavazza-coffee-agent/.venv/bin/python3 scripts/debug_mongo.py
```

Verificare Qdrant Cloud:

```bash
lavazza-coffee-agent/.venv/bin/python3 scripts/debug_qdrant.py
```

Avviare la dashboard:

```bash
./start.sh
```

Se Streamlit mostra import vecchi dopo un refactor, fermare e riavviare il processo:

```bash
Ctrl+C
./start.sh
```

---

## Quando aggiornare il catalogo

Ricostruire `source_catalog` quando:

- viene aggiunta una nuova source n8n;
- cambia lo schema dei documenti raw;
- cambia la descrizione o area di una fonte in `source_configs/sources.py`;
- vengono caricati nuovi dati significativi;
- il router seleziona fonti non coerenti con le domande.

---

## Riassunto

Il chatbot funziona come un RAG selettivo:

- MongoDB `source_catalog` decide quali fonti sono pertinenti;
- Qdrant recupera evidenze testuali semanticamente simili;
- MongoDB raw fornisce i dati aggiornati solo delle source selezionate;
- Claude sintetizza una risposta dettagliata, tracciabile e vincolata al contesto.

Questo disegno riduce token, latenza e rumore, mantenendo il sistema estendibile quando cambiano le fonti dati.
