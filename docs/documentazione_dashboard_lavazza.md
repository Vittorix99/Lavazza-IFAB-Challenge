# Documentazione Tecnica — Dashboard Intelligence Filiera Caffè
## Lavazza Brazil Origins Intelligence · Aprile 2026

---

> **A chi è rivolto questo documento**
>
> Il documento è strutturato per tre tipologie di lettore simultanee:
> - 🏢 **Business & Management**: valore strategico di ogni dato, senza tecnicismi.
> - 📊 **Analisti & Data Analyst**: struttura dei dati, metriche, logica interpretativa.
> - 🛠️ **Data Scientists & Sviluppatori**: API, formati, limiti tecnici, opportunità di evoluzione.

---

## 🚀 COME AVVIARE LA DASHBOARD

### Prerequisiti

| Requisito | Versione minima |
|-----------|----------------|
| Python | ≥ 3.10 |
| Streamlit | ≥ 1.32 |
| pip | ≥ 23 |

```bash
# Installa tutte le dipendenze
pip install -r requirements.txt
pip install geopandas websockets faostat openpyxl yfinance
```

### Variabili d'ambiente (opzionali ma consigliate)

```bash
export USDA_API_KEY="la-tua-chiave-usda"
export FAOSTAT_USERNAME="email@esempio.com"
export FAOSTAT_PASSWORD="password"
```

> Senza queste variabili la dashboard funziona ugualmente in modalità **Dati Simulati**.

### Avvio

```bash
# 1. Aggiorna i dati CONAB (una volta, o prima di ogni presentazione)
python3 fetch_conab.py

# 2. Avvia la dashboard
streamlit run app_standalone.py
```

Streamlit apre automaticamente il browser su `http://localhost:8501`.

---

## PARTE 1 — PANORAMICA DELLA DASHBOARD

### Cos'è e a cosa serve

La dashboard è un sistema centralizzato di **monitoraggio e visualizzazione Intelligence** che aggrega dati da 8 fonti globali — climatiche, agronomiche, logistiche e finanziarie — per fornire a Lavazza una visione integrata della filiera del caffè brasiliano.

Il Brasile è il **primo produttore mondiale di caffè**, responsabile del 35–40% dell'intera produzione globale. Monitorare clima, produzione, logistica portuale e mercati cambi in Brasile significa avere visibilità anticipata sui rischi che impattano direttamente i **costi di approvvigionamento** e la **disponibilità di materia prima**.

### Filosofia della dashboard

La dashboard è uno strumento di **esplorazione dati puri**, non di previsione. Non contiene modelli predittivi né raccomandazioni automatiche. Il valore sta nel permettere a buyer, agronomi e logistici di vedere tutto in un unico posto e identificare correlazioni rilevanti in modo autonomo e informato.

### Le 6 Schede Tematiche

| Scheda | Tema | Fonte principale |
|--------|------|-----------------|
| 🌦️ Clima & ENSO | Fenomeni climatici globali | NOAA |
| 🔥 Incendi | Focolai satellitari attivi in Brasile | NASA FIRMS |
| ⚓ Navi & Porti | Traffico + congestione porti export | AISStream.io + modello |
| 📈 Prezzi di Mercato | Prezzi commodity e tassi di cambio | World Bank + yfinance |
| 🌾 Produttività | Produzione, resa e stock per anno | USDA PSD / FAOSTAT / CONAB |
| 🌧️ Precipitazioni | Deficit pluviometrico per stato | NOAA (modellato) |

---

## PARTE 2 — LE FONTI DATI

### 2.1 NOAA — ONI e SOI (Indici ENSO)

**Chi è NOAA**: L'agenzia governativa americana che gestisce il monitoraggio oceanico e atmosferico globale. I suoi dati sono il gold standard internazionale per la climatologia.

| Parametro | Dettaglio |
|-----------|-----------|
| Endpoint ONI | `https://psl.noaa.gov/data/correlation/oni.data` |
| Endpoint SOI | `https://psl.noaa.gov/data/correlation/soi.data` |
| Formato | File di testo a larghezza fissa. Il valore `-99.90` indica mesi non ancora registrati (filtrato automaticamente). |
| Cache | 24 ore |
| Autenticazione | Nessuna |
| Storico | Dal 1950 ad oggi |

---

### 2.2 NASA FIRMS — Incendi Attivi

| Parametro | Dettaglio |
|-----------|-----------|
| Endpoint | `https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/VIIRS_SNPP_NRT/{BBOX}/{DAYS}` |
| Bbox Brasile | `-75,-35,-33,6` |
| Output | CSV: `latitude`, `longitude`, `frp` (Fire Radiative Power, MW) |
| Latenza | ~3 ore dopo il passaggio del satellite |
| Cache | 1 ora |

---

### 2.3 AISStream.io — Traffico Marittimo Live

| Parametro | Dettaglio |
|-----------|-----------|
| Protocollo | WebSocket (`wss://stream.aisstream.io/v0/stream`) |
| Messaggi | `PositionReport` (posizione + SOG) e `ShipStaticData` (tipo nave) |
| Filtro tipo | Cargo AIS 70–89. Codici sconosciuti (0) inclusi per prudenza. |
| Limitazione tier gratuito | Copertura concentrata su Asia, Nord Europa, West Coast USA. I porti brasiliani usano stime modellistiche. |

---

### 2.4 World Bank Commodity Prices — "Pink Sheet"

| Parametro | Dettaglio |
|-----------|-----------|
| Formato | File Excel .xlsx scaricato direttamente |
| Dati | Prezzi mensili ICE Arabica (USD/kg, New York) e Robusta (USD/kg, Londra) |
| Storico | Dal 1960 |
| Cache | 1 ora |

---

