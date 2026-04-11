# Regole di Ingestion — Standard per Connettori n8n

Queste regole devono essere seguite da chiunque aggiunga o modifichi un connettore n8n nel sistema Lavazza. Il rispetto di queste regole è necessario per il corretto funzionamento degli agenti LangGraph nel Layer 2.

---

## 1. Campi obbligatori in ogni documento MongoDB

Ogni documento salvato in qualsiasi collection raw deve avere esattamente questi tre campi:

```json
{
  "country": "BR",
  "macroarea": "geo | colture | prices | environment",
  "collected_at": "2026-04-08T07:03:21Z"
}
```

- `country`: sempre `"BR"` nella fase 1
- `macroarea`: uno tra `"geo"`, `"colture"`, `"prices"`, `"environment"`
- `collected_at`: ISO 8601, generato con `new Date().toISOString()` nel nodo Parse

---

## 2. Campo `_chart_fields`

Ogni documento deve dichiarare quali campi contengono array grandi (timeseries, liste di detections, serie storiche). Questo campo è letto dagli agenti per separare i dati analitici dalle serie numeriche.

```json
{
  "_chart_fields": ["recent_series", "detections_by_day"]
}
```

**Regola:** qualsiasi campo che contiene un array con più di 10 elementi deve essere elencato in `_chart_fields`.

**Campi tipicamente da includere:**
- `recent_series` (timeseries mensili o giornaliere)
- `yearly_series` (timeseries annuali)
- `detections`, `detections_by_day` (NASA FIRMS)
- `destinations_series`, `transport_series` (Comex)
- `top_ports`, `top_destinations` se array > 10 elementi

**Campi da NON includere** (array piccoli, vanno all'agente):
- `signals` (max 6 stringhe)
- `focus_states` (max 4 elementi)
- `top_destinations` se <= 10 elementi

---

## 3. Timeseries — limiti di lunghezza

Per evitare di saturare la context window degli agenti e tenere i documenti compatti:

| Tipo di dato | Lunghezza massima | Parametro da usare |
|---|---|---|
| Dati giornalieri (prezzi, cambi) | 180 giorni (6 mesi) | `lookbackDays = 180` |
| Dati mensili | 6 mesi | `lookbackMonths = 6` o `HISTORY_MONTHS = 6` |
| Dati annuali (FAOSTAT, USDA) | 6 anni | `yearly.slice(-6)` |

**Non superare mai questi limiti.** Se hai bisogno di più storico per calcoli interni (es. YoY), fallo in memoria nel nodo Parse ma non salvare la serie completa nel documento finale.

---

## 4. Struttura `ingestion_log`

Al termine di ogni run, ogni connettore deve scrivere in `ingestion_log`:

```json
{
  "source": "NOME_FONTE",
  "country": "BR",
  "run_date": "2026-04-08T07:00:00Z",
  "status": "done",
  "completed_at": "2026-04-08T07:03:21Z"
}
```

- `source`: stringa identificativa unica della fonte (es. `"COMEX_STAT"`, `"BCB_PTAX"`)
- Il nodo che scrive `ingestion_log` deve essere sempre l'ultimo del flusso

---

## 5. Nodo AI Signals (obbligatorio per ogni connettore)

Ogni connettore deve avere un nodo AI (`chainLlm`) che produce almeno:

```json
{
  "movement_label": "...",
  "risk_level": "low|medium|high",
  "signals": ["stringa 1", "stringa 2"],
  "summary_en": "1-2 frasi in inglese"
}
```

Il nodo `Parse Signals` successivo deve fondere l'output AI con il documento base, mantenendo i segnali rule-based come fallback:

```javascript
const parsed = JSON.parse(cleaned);
const base = $('SOURCE Parse Node').item.json;

return [{
  json: {
    ...base,
    rule_based_signals: base.signals,
    rule_based_movement_label: base.movement_label,
    movement_label: parsed.movement_label || base.movement_label || 'mixed',
    risk_level: parsed.risk_level || base.risk_level || 'low',
    signals: parsed.signals?.length ? parsed.signals : base.signals,
    summary_en: parsed.summary_en || base.summary_en || ''
  }
}];
```

**Regola:** il documento che arriva su MongoDB deve sempre avere `signals`, `movement_label`, `risk_level`, `summary_en` — anche se l'AI fallisce (usa i fallback rule-based).

---

## 6. Qdrant — quando usarlo

Salvare embedding in Qdrant **solo** per documenti che contengono testo narrativo significativo:

| Collection | Quando usarla |
|---|---|
| `geo_texts` | news GDELT, articoli WTO RSS, alert geopolitici |
| `crops_texts` | estratti PDF CONAB, analisi qualitative produzione |
| `reports_archive` | report narrativi generati dagli agenti (Layer 2) |

**Non usare Qdrant** per dati puramente numerici (BCB, ECB, World Bank, NASA, NOAA, USDA, IBGE, Comex, FAOSTAT). Questi vengono letti direttamente da MongoDB dagli agenti.

---

## 7. Testo per embedding Qdrant

Il testo inviato a OpenAI Embeddings deve combinare:

```javascript
const embedText = [
  parsed.summary_en || '',
  ...(parsed.signals || []),
  textExcerpt.slice(0, 2000)   // estratto testo narrativo (PDF, articolo, ecc.)
].filter(Boolean).join(' ');
```

Limite massimo testo embedding: **4000 caratteri** (per stare nei limiti del modello e mantenere il vettore semanticamente denso).

---

## 8. Collection MongoDB per macroarea

| Macroarea | Collection |
|---|---|
| `geo` | `raw_geo` |
| `colture` | `raw_crops` |
| `prices` | `raw_prices` |
| `environment` | `raw_environment` |

---

## 9. Campi `source` e formato nomi

Il campo `source` deve essere in `SNAKE_CASE_MAIUSCOLO`:

| Connettore | source |
|---|---|
| GDELT | `GDELT` |
| WTO RSS | `WTO_RSS` |
| CONAB | `CONAB` |
| USDA FAS PSD | `USDA_PSD` |
| IBGE SIDRA | `IBGE_SIDRA` |
| Comex Stat | `COMEX_STAT` |
| World Bank | `WB_PINK_SHEET` |
| BCB PTAX | `BCB_PTAX` |
| ECB Data Portal | `ECB_DATA_PORTAL` |
| NASA FIRMS | `NASA_FIRMS` |
| NOAA ENSO | `NOAA_ENSO` |
| FAOSTAT QCL | `FAOSTAT_QCL` |

---

## 10. Checklist per nuovo connettore

Prima di considerare completo un nuovo connettore, verificare:

- [ ] Il documento ha `country`, `macroarea`, `collected_at`
- [ ] Il documento ha `_chart_fields` con tutti gli array grandi
- [ ] Le timeseries rispettano i limiti di lunghezza (6 mesi / 6 anni)
- [ ] C'è un nodo `AI Signals` (chainLlm) con prompt appropriato
- [ ] C'è un nodo `Parse Signals` che fonde AI output + fallback rule-based
- [ ] Il documento finale ha `signals`, `movement_label`, `risk_level`, `summary_en`
- [ ] L'ultimo nodo scrive in `ingestion_log`
- [ ] Se il connettore produce testo narrativo: embedding in Qdrant
- [ ] Se il connettore produce solo numeri: solo MongoDB, no Qdrant