### 2.5 yfinance — Tassi di Cambio Storici EURBRL=X

La dashboard usa la libreria `yfinance` (Yahoo Finance) per scaricare la **serie storica mensile del cambio EUR/BRL** (ticker `EURBRL=X`), coprendo gli ultimi 12 anni.

**Perché yfinance invece di ER-API per i prezzi storici**: ER-API fornisce solo il tasso di cambio *corrente* (istantaneo). Applicare un singolo tasso fisso a 10 anni di prezzi storici invalida qualsiasi analisi comparativa, perché la serie `arabica_brl_kg` diventerebbe un multiplo costante di `arabica_eur_kg` — le due linee normalizzate si sovrapporrebbero perfettamente e lo Z-score avrebbe deviazione standard zero (barre NaN). yfinance restituisce invece la serie mensile storica effettiva, che viene unita alla serie prezzi tramite `pd.merge_asof` con tolleranza di 45 giorni.

```python
yf.download("EURBRL=X", period="12y", interval="1mo", auto_adjust=True)
```

---

### 2.6 USDA PSD — Production, Supply and Distribution

| Parametro | Dettaglio |
|-----------|-----------|
| Endpoint | `https://api.fas.usda.gov/api/psd/commodity/0711100/country/BR/year/{anno}` |
| Commodity | `0711100` = Coffee, Green |
| Paese | `BR` = Brasile |
| Autenticazione | Header `X-Api-Key` |
| Unità originale | 1.000 Metric Ton → conversione: × 1000 × 16,667 sacchi 60 kg |
| Marketing Year | Aprile–Marzo |

---

### 2.7 FAOSTAT — Dataset QCL

| Parametro | Dettaglio |
|-----------|-----------|
| Dataset | QCL (Crops and Livestock Products) |
| Area | `21` (Brasile) |
| Item | `656` (Coffee, green) |
| Elementi estratti | `2312` Area harvested (ha), `2413` Yield (hg/ha), `2510` Production (t) |
| Accesso | Libreria Python `faostat` con credenziali via variabili d'ambiente |
| Storico | Dal 1990 ad oggi, aggiornamento annuale (ritardo ~1-2 anni) |

---

### 2.8 CONAB — Excel pre-scaricato

**Script dedicato**: `fetch_conab.py` scarica e parsa l'ultimo "Levantamento de Café" dal sito `gov.br/conab`.
**Output**: `data_sources/conab/conab_data.csv` con produzione e resa per stato.
**Frequenza update CONAB**: 5–6 volte l'anno. Non esiste un'API ufficiale CONAB — il parsing è basato su scraping BeautifulSoup.

---

### 2.9 GeoJSON — Confini Stati Brasiliani

**Fonte**: GitHub `click_that_hood`. Usato da GeoPandas per join spaziale focolai NASA → stati brasiliani, e per le mappe coropletiche Matplotlib.

---

## PARTE 3 — I GRAFICI: GUIDA COMPLETA TAB PER TAB

---

## 🌦️ SCHEDA 1: CLIMA & ENSO

### 3.1 — Pannello KPI: ONI, SOI, Fase ENSO, Impatto Agronomico

Il pannello superiore mostra quattro metriche istantanee:

| KPI | Descrizione |
|-----|-------------|
| **ONI (°C)** | Ultimo valore mensile dell'indice oceanico, con delta rispetto al mese precedente. |
| **SOI** | Ultimo valore dell'indice atmosferico, con delta. |
| **Fase ENSO** | 🔴 El Niño / 🔵 La Niña / 🟢 Neutrale + flag ⚠️ se evento accoppiato. |
| **Impatto Agronomico** | Testo descrittivo del rischio atteso per le colture brasiliane. |

**Logica di classificazione** (soglie WMO standard):
- ONI ≥ +0.5°C → **El Niño**
- ONI ≤ −0.5°C → **La Niña**
- SOI ≤ −7 con ONI ≥ +0.5 → ⚠️ **evento El Niño accoppiato** — impatto severo quasi certo

---

### 3.2 — Grafico: Indice ONI con Aree di Fase (Ultimi 36 Mesi) ⭐

**Tipo**: Linea temporale con aree fillate.

**Cosa contiene**:
- Linea nera: valore ONI mensile
- Area rossa: mesi con ONI > +0.5 (El Niño attivo)
- Area blu: mesi con ONI < −0.5 (La Niña attiva)
- Linee tratteggiate: soglie +0.5 e −0.5

**Cos'è l'ONI e perché è fondamentale per il caffè**:

L'Oceanic Niño Index misura l'**anomalia termica della superficie marina** (SST, Sea Surface Temperature) nella regione Niño 3.4 del Pacifico Equatoriale Centrale (5°N–5°S, 170°W–120°W), calcolata come media mobile trimestrale rispetto alla baseline 1991–2020.

Il Pacifico Equatoriale funge da **pompa di calore** che guida i sistemi di circolazione atmosferica globale (circolazione di Walker). Quando la SST sale (El Niño), il motore della circolazione rallenta: le masse d'aria umida che normalmente salgono sull'Amazzonia perdono forza, causando siccità nel Centro-Ovest e Nord del Brasile. Quando la SST scende (La Niña), il motore si accelera: eccesso di piogge in Amazzonia, siccità nel Sud.

**Perché è un indicatore anticipatorio**: L'ONI viene misurato mesi prima che l'effetto si manifesti sul raccolto. Un El Niño dichiarato a Giugno significa siccità durante la fioritura del caffè (Settembre–Novembre) con certezza statistica elevata — il mercato spesso non prezza ancora completamente questo rischio. I buyer che monitorano l'ONI possono anticipare coperture o bloccare forniture prima che i prezzi reagiscano.

---

### 3.3 — Grafico: Indice SOI (Ultimi 36 Mesi) ⭐

**Tipo**: Istogramma bicolore mensile.

**Cosa contiene**:
- Barre blu: SOI positivo (pressione alta a Tahiti → venti alisei forti → La Niña)
- Barre rosse: SOI negativo (pressione bassa a Tahiti → El Niño)
- Soglie: +7 (La Niña confermata) e −7 (El Niño confermato)

**Cos'è il SOI e in cosa si differenzia dall'ONI**:

Il Southern Oscillation Index misura la **differenza di pressione atmosferica standardizzata** tra Tahiti e Darwin, Australia. È la componente *atmosferica* dell'ENSO, mentre l'ONI è quella *oceanica*.

L'importanza di avere entrambi: oceano e atmosfera non sempre si sincronizzano immediatamente. L'ONI può essere oltre +0.5°C (mare caldo → El Niño potenziale) mentre il SOI è ancora vicino allo zero (l'atmosfera non ha ancora "reagito"). In questo caso l'evento è debole o in sviluppo. Quando invece ONI e SOI concordano entrambi oltre le rispettive soglie — el oceano si scalda *e* l'atmosfera risponde con pressione bassa a Tahiti — l'evento è "accoppiato" ed è responsabile storicamente dei peggiori impatti agricoli in Brasile.

**Regola pratica per la lettura combinata**:

| ONI | SOI | Interpretazione |
|-----|-----|----------------|
| > +0.5 | < −7 | El Niño accoppiato — siccità Cerrado quasi certa → alta allerta |
| > +0.5 | tra −7 e 0 | El Niño oceanico in sviluppo — monitorare |
| < −0.5 | > +7 | La Niña accoppiata — piogge eccessive Sud Brasile → rischio malattie fungine |
| tra −0.5 e +0.5 | tra −7 e +7 | Fase neutra — nessun impatto ENSO significativo atteso |

---

### 3.4 — Grafico: Heatmap ONI Storica (10 Anni, Mese × Anno)

**Tipo**: Mappa di calore.

**Cosa mostra**: Il valore ONI per ogni mese (righe: Gennaio–Dicembre) per ogni anno degli ultimi 10 (colonne). Scala divergente: rosso intenso = El Niño forte, blu intenso = La Niña forte, bianco = neutro.

**Perché è utile**: Permette di identificare immediatamente **durata e stagionalità** degli eventi ENSO. Un blocco rosso esteso da Giugno a Dicembre dello stesso anno è molto più preoccupante di un valore rosso isolato. I blocchi blu prolungati su Ottobre–Novembre indicano La Niña durante la fioritura — storicamente associata a siccità nel Cerrado e Minas Gerais.

---

## 🔥 SCHEDA 2: INCENDI

### 3.5 — Mappa: Arabica & Robusta con Focolai NASA (Matplotlib)

**Tipo**: Doppia mappa coropletica + scatter geografico su mappa statica.

**Mappa sinistra (Arabica)**:
- Colorazione stati: gradiente verde proporzionale alla produzione Arabica (sacchi/60kg, dati COFFEE_STATE_PROD).
- Punti **grigi** (FRP ≤ 50 MW): incendi minori — fuochi agricoli controllati, sterpaglie. Rumore di fondo.
- Punti **colorati scala `hot`** (FRP > 50 MW): incendi significativi, dimensionati ∝ √FRP × 3.

**Mappa destra (Robusta)**: Identica logica, gradiente viola per la produzione Robusta.

**Perché FRP e non solo conteggio focolai**: Il *Fire Radiative Power* (potenza radiativa, in Megawatt) è molto più informativa del semplice conteggio. Un fuoco agricolo controllato vale 5 MW; un incendio foresta-savana può superare 500 MW. Il FRP è proporzionale alla massa vegetale bruciata e quindi al danno potenziale sulle colture limitrofe e al particolato emesso.

**Come leggere la sovrapposizione**: Un punto rosso/arancio (FRP alto) su area verde intensa (alta produzione Arabica) — tipicamente nel sud di Minas Gerais — è il segnale di massima allerta. Anche senza che il fuoco raggiunga direttamente le piante, il particolato riduce la fotosintesi per settimane e altera il microclima locale, riducendo la qualità del chicco nella cernita definitiva.

---

### 3.6 — Grafico: Conteggio Mensile Incendi (Ultimi 24 Mesi)

**Tipo**: Linea con marcatori, colore rosso.

**Come leggerlo**: I picchi si verificano fisiologicamente tra **Agosto e Ottobre** (stagione secca del Cerrado). Un picco anomalo fuori da questa finestra è un segnale di allarme — siccità atipica o cambio nelle pratiche di disboscamento. Confrontare con l'ONI: anni di El Niño mostrano picchi sehr molto superiori alla media già da Giugno–Luglio.

---

### 3.7 — Grafico: Focolai per Macro-Regione

**Tipo**: Barre verticali per macro-regione geografica.

**Come leggerlo**: Il Centro-Ovest (Cerrado) e il Nord (Amazzonia) dominano strutturalmente per volume. Se il **Sud-Est** (Minas Gerais, Espírito Santo) mostra un incremento anomalo, le aree core dell'Arabica brasiliana sono direttamente sotto pressione — segnale di mercato di massima rilevanza per i buyer.

---

## ⚓ SCHEDA 3: NAVI & PORTI

### 3.8 — Pannello: Diagnostica AIS Live (6 KPI)

| KPI | Significato |
|-----|-------------|
| Stato WS | Connesso/Simulato/Fallito |
| Messaggi Ricevuti | Totale messaggi raw dal WebSocket nella finestra di ascolto |
| Report Posizione | Messaggi PositionReport ricevuti |
| Msg Dati Statici | Messaggi ShipStaticData (tipo nave, nome) |
| Nel Bbox (grezzo) | Position report che ricadono nelle bounding box monitorate |
| Tracciati Finali | Navi registrate dopo filtro tipo cargo (AIS 70–89) |

**Nota**: Il tier gratuito AISStream non ha copertura affidabile nei porti brasiliani. La demo live usa Singapore, Rotterdam e Los Angeles. Con feed AIS premium, lo stesso codice funzionerebbe su Santos e Vitória.

---

### 3.9 — Grafico: Tendenze Ritardo Porto — Ultimi 12 Mesi

**Tipo**: Grafico a linee multi-serie (una linea per porto).

**Modello di stima**: Il ritardo stimato (giorni) combina deficit pluviometrico (45%), pressione incendi (20%), e throughput storico di base (35%). Un ritardo crescente a Santos — che gestisce ~60% dell'export caffè brasiliano — è il segnale per anticipare forniture o diversificare i percorsi.

---

### 3.10 — Mappa: Rischio Porto Attuale

**Tipo**: Scatter map interattiva (Plotly + Mapbox Carto-Positron).

**Lettura**: Punti dimensionati per ritardo stimato, colorati per rischio (🟢 Basso / 🟠 Medio / 🔴 Alto). Mouse-over per valori esatti.

---

## 📈 SCHEDA 4: PREZZI DI MERCATO

### 3.11 — KPI: Tasso di Cambio BRL/EUR Attuale

**Tipo**: `st.metric` singolo.

**Cosa mostra**: Il valore più recente di EUR/BRL dalla serie yfinance — quanti Real brasiliani equivalgono a 1 Euro. È il termometro istantaneo del vantaggio di acquisto per il buyer europeo.

---

### 3.12 — Grafico: Prezzi Arabica & Robusta in EUR/kg (Storico 10 anni)

**Tipo**: Doppio asse Y — Arabica (asse sinistro, marrone) + Robusta (asse destro, arancio scuro).

**Come leggerlo**: Le due serie tendono a muoversi in parallelo ma il **differenziale** tra esse è la metrica chiave per il compratore (analizzata nel grafico successivo). In periodi di stress climatico brasiliano (El Niño, siccità), l'Arabica tende a salire proporzionalmente più della Robusta, ampliando lo spread.

---

### 3.13 — Grafico: Spread Arabica vs Robusta con Media Mobile a 3 Mesi ⭐

**Tipo**: Barre mensili (differenziale assoluto EUR/kg) + linea rossa (media mobile 3 mesi).

**Cos'è lo spread nel contesto delle materie prime**:

Lo spread (differenziale di prezzo) tra due commodity correlate è una delle metriche più usate nel trading di materie prime perché cattura la *relazione strutturale* tra due prodotti, eliminando il rumore del movimento comune del mercato.

Nel caffè, lo spread Arabica−Robusta misura **quanto il mercato premia la qualità Arabica rispetto alla varietà più economica**:

> Spread(t) = Prezzo_Arabica_EUR/kg(t) − Prezzo_Robusta_EUR/kg(t)

La linea rossa (media mobile 3 mesi) mostra il *momentum* strutturale, livellando la volatilità mensile.

**I 4 scenari interpretativi**:

| Scenario | Segnale | Implicazione per Lavazza |
|----------|---------|--------------------------|
| Spread in forte crescita | Il mercato paga un premio crescente per l'Arabica — scarsità o domanda premium | Pressione sui costi; considerare contratti forward o copertura |
| Spread in forte calo | Arabica abbondante, o mercato accetta Robusta come sostituto | Opportunità di acquisto Arabica a prezzi relativamente convenienti |
| Spread sopra media storica + El Niño attivo | Scarsità stagionale confermata | Probabile persistenza del differenziale — agire rapidamente |
| Spread sotto media storica | Abbondanza relativa Arabica | Rivalutare il mix Arabica/Robusta nei blend per ottimizzare i costi |

**Perché la media mobile a 3 mesi**: Il mercato del caffè ha alta volatilità mensile (speculazione, report USDA, gelate occasionali). La media mobile a 3 mesi livella i picchi transitori e mostra il *momentum strutturale*, rilevante per decisioni di acquisto di lungo periodo.

---

### 3.14 — Grafico: Prezzo Arabica BRL/kg vs EUR/kg — Analisi Opportunità d'Acquisto ⭐⭐

**Tipo**: Due subplot sovrapposti con asse X condiviso.

Questo è il grafico più elaborato della dashboard, progettato specificamente per il **buyer europeo** che vuole identificare i momenti più favorevoli all'acquisto.

---

#### Subplot superiore — Prezzi Normalizzati Base 100

Entrambe le serie `arabica_brl_kg` e `arabica_eur_kg` vengono normalizzate a **indice Base 100** dalla prima data disponibile:

```
BRL_idx(t) = arabica_brl_kg(t) / arabica_brl_kg(t=0) × 100
EUR_idx(t) = arabica_eur_kg(t) / arabica_eur_kg(t=0) × 100
```

**Perché normalizzare a Base 100**: Le due serie hanno unità diverse (Real brasiliani e Euro) e scale numeriche diverse. Riportarle entrambe a 100 alla data iniziale le mette sulla **stessa scala di crescita relativa**, permettendo di confrontare non i valori assoluti (inutile confrontarli direttamente) ma il *momentum* di ciascuna — quanto è salita o scesa rispetto al punto di partenza.

**Il riempimento colorato tra le linee**:

Il riempimento è calcolato segmento per segmento (un segmento = un mese):

- 🟢 **Verde** quando `EUR_idx < BRL_idx`: il produttore brasiliano ha visto il suo prezzo in Real crescere *più* velocemente di quanto il prezzo in Euro sia salito per il compratore europeo. Questo è il **vantaggio valutario del buyer europeo**: ogni euro speso compra relativamente più caffè rispetto alla baseline.
- 🔴 **Rosso** quando `EUR_idx > BRL_idx`: il prezzo in Euro è salito più velocemente di quello in Real — il buyer europeo paga di più in termini relativi.

Il colore verde non significa che i prezzi assoluti siano bassi — significa che il *rapporto di cambio effettivo* è favorevole al compratore europeo in quel momento specifico rispetto alla sua posizione storica.

---

#### Subplot inferiore — Z-Score Rolling 12 Mesi del Cambio BRL/EUR ⭐⭐

**Tipo**: Grafico a barre con colorazione condizionale (🟢 verde se Z > +1σ, ⬜ grigio altrimenti).

**Cos'è lo Z-score**:

Lo Z-score è una misura statistica standardizzata che esprime **di quante deviazioni standard un valore si discosta dalla media corrente**:

> Z(t) = ( FX(t) − Media_12m(t) ) / DevStd_12m(t)

dove tutti i termini sono calcolati su una finestra mobile degli ultimi 12 mesi. Questo rende lo Z-score **adattivo**: confronta ciascun mese non con la media storica totale (che potrebbe essere obsoleta dopo anni di cambio di regime valutario), ma con il suo *recente contesto* degli ultimi 12 mesi.

**Perché "rolling 12 mesi" e non la media storica totale**: Se il BRL si svaluta strutturalmente nel corso di anni, uno Z-score sulla media storica sovrastimarebbe sistematicamente la "forza" dell'euro. La finestra rolling adattiva identifica invece la forza o debolezza *relativa al regime corrente*, che è la misura operativamente significativa per il buyer.

**Come leggere i colori**:

| Colore | Condizione | Significato economico |
|--------|------------|----------------------|
| 🟢 **Verde** | Z > +1σ | L'euro è almeno 1 deviazione standard **più forte** rispetto alla sua media recente. Questo accade statisticamente in ~16% dei mesi (circa 2 mesi l'anno). È una finestra **rara e favorevole**: il buyer europeo acquista Real a tassi eccezionalmente convenienti. |
| ⬜ **Grigio** | −1σ ≤ Z ≤ +1σ | Situazione nella norma. Nessun segnale specifico. |
| (nessun colore speciale) | Z < −1σ | L'euro è debole: il buyer europeo paga di più in termini relativi — evitare acquisti spot non urgenti. |

**Le tre linee di riferimento**:
- Linea verde tratteggiata a **+1σ**: soglia di "euro forte" — momento favorevole
- Linea grigia punteggiata a **0**: media rolling — cambio nella norma
- Linea rossa tratteggiata a **−1σ**: soglia di "euro debole"

**Il segnale combinato ottimale**: Le finestre in cui *contemporaneamente* il pannello superiore è **verde** (EUR relativa al BRL in vantaggio) E il pannello inferiore ha barre **verdi** (Z > +1σ) sono i momenti storicamente ottimali per acquistare caffè brasiliano in euro — si ha sia il vantaggio del prezzo relativo sia il vantaggio valutario sullo storico recente.

---

### 3.15 — Grafico: Prezzo Medio Annuo Arabica vs Media Decennale

**Tipo**: Barre per anno + linea tratteggiata (media decennale).

**Come leggerlo**: Gli anni con barre significativamente sopra la media sono quasi sempre associati a eventi climatici estremi: gelate brasiliane, siccità El Niño, o shock geopolitici di offerta. Sovrapporre mentalmente questo grafico con la heatmap ONI costruisce la narrativa causale che spiega le variazioni di budget di acquisto.

---

## 🌾 SCHEDA 5: PRODUTTIVITÀ DELLE COLTURE

### 3.16 — Grafico: FAOSTAT — Produzione e Area Raccolta (1990–Presente) ⭐

**Tipo**: Doppio asse — barre marroni (produzione in tonnellate, asse sinistro) + linea verde (superficie raccolta in ettari, asse destro).

**Fonte esatta**: Dataset FAOSTAT QCL — Brasile (area=`21`), Caffè verde (item=`656`), elementi:
- `2510` → Production (tonnellate) → **barre**
- `2312` → Area harvested (ettari) → **linea**

**Come leggere le relazioni tra barre e linea**:

- Se le barre crescono **più velocemente** della linea → la resa per ettaro sta aumentando (guadagni di efficienza agronomica).
- Se le barre e la linea crescono **proporzionalmente** → l'aumento di produzione è interamente dovuto all'espansione dell'area coltivata, non all'intensificazione.
- Se le barre **calano** mentre la linea è stabile → la resa è diminuita (siccità, malattie, anno off).

**Il ciclo biennale (anni on/off) — spiegazione dettagliata**:

La caratteristica più evidente del grafico è l'oscillazione regolare della produzione tra anni alterni. Questo riflette il **ciclo biologico naturale della pianta Coffea arabica**:

> Un anno di produzione intensa (anno "on") esa le riserve di carboidrati della pianta. Le gemme fiorali già formate durante l'anno on hanno richiesto un investimento energetico enorme. L'anno successivo (anno "off"), la pianta riduce la carica fruttificante spontaneamente per recuperare. L'anno seguente torna all'alta produzione.

Nelle barre del grafico, questo ciclo appare come oscillazione quasi perfetta: anno alto → anno basso → anno alto... La superficie raccolta (linea) non oscilla — è stabile o in crescita lenta — mentre la produzione (barre) oscilla. Ciò conferma che l'oscillazione è biologica (resa per pianta), non strutturale (area coltivata).

**Implicazioni per la pianificazione degli acquisti**:

Il ciclo biennale è *parzialmente prevedibile*. Se l'anno corrente è un "anno on" (produzione alta, prezzi tendenzialmente più bassi), il prossimo sarà probabilmente un "anno off" (produzione più contenuta, pressione rialzista sui prezzi). Questo fornisce una base per la pianificazione degli acquisti a 12–18 mesi di orizzonte.

**Perché la FAO e non solo USDA**: FAOSTAT offre dati **dal 1990 ad oggi** — 30+ anni — permettendo di vedere cambiamenti strutturali decennali (conversione del Cerrado in terra agricola) che i 15-20 anni di USDA non catturano.

---

### 3.17 — Grafico: Produzione Totale Arabica + Robusta per Anno (USDA PSD)

**Tipo**: Barre impilate per anno.

**Come leggerlo**: Il ciclo biennale è evidente come oscillazione delle barre totali. La quota Robusta (arancio) è cresciuta strutturalmente grazie alla sua maggiore resistenza alla siccità, alla meccanizzazione più facile in pianura e alla domanda crescente per miscele espresso. Un trend di crescita della quota Robusta può indicare una pressione futura sulla disponibilità di Arabica di qualità.

---

### 3.18 — Grafico: Volumi Annui Esportazioni vs Scorte Finali ⭐⭐

**Tipo**: Doppia linea su doppio asse Y — Export (verde, asse sinistro) + Ending Stocks (blu tratteggiato, asse destro). Entrambe in sacchi da 60 kg, con notazione abbreviata (.2s).

**Il concetto chiave: lo "squeeze" dell'offerta**

Le due serie raccontano insieme la **storia della disponibilità fisica di caffè brasiliano sul mercato**. Leggere una sola delle due è insufficiente — è la relazione dinamica tra export e scorte che porta il segnale.

**I 4 scenari fondamentali**:

| Scenario | Export | Scorte | Segnale | Azione buyer |
|----------|--------|--------|---------|-------------|
| **Squeeze** | ↑ crescono | ↓ calano | Tightening dell'offerta — precursore rialzo prezzi 6-12 mesi | Anticipare acquisti, valutare contratti a termine |
| **Abbondanza** | ↑ crescono | ↑ crescono | Produzione molto abbondante (anno on), pressione ribassista | Momento favorevole per acquisti spot |
| **Stress produttivo** | ↓ calano | ↓ calano | Produzione bassa (anno off o siccità) — scorte si erodono anche con meno esportazioni | Monitorare — rischio rialzo anche senza boom export |
| **Ritenzione** | ↓ calano | ↑ crescono | Il Brasile trattiene il caffè (cambio sfavorevole o domanda interna alta) | Segnale misto — attendere chiarimento |

**Il "crossover" come segnale tecnico**: Il momento in cui la linea delle scorte scende *sotto* la traiettoria delle esportazioni è storicamente uno dei segnali più affidabili di squeeze imminente. I traders di commodity lo chiamano "drawdown da scorte" — ed è quasi invariabilmente seguito da movimenti rialzisti sul futures ICE Arabica di New York entro 3–6 mesi.

---

### 3.19 — Grafico: Efficienza Resa vs Volume Produzione — Top 10 Regioni ⭐

**Tipo**: Bubble scatter chart.

| Dimensione visiva | Dato |
|-------------------|------|
| **Asse X** | Resa media (sacchi 60 kg / ettaro) — efficienza agronomica |
| **Asse Y** | Produzione totale annua (sacchi 60 kg) — volume assoluto |
| **Dimensione bolla** | Proporzionale alla produzione totale |
| **Etichetta sulla bolla** | Sigla dello stato (es. "MG") — compatta, leggibile |
| **Mouse-over** | Nome completo + regione geografica (es. "MG — Minas Gerais (Sud-Est)") |

**La lettura per quadranti**:

```
Volume Produzione (Y)
        │
   Alto │ [Grandi estensivi]  │  [Campioni: MG]
        │                     │
        │─────────────────────│──────── Resa (X)
        │                     │
  Basso │ [Marginali]         │  [Piccoli intensivi: ES, SP]
        │
```

| Quadrante | Tipo stato | Esempio |
|-----------|------------|---------|
| Alto-destra | Alta produzione + Alta resa — campioni di efficienza | MG (Arabica), ES (Robusta) |
| Alto-sinistra | Grandi produttori estensivi — area enorme, poca intensificazione | — |
| Basso-destra | Piccoli produttori ad alta tecnologia | SP, PR |
| Basso-sinistra | Zone marginali | GO, MT, BA |

**Lettura per i principali stati**:
- **MG (Minas Gerais)**: Bolla più grande. Domina per volume assoluto di Arabica. Qualsiasi evento climatico qui impatta il mercato globale.
- **ES (Espírito Santo)**: Alta resa per Robusta (Conilon) con tecniche intensive. Bolla media ma resa elevata.
- **RO (Rondônia)**: Alta resa relativa di Robusta in zona amazzonica, volume contenuto.
- **SP (São Paulo)**: Alta resa, volume medio — piantagioni meccanizzate nel Mogiana e Alta Paulista.

**Perché questa visualizzazione è utile per i buyer**: Gli stati con alta resa e alto volume sono i più competitivi economicamente e resilienti a shock di superficie (pressione della soia, urbanizzazione). Gli stati con bassa resa sono più vulnerabili a pressioni di costo e a shock climatici.

---

### 3.20 — Grafico: Quota di Mercato Arabica / Robusta (Donut)

**Tipo**: Donut chart per l'anno più recente.

**Come leggerlo**: Il Brasile è storicamente 70–75% Arabica. Un trend verso la parità indica un cambiamento strutturale profondo — con implicazioni per la disponibilità futura di Arabica di qualità e per i costi delle miscele. Da leggere in combinazione con il trend pluriennale delle barre impilate (3.17).

---

## 🌧️ SCHEDA 6: PRECIPITAZIONI

### 3.21 — Guida: Cos'è il Deficit Pluviometrico e Come si Calcola ⭐

**Definizione**: Misura di quanto le precipitazioni mensili si discostano **al di sotto** della media storica di riferimento.

**Formula**:
```
Deficit (%) = ((Pioggia_media_storica − Pioggia_osservata) / Pioggia_media_storica) × 100
```

**Esempio pratico**: Se agosto ha storicamente 80 mm medi e quest'anno ne sono caduti 56 mm, il deficit è **30%** → zona rossa.

**Baseline**: Media storica 1981–2010 per le regioni del Cerrado brasiliano (standard WMO per confronti climatici).

**Le tre soglie critiche per la pianta del caffè**:

| Deficit | Colore | Impatto agronomico |
|---------|--------|--------------------|
| < 10% | 🟢 Verde | Precipitazioni nella norma. Pianta in condizioni ottimali. Nessun intervento necessario. |
| 10–20% | 🟠 Arancio | Stress moderato. La pianta attiva meccanismi di risparmio idrico — riduzione turgor, chiusura stomatica. Irrigazione supplementare consigliata. Possibile riduzione dimensionale del frutto (chicco più piccolo). |
| > 20% | 🔴 Rosso | Stress severo. Rischio di **aborto floreale** (le gemme floreali cadono prima di impollinare). Riduzione della resa stimata 20–40%. Maggiore suscettibilità a malattie fungine (*Cercospora coffeicola*, *Hemileia vastatrix*). Riduzione della qualità del chicco per disidratazione precoce. |

**Calendario critico del caffè in Brasile (Cerrado/Minas Gerais)**:

| Mese | Fase fenologica | Vulnerabilità al deficit |
|------|----------------|--------------------------|
| Giu–Set | Stagione secca fisiologica | Deficit 20–35% è **normale e necessario** per sincronizzare la fioritura |
| Ott–Nov | **Fioritura** | ⚠️ Deficit > 20% in questo periodo = disastro agronomico. La fioritura richiede un "trigger" idrico (prime piogge dopo la siccità) — senza pioggia la fioritura è asincronizzata e ridotta. |
| Dic–Gen | **Chumbinho** (sviluppo del frutto) | ⚠️ Il chicco si forma in questa fase — deficit riduce direttamente dimensioni e densità del chicco. |
| Feb–Apr | Maturazione | Deficit qui riduce il peso finale del frutto e la resa alla lavorazione. |
| Mag–Giu | Raccolta | Meno critico per il raccolto in corso, ma impatta la formazione delle gemme per il prossimo anno. |

---

### 3.22 — Grafico: Deficit Pluviometrico Mensile con Media Mobile (Ultimi 24 Mesi)

**Tipo**: Barre colorate dinamicamente per soglia + linea nera (media mobile 12 mesi).

**Colorazione barre**:
- 🟢 Verde: deficit < 10% (nella norma)
- 🟠 Arancio: 10–20% (stress moderato)
- 🔴 Rosso: > 20% (stress severo)

**Linee tratteggiate di riferimento**: a 10% (soglia stress moderato) e 20% (soglia stress severo).

**Come leggerlo**: Un blocco di barre rosse consecutive in **Ottobre–Novembre** o **Dicembre–Gennaio** è il segnale di massima preoccupazione per il raccolto dell'anno successivo. Confrontare sempre con l'ONI — un El Niño attivo (ONI > +1.0°C) in estate australe porta quasi invariabilmente deficit > 20% nelle regioni del Cerrado in Settembre–Novembre.

---

### 3.23 — Grafico: Deficit Pluviometrico Medio per Stato (Barre Orizzontali)

**Tipo**: Barre orizzontali con gradiente continuo RdYlGn_r (rosso = critico, verde = abbondante).

**Asse Y**: Sigla dello stato — compatta. Mouse-over: nome completo con regione geografica.

**Come leggerlo**: Gli stati con deficit medio > 15% dipendono strutturalmente dall'irrigazione per sostenere le rese. Gli impianti di irrigazione coprono ~30% delle piantagioni Arabica in Minas Gerais, ma scendono < 10% nelle zone Robusta di Rondônia (coltivate in contesto più umido). Un aumento strutturale del deficit medio (visibile su più anni consecutivi) indica un peggioramento delle condizioni climatiche locali e un aumento dei costi di produzione a lungo termine.

---

## PARTE 4 — SISTEMA DI NORMALIZZAZIONE DEI NOMI GEOGRAFICI

La dashboard unifica tre sistemi di denominazione degli stati brasiliani — sigle (MG, ES...), nomi per esteso in varie grafie (Espirito Santo, Espírito Santo), e micro-regioni CONAB (Triângulo, Alto Paranaíba...) — tramite:

- **`REGION_NAME_MASTER`**: Dizionario centralizzato con ~80 voci.
- **`normalize_region_name()`**: Funzione di lookup che accetta qualsiasi variante e restituisce la label italiana normalizzata.

**Formato target**: `"SIGLA — Nome Completo (Regione Italiana)"`

Esempi di mapping:

| Input (variante) | Output (label normalizzata) |
|-----------------|----------------------------|
| `"MG"` | `"MG — Minas Gerais (Sud-Est)"` |
| `"Espirito Santo"` | `"ES — Espírito Santo (Sud-Est)"` |
| `"Espírito Santo"` | `"ES — Espírito Santo (Sud-Est)"` |
| `"Triângulo, Alto Paranaíba e Noroeste"` | `"MG Norte-Ovest — Triângulo/Noroeste"` |
| `"SUDESTE"` | `"Sud-Est Brasile (MG, ES, SP, RJ)"` |
| `"Norte"` | `"Nord Brasile (RO, AM, PA...)"` |

**Nei grafici**: L'asse Y mostra sempre la **sigla compatta** (prima del "—") per economia di spazio. Il **tooltip al passaggio del mouse** mostra il nome completo con regione geografica.

---

## PARTE 5 — ARCHITETTURA TECNICA

```
app_standalone.py
│
├── COSTANTI & CONFIG          URL endpoint, API key, coordinate, palette colori
├── NORMALIZZAZIONE            REGION_NAME_MASTER / normalize_region_name()
├── FUNZIONI DI FETCH          @st.cache_data(ttl) — una per fonte
│   ├── fetch_prices()         World Bank Excel + yfinance EURBRL=X (merge_asof)
│   ├── fetch_enso_data()      NOAA ONI (testo, filtro -99.90)
│   ├── fetch_soi_data()       NOAA SOI
│   ├── fetch_climate()        Modello parametrico (ONI → deficit → incendi)
│   ├── fetch_firms_data()     NASA FIRMS CSV via API
│   ├── fetch_usda()           USDA PSD REST per anno, pivot su attributo
│   ├── fetch_faostat()        FAOSTAT via libreria Python
│   ├── fetch_conab_states()   CSV da fetch_conab.py
│   ├── build_port_history()   Modello parametrico clima → congestione → ritardo
│   └── _fetch_ais_snapshot()  AISStream WebSocket async (nest_asyncio)
├── WILDFIRE MAPS              render_wildfire_maps() — GeoPandas + Matplotlib
├── FUNZIONI DI RENDERING      Una per ogni scheda
│   ├── render_tab_1()         Clima & ENSO
│   ├── render_tab_2()         Incendi
│   ├── render_tab_3()         Navi & Porti
│   ├── render_tab_4()         Prezzi (spread, BRL/EUR dual-subplot, Z-score)
│   ├── render_tab_5()         Produttività (FAOSTAT, USDA, CONAB, bubble)
│   └── render_tab_6()         Precipitazioni
└── main()                     Sidebar → fetch → health panel → tab routing
```

**Gestione errori**: Ogni `fetch_*()` è protetta da `try/except` multiplo. In caso di fallimento, la funzione registra l'errore nel pannello "Salute API" e restituisce dati simulati — **un'API giù non blocca mai il resto della dashboard**.

**Caching**: `@st.cache_data(ttl=N_secondi)` memorizza il risultato di ogni fetch in RAM. TTL tipici: 3600s (1h) per prezzi e incendi, 86400s (24h) per ENS e USDA.

---

## PARTE 6 — GLOSSARIO

| Termine | Definizione |
|---------|-------------|
| **API** | Application Programming Interface — sistema di comunicazione tra software. |
| **AIS** | Automatic Identification System — tracciamento obbligatorio navi commerciali via VHF. |
| **Arabica** | Coffea arabica — varietà premium, coltivata in altitudine, ~60% produzione mondiale. |
| **Base 100** | Normalizzazione che porta tutte le serie al valore 100 alla data iniziale per confronti di crescita relativa. |
| **Cache TTL** | Time To Live — durata di validità di un dato in memoria prima del refresh. |
| **Conilon** | Nome locale brasiliano per Coffea canephora (Robusta). |
| **Deficit pluviometrico** | Scostamento percentuale delle precipitazioni al di sotto della media storica. |
| **ENSO** | El Niño-Southern Oscillation — fenomeno climatico ciclico del Pacifico che altera le precipitazioni globali. |
| **Ending Stocks** | Scorte di fine anno commerciale — indicatore di disponibilità fisica residua per l'anno successivo. |
| **FRP** | Fire Radiative Power — potenza energetica irradiata da un incendio in Megawatt. |
| **ICE** | Intercontinental Exchange — borsa commodity per i futures del caffè. |
| **Marketing Year** | Anno commerciale agricolo (per il caffè brasiliano: Aprile–Marzo). |
| **merge_asof** | Funzione pandas per unire due dataframe su una chiave temporale usando la data più vicina. |
| **MMSI** | Maritime Mobile Service Identity — identificativo unico di ogni nave (9 cifre). |
| **ONI** | Oceanic Niño Index — anomalia termica superficie marina Pacifico Centrale. |
| **Pink Sheet** | Nome colloquiale del dataset mensile prezzi commodity della Banca Mondiale. |
| **PSD** | Production, Supply and Distribution — database USDA di riferimento globale. |
| **QCL** | Crops and Livestock Products — dataset FAOSTAT per colture. |
| **Robusta** | Coffea canephora — varietà resistente alla siccità, più caffeina, usata in miscele espresso. |
| **Sacco 60 kg** | Unità di misura standard internazionale per il caffè verde (1 MT = 16,667 sacchi). |
| **SOG** | Speed Over Ground — velocità della nave in nodi rispetto al fondale. |
| **SOI** | Southern Oscillation Index — differenza standardizzata di pressione atmosferica Tahiti–Darwin. |
| **Spread** | Differenziale di prezzo tra due commodity correlate. Nel caffè: Arabica − Robusta. |
| **SST** | Sea Surface Temperature — temperatura superficiale del mare. |
| **VIIRS** | Visible Infrared Imaging Radiometer Suite — sensore termico satellitare NASA. |
| **WebSocket** | Protocollo di comunicazione bidirezionale persistente per dati in streaming. |
| **yfinance** | Libreria Python per download di serie storiche da Yahoo Finance. |
| **Z-score** | Misura statistica: di quante deviazioni standard un valore si discosta dalla media corrente. |
