# Documentazione Tecnica & di Business
# Dashboard Intelligence Filiera Caffè — Lavazza Brazil Origins

---

> **A chi è rivolto questo documento**
> Questo documento è strutturato per essere comprensibile a tre tipi di pubblico simultaneamente:
> - **Business & Management**: comprende il valore strategico di ogni dato senza entrare nei tecnicismi
> - **Analisti & Data Analyst**: comprende la struttura dei dati, le metriche e come interpretare i grafici
> - **Data Scientists & Sviluppatori**: comprende le API, i formati dati, i limiti tecnici e le opportunità di sviluppo

---

## 🚀 COME AVVIARE LA DASHBOARD

### File richiesti

Per eseguire la dashboard sono necessari i seguenti file nella stessa cartella di progetto:

| File | Ruolo |
|------|-------|
| `app_standalone.py` | Applicazione Streamlit principale — contiene tutta la logica di fetch, caching e rendering dei grafici. È l'unico file da passare a `streamlit run`. |
| `dashboard_core.py` | Modulo di supporto con costanti condivise, utilità e funzioni ausiliarie richiamate da `app_standalone.py`. Deve essere presente nella stessa directory. |
| `fetch_conab.py` | Script indipendente per il download e il parsing del report Excel CONAB. Va eseguito separatamente, prima di avviare la dashboard. |

---

### Prerequisiti

1. **Python ≥ 3.10** installato sul sistema.
2. **Dipendenze Python** installate tramite il file `requirements.txt` incluso nel progetto:

```bash
pip install -r requirements.txt
```

3. **Variabili d'ambiente** per i dati live (vedi sezione dedicata sotto):

```bash
# Creare un file .env nella cartella del progetto, oppure esportare nel terminale
export USDA_API_KEY="la-tua-chiave-usda"
export FAOSTAT_USERNAME="la-tua-email-fao"
export FAOSTAT_PASSWORD="la-tua-password-fao"
```

> **Nota:** Senza queste variabili la dashboard funziona comunque in modalità **Dati Simulati**, che non richiede alcuna autenticazione.

---

### Come ottenere le credenziali e le chiavi API

Ogni fonte dati richiede una registrazione separata. Di seguito i passaggi per ciascuna:

#### 🔑 USDA API Key
1. Andare su [https://apps.fas.usda.gov/psdonline/app/index.html#/app/registration](https://apps.fas.usda.gov/psdonline/app/index.html#/app/registration)
2. Registrarsi gratuitamente con nome, cognome ed e-mail istituzionale.
3. Una volta approvata la richiesta (tipicamente entro poche ore), si riceve la chiave via e-mail.
4. Impostarla come variabile d'ambiente: `export USDA_API_KEY="xxxxx"`

#### 🔑 FAOSTAT Username & Password
1. Andare su [https://www.fao.org/registration/](https://www.fao.org/registration/) e creare un account FAO gratuito.
2. Le credenziali FAO (e-mail e password) sono le stesse da usare nella dashboard.
3. Impostarle come variabili: `export FAOSTAT_USERNAME="email@esempio.com"` e `export FAOSTAT_PASSWORD="password"`
> **Nota:** Se FAOSTAT non richiede autenticazione nel momento dell'uso, le variabili possono essere lasciate vuote — la libreria tenta comunque l'accesso pubblico.

#### 🔑 NASA FIRMS Map Key
1. Andare su [https://firms.modaps.eosdis.nasa.gov/api/area/](https://firms.modaps.eosdis.nasa.gov/api/area/)
2. Cliccare su **"Get MAP_KEY"** e registrarsi con un account Earth Data NASA (gratuito).
3. La chiave viene mostrata subito dopo la registrazione.
4. La chiave è attualmente hardcoded nella costante `FIRMS_MAP_KEY` in `app_standalone.py` — sostituire il valore con la propria chiave.

#### 🔑 ER-API (Exchange Rates)
- **Nessuna registrazione richiesta.** L'endpoint `open.er-api.com` è pubblico e gratuito per uso base (1.500 chiamate/mese).
- Non è necessaria alcuna chiave API nella configurazione attuale della dashboard.

#### 🔑 AISStream.io API Key
1. Andare su [https://aisstream.io/](https://aisstream.io/) e registrarsi gratuitamente.
2. Dal pannello utente, copiare la propria API Key.
3. La chiave è attualmente hardcoded nella costante `AIS_API_KEY` in `app_standalone.py` — sostituire il valore con la propria chiave.
> **Nota:** Il piano gratuito di AISStream è sufficiente per la demo. Per copertura AIS completa sui porti brasiliani è necessario un piano premium.

---

### Passo 1 — Aggiornare i dati CONAB

Prima di avviare la dashboard, eseguire una volta lo script di scraping CONAB per scaricare il report più recente:

```bash
python3 fetch_conab.py
```

Lo script scarica l'ultimo Excel dal sito `gov.br/conab`, lo analizza e salva il risultato in:

```
data_sources/conab/conab_data.csv
```

> **Quando ripetere questo passo:** Il CONAB pubblica nuovi Levantamentos de Café circa 5-6 volte all'anno. Si consiglia di schedulare questo script (es. via cron job mensile) oppure di eseguirlo manualmente prima di ogni presentazione importante.

---

### Passo 2 — Avviare la dashboard Streamlit

Dalla cartella del progetto, eseguire:

```bash
streamlit run app_standalone.py
```

Streamlit avvierà automaticamente il browser predefinito all'indirizzo:

```
http://localhost:8501
```

> **Opzioni utili:**
> ```bash
> # Specificare una porta diversa
> streamlit run app_standalone.py --server.port 8080
>
> # Avviare senza aprire il browser automaticamente
> streamlit run app_standalone.py --server.headless true
> ```

---

### Riepilogo rapido (copia-incolla)

```bash
# 1. Installa le dipendenze (solo la prima volta)
pip install -r requirements.txt
pip install geopandas websockets faostat openpyxl   # se non già presenti

# 2. Aggiorna i dati CONAB
python3 fetch_conab.py

# 3. Avvia la dashboard
streamlit run app_standalone.py
```

Una volta aperta la dashboard, selezionare **"Dati API Reali"** dalla sidebar sinistra per usare le fonti live, oppure **"Dati Simulati"** per una demo offline senza chiavi API.

---

## PARTE 1 — PANORAMICA DELLA DASHBOARD

### Cos'è questa dashboard?

La dashboard è un sistema centralizzato di monitoraggio e visualizzazione dati che aggrega informazioni provenienti da **8 fonti dati globali** in tempo reale o semi-reale, con l'obiettivo di fornire a Lavazza una visione integrata della filiera del caffè brasiliano.

Il Brasile è il **primo produttore mondiale di caffè**, responsabile di circa il 35-40% dell'intera produzione globale. Monitorare le condizioni climatiche, produttive, logistiche e di mercato in Brasile significa avere visibilità anticipata sui rischi che impattano direttamente i costi di approvvigionamento e la disponibilità di materia prima.

### Filosofia della dashboard

La dashboard è progettata come uno strumento di **esplorazione dati puri**, non di previsione. Non contiene modelli predittivi né raccomandazioni automatiche. Ogni scheda mostra i dati disponibili così come sono — il valore sta nel permettere agli esperti di dominio (buyers, agronomi, logistici) di vedere tutto in un unico posto e identificare correlazioni rilevanti.

### Struttura: 6 Schede Tematiche

| Scheda | Tema | Fonte Principale |
|--------|------|-----------------|
| 🌦️ Clima & ENSO | Fenomeni climatici globali che influenzano le piogge | NOAA |
| 🔥 Incendi | Rilevamenti satellitari di incendi attivi in Brasile | NASA FIRMS |
| ⚓ Navi & Porti | Traffico marittimo e congestione dei porti export | AISStream.io |
| 📈 Prezzi di Mercato | Prezzi commodity caffè e tassi di cambio | World Bank / ER-API |
| 🌾 Produttività Colture | Produzione, resa e stock per anno | USDA PSD / FAOSTAT / CONAB |
| 🌧️ Precipitazioni | Deficit pluviometrico per stagione e stato | NOAA (modellato) |

---

## PARTE 2 — LE API: DESCRIZIONE DETTAGLIATA

### 2.1 NOAA — National Oceanic and Atmospheric Administration
**Indici ENSO: ONI e SOI**

**Chi è NOAA?**
La NOAA è l'agenzia governativa americana che gestisce il monitoraggio dell'oceano e dell'atmosfera globale. I suoi dati sono il gold standard internazionale per la meteorologia e la climatologia. Pubblica gratuitamente decenni di dati storici.

**Cosa forniamo dalla NOAA:**

**Indice ONI — Oceanic Niño Index**
- **Cos'è**: Misura l'anomalia termica (in gradi Celsius) della superficie oceanica nella regione Niño 3.4 del Pacifico Centrale, usando una media mobile trimestrale.
- **Perché importa**: Le temperature oceaniche nel Pacifico guidano i pattern di pioggia e siccità in tutto il Sud America. Quando il Pacifico si scalda (El Niño), il Brasile nord-orientale e la regione amazzonica soffrono di siccità, aumentando il rischio di incendi. Quando si raffredda (La Niña), il Sud del Brasile riceve piogge eccessive.
- **Come si legge**: ONI > +0.5°C per almeno 5 mesi consecutivi = El Niño. ONI < -0.5°C = La Niña. Tra -0.5 e +0.5 = fase neutra.
- **Frequenza aggiornamento**: Mensile. La dashboard aggiorna i dati ogni 24 ore.
- **Endpoint**: `https://psl.noaa.gov/data/correlation/oni.data` — file di testo a larghezza fissa, pubblico e senza autenticazione.
- **Storico disponibile**: Dal 1950 ad oggi.

**Indice SOI — Southern Oscillation Index**
- **Cos'è**: Misura la differenza di pressione atmosferica standardizzata tra Tahiti (Pacifico Est) e Darwin (Australia), calcolata mensilmente dalla NOAA.
- **Perché importa**: Il SOI è la componente "atmosferica" dell'ENSO, mentre l'ONI è quella "oceanica". Quando entrambi superano le soglie (ONI e SOI concordano) si parla di **evento accoppiato**, che produce impatti agricoli molto più severi e prevedibili rispetto a quando i due indici divergono.
- **Come si legge**: SOI > +7 = La Niña confermata atmosfericamente. SOI < -7 = El Niño confermato. Un ONI positivo con SOI positivo indica un disaccoppiamento: l'evento è débole o si sta attenuando.
- **Frequenza aggiornamento**: Mensile. Cache 24 ore nella dashboard.
- **Endpoint**: `https://psl.noaa.gov/data/correlation/soi.data` — stessa struttura dell'ONI.

**Nota tecnica importante**: Entrambi i file NOAA usano il valore `-99.90` per i mesi non ancora registrati (mesi futuri dell'anno corrente). La dashboard filtra automaticamente questi valori e prende solo l'ultimo mese con dato valido.

---

### 2.2 NASA FIRMS — Fire Information for Resource Management System

**Chi è NASA FIRMS?**
NASA FIRMS è il sistema della NASA che distribuisce in tempo quasi-reale i dati di rilevamento degli incendi da satellite. Utilizza i sensori VIIRS (Visible Infrared Imaging Radiometer Suite) a bordo dei satelliti Suomi NPP e NOAA-20.

**Cosa forniamo:**
- **FRP — Fire Radiative Power**: Potenza radiativa del fuoco in Megawatt (MW). È la misura dell'intensità di un incendio rilevato da satellite. Più alto è il valore FRP, più intenso è l'incendio.
- **Coordinate geografiche**: Latitudine e longitudine di ogni focolaio rilevato.
- **Data di rilevamento**: Il file copre gli ultimi N giorni configurabili (nella dashboard: 5 giorni).

**Perché importa per il caffè?**
Gli incendi nel Cerrado (savana brasiliana) e in Amazzonia impattano direttamente le piantagioni di caffè in tre modi:
1. **Danno diretto**: I fuochi si propagano alle piantagioni, distruggendo il raccolto.
2. **Danno indiretto da fumo**: Il particolato riduce la fotosintesi delle piante nelle settimane successive.
3. **Effetto suolo**: Le ceneri alterano il pH e la composizione chimica del suolo, impattando le rese future.

**Come funziona tecnicamente:**
- **API**: `https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{BBOX}/{DAYS}`
- **MAP_KEY**: Chiave personale ottenibile gratuitamente dal sito NASA FIRMS.
- **SOURCE**: `VIIRS_SNPP_NRT` (Near Real-Time, Suomi NPP).
- **BBOX**: Bounding box geografica in formato `lon_min,lat_min,lon_max,lat_max`. Per il Brasile: `-75,-35,-33,6`.
- **Output**: File CSV con colonne: `latitude`, `longitude`, `bright_ti4`, `bright_ti5`, `frp`, `daynight`, `acq_date`, ecc.
- **Latenza**: I dati NRT (Near Real-Time) sono disponibili circa 3 ore dopo il passaggio del satellite.
- **Aggiornamento**: Ogni 12 ore (doppio passaggio dei satelliti in orbita polare).

**Come visualizziamo i dati:**
La mappa usa **Matplotlib + GeoPandas** per sovrapporre tre layer:
1. Layer base: confini degli stati brasiliani (GeoJSON IBGE).
2. Layer produzione: colorazione coropletica degli stati per volume di produzione di Arabica (verde) o Robusta (viola).
3. Layer incendi piccoli (FRP ≤ 50 MW): punti grigi semitrasparenti.
4. Layer incendi grandi (FRP > 50 MW): punti colorati con gradiente `hot` (rosso scuro → arancione → giallo), dimensionati proporzionalmente a `√FRP × 3`.

La scelta di separare piccoli e grandi incendi è deliberata: i focolai minori (disboscamento controllato, fuochi agricoli) sono rumore di fondo. I grandi incendi (FRP > 50 MW) sono quelli che costituiscono un rischio reale per le colture.

---

### 2.3 AISStream.io — Automatic Identification System Live Stream

**Cos'è AIS?**
L'AIS (Automatic Identification System) è un sistema di tracciamento marittimo obbligatorio per tutte le navi commerciali sopra le 300 tonnellate. Ogni nave trasmette continuamente via VHF la propria posizione, velocità, rotta e tipo di nave. Esistono reti globali di ricevitori a terra e satellitari che aggregano questi segnali.

**Cos'è AISStream.io?**
AISStream.io è un servizio che distribuisce i dati AIS via WebSocket in tempo reale. La dashboard si connette direttamente tramite WebSocket (protocollo `wss://`) e riceve un flusso continuo di messaggi JSON.

**Tipi di messaggi ricevuti:**
- **PositionReport**: Posizione aggiornata ogni 2-10 secondi per ogni nave. Contiene: latitudine, longitudine, SOG (Speed Over Ground in nodi), stato navigazionale (0=in navigazione, 1=all'ancora, 5=ormeggiata).
- **ShipStaticData**: Dati statici della nave trasmessi ogni 6 minuti. Contiene: nome, MMSI (identificativo univoco), tipo di nave (codice AIS 70-89 = cargo).

**Codici tipo nave AIS rilevanti:**
| Codice | Tipo |
|--------|------|
| 70 | Cargo generico |
| 71 | Cargo, pericolosi (cat A) |
| 72 | Cargo, pericolosi (cat B) |
| 73 | Cargo, pericolosi (cat C) |
| 74 | Cargo, pericolosi (cat D) |
| 79 | Cargo (non classificato) |
| 80-89 | Petroliere e chimichiere |

**Limitazione importante del tier gratuito:**
Il tier gratuito di AISStream.io ha copertura concentrata sui grandi hub marittimi globali (Asia, Nord Europa, West Coast USA). La copertura nei porti brasiliani è frammentata e insufficiente per un monitoraggio affidabile. **Per questa ragione, la demo live utilizza Singapore, Rotterdam e Los Angeles** come porti di riferimento per dimostrare il funzionamento del sistema. I dati di congestione dei porti brasiliani (Santos, Vitória, Paranaguá, Rio de Janeiro, Salvador) sono invece **stimati con un modello** basato su stress climatico e pattern storici.

**Per ottenere dati AIS affidabili sui porti brasiliani in produzione**, sarebbe necessario sottoscrivere un piano premium di un provider come MarineTraffic, VesselFinder, o acquistare feed AIS satellitari (es. Spire Maritime, exactEarth).

**I 5 porti brasiliani monitorati:**
| Porto | Quota export caffè |
|-------|-------------------|
| Santos (SP) | ~60% del totale nazionale |
| Vitória (ES) | ~25% |
| Paranaguá (PR) | ~8% |
| Rio de Janeiro (RJ) | ~4% |
| Salvador (BA) | ~3% |

---

### 2.4 World Bank Commodity Price Data — "Pink Sheet"

**Cos'è?**
La Banca Mondiale pubblica mensilmente il "Pink Sheet" (foglio rosa), un dataset storico dei prezzi delle principali commodity globali. Per il caffè, riporta le quotazioni ICE (Intercontinental Exchange) di New York per l'Arabica e di Londra per la Robusta.

**Dati forniti:**
- **Arabica**: Prezzo in USD/kg, contratto ICE New York "Other Milds" (qualità lavata centro-americana, usata come benchmark internazionale).
- **Robusta**: Prezzo in USD/kg, contratto ICE Liffe Londra.
- **Frequenza**: Mensile, con storico dal 1960.

**Come accediamo:**
- **Endpoint**: File Excel (`.xlsx`) scaricato direttamente dalla Banca Mondiale.
- **URL**: Diretto link al file Excel CMO (Commodity Markets Outlook), foglio 2, righe 4-5 come header.
- **Parsing**: La dashboard legge il file Excel in memoria, identifica le colonne caffè tramite keyword "coffee", e converte i prezzi da USD a EUR usando il tasso di cambio live.
- **Aggiornamento**: Il Pink Sheet viene aggiornato ogni mese (solitamente intorno al 10 del mese).

**Conversione valutaria:**
I prezzi vengono convertiti in EUR/kg usando il tasso di cambio live fornito da ER-API (vedi paragrafo successivo).

---

### 2.5 ER-API — Exchange Rates API

**Cos'è?**
ER-API (`open.er-api.com`) è un servizio gratuito di tassi di cambio in tempo reale. Fornisce i tassi di cambio correnti rispetto al dollaro USA per ~160 valute.

**Dati forniti dalla dashboard:**
- **USD → EUR**: Usato per convertire i prezzi commodity da dollari a euro.
- **USD → BRL**: Usato per calcolare il tasso BRL/EUR (derivato incrociando USD/EUR e USD/BRL), che impatta il costo delle esportazioni brasiliane.

**Perché il BRL/EUR è importante:**
Quando il Real brasiliano si deprezza rispetto all'Euro (il tasso BRL/EUR sale, cioè ci vogliono più Real per comprare un Euro), i produttori brasiliani ricevono più Real per ogni sacco di caffè venduto all'estero. Questo **incentiva le esportazioni** e può comprimere le scorte disponibili, esercitando pressione al rialzo sui prezzi internazionali.

---

### 2.6 USDA PSD — Production, Supply and Distribution

**Chi è USDA FAS?**
Il Foreign Agricultural Service del Dipartimento dell'Agricoltura degli Stati Uniti pubblica la banca dati PSD (Production, Supply and Distribution), che è il dataset di riferimento globale per le previsioni e i consuntivi di produzione agricola mondiale. I dati vengono compilati attraverso una rete di attaché agricoli nei vari paesi e aggiornati mensilmente.

**Cosa contiene per il caffè brasiliano:**
| Attributo | Descrizione | Unità |
|-----------|-------------|-------|
| Production | Produzione totale del marketing year | 1000 Metric Ton |
| Exports | Volume esportato | 1000 MT |
| Ending Stocks | Scorte di fine anno | 1000 MT |
| Beginning Stocks | Scorte di inizio anno | 1000 MT |
| Domestic Consumption | Consumo interno brasiliano | 1000 MT |

**Marketing Year per il caffè brasiliano**: Aprile-Marzo (il raccolto principale in Brasile avviene tra Maggio e Settembre).

**Come accediamo:**
- **Endpoint base**: `https://api.fas.usda.gov/api/psd`
- **Autenticazione**: Header `X-Api-Key` con chiave personale. Chiave di test disponibile, ma per uso production è necessaria registrazione gratuita su `fas.usda.gov`.
- **Pattern di fetch**: La dashboard scarica i dati anno per anno (`/commodity/{code}/country/{country}/year/{year}`), poi li pivota per ottenere un dataframe storico.
- **Commodity code**: `0711100` = Coffee, Green (caffè verde, non torrefatto).
- **Country code**: `BR` = Brasile.

**Conversione unità:**
USDA usa "1000 Metric Ton". La dashboard converte in sacchi da 60 kg:
- 1 MT = 16.667 sacchi da 60 kg
- I valori USDA sono in 1000 MT → moltiplicare per 1000 × 16.667

---

### 2.7 FAOSTAT — Food and Agriculture Organization Statistics

**Chi è la FAO?**
La FAO (Food and Agriculture Organization) è l'agenzia dell'ONU per l'alimentazione e l'agricoltura. FAOSTAT è la sua banca dati statistica, considerata la fonte più autorevole per i dati agricoli storici a livello globale. Copre oltre 200 paesi e risale al 1961.

**Cosa forniamo:**
Dal dataset **QCL (Crops and Livestock Products)**, item 656 (Coffee, green), paese 21 (Brasile):
| Elemento | Codice | Descrizione |
|----------|--------|-------------|
| Area harvested | 2312 | Superficie raccoltata in ettari |
| Production | 2510 | Produzione in tonnellate |
| Yield | 2413 | Resa in hg/ha (ettogrammi per ettaro) |

**Perché è prezioso:**
FAOSTAT offre dati dal **1990 ad oggi**, permettendo di vedere i cicli pluridecennali della produzione brasiliana: l'espansione delle aree coltivate, il miglioramento della resa per ettaro grazie alle tecnologie agricole, e i cicli biennali di produzione (anno on/off).

**Come accediamo:**
- **Metodo**: Libreria Python `faostat` (installabile via pip). Non si chiama un endpoint REST direttamente ma si usa la libreria che gestisce l'autenticazione e il parsing.
- **Autenticazione**: Credenziali FAOSTAT (username/password) impostabili via variabili d'ambiente `FAOSTAT_USERNAME` e `FAOSTAT_PASSWORD`.
- **Parametri chiave**:
  - `area`: `'21'` (Brasil)
  - `item`: `'656'` (Coffee, green)
  - `element`: stringa separata da virgole (es. `'2312,2413,2510'`)

---

### 2.8 CONAB — Companhia Nacional de Abastecimento

**Chi è CONAB?**
CONAB è l'ente governativo brasiliano responsabile del monitoraggio e delle previsioni della produzione agricola in Brasile. Pubblica i "Levantamentos de Café" (rilevamenti del caffè), rapporti periodici (solitamente 5-6 all'anno) con dati aggiornati su produzione, resa e area raccolta per ogni stato brasiliano.

**Cosa contiene:**
- Produzione per stato (MG, ES, SP, BA, RO, PR, GO, MT, ecc.) in sacchi da 60 kg
- Superficie raccoltata in ettari
- Resa in sacchi/ettaro
- Confronto con stagione precedente

**Come accediamo:**
CONAB non ha un'API ufficiale. I dati sono disponibili in file Excel scaricabili dalla pagina web `gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe`.

La dashboard include uno script separato (`fetch_conab.py`) che:
1. Accede alla pagina web e trova il link all'ultimo rapporto tramite BeautifulSoup.
2. Naviga nella pagina del rapporto e trova il link al file Excel.
3. Scarica il file Excel e lo analizza cercando le colonne di interesse (`(d)` per la resa, `(f)` per la produzione).
4. Salva i risultati come CSV in `data_sources/conab/conab_data.csv`.

Questo script viene eseguito **manualmente o schedulato** (cron job), non ad ogni ricaricamento della dashboard.

**Limitazione**: La struttura del file Excel CONAB cambia occasionalmente tra un rapporto e l'altro. Lo script include logica di ricerca intelligente che identifica le colonne per intestazione (`(d)`, `(f)`) invece che per posizione fissa.

---

### 2.9 GeoJSON IBGE — Confini Geografici degli Stati Brasiliani

**Cos'è:**
Un file GeoJSON (formato standard per dati geografici vettoriali) che contiene i confini poligonali di tutti gli stati brasiliani. Viene usato per:
- Sovrapporre i dati di produzione caffè su una mappa coropletica.
- Identificare a quale stato appartiene ogni focolaio NASA FIRMS tramite join spaziale (GeoPandas `sjoin`).

**Fonte**: Repository pubblico GitHub `click_that_hood`. Il file viene scaricato direttamente e cachato per 1 ora.

---

## PARTE 3 — I GRAFICI: GUIDA COMPLETA TAB PER TAB

### Scheda 1: 🌦️ Clima & ENSO

#### Grafico 1.1 — Linea ONI con aree di fase (Ultimi 36 mesi)
**Tipo**: Linea temporale con aree colorate.
**Cosa mostra**: L'andamento mensile dell'indice ONI negli ultimi 3 anni.
- Area rossa: mesi in cui ONI > +0.5 (fase El Niño).
- Area blu: mesi in cui ONI < -0.5 (fase La Niña).
- Linea nera: valore ONI mensile.
- Linee tratteggiate: soglie +0.5 e -0.5.

**Come leggerlo**: Un periodo prolungato nell'area rossa indica rischio siccità per le zone produttrici di caffè nel Centro-Ovest e in Amazzonia. Più il valore ONI è alto, più l'impatto è severo.

#### Grafico 1.2 — Grafico a barre SOI (Ultimi 36 mesi)
**Tipo**: Istogramma bicolore.
**Cosa mostra**: Il valore mensile del SOI.
- Barre blu: mesi con SOI positivo (La Niña atmosferica).
- Barre rosse: mesi con SOI negativo (El Niño atmosferico).
- Linee tratteggiate: soglie +7 e -7.

**Come leggerlo**: Quando sia ONI che SOI superano le rispettive soglie nella stessa direzione, l'evento ENSO è "accoppiato" e gli impatti agricoli sono certi e forti. Se divergono, l'evento è debole o in dissolvenza.

#### Grafico 1.3 — Heatmap ONI 10 anni (Mese × Anno)
**Tipo**: Mappa di calore.
**Cosa mostra**: Il valore ONI per ogni mese (righe, Gennaio-Dicembre) per ogni anno degli ultimi 10 anni (colonne).
- Rosso intenso: El Niño forte.
- Blu intenso: La Niña forte.
- Bianco/grigio: fase neutra.

**Come leggerlo**: Permette di identificare immediatamente gli anni di stress climatico e la loro stagionalità. Un blocco rosso prolungato su più mesi dello stesso anno indica un anno di El Niño significativo.

#### Grafico 1.4 — Anomalia di Temperatura (Area Riempita)
**Tipo**: Area chart bicolore.
**Cosa mostra**: L'anomalia di temperatura superficiale nella cintura del caffè brasiliano rispetto alla baseline 1980-2010.
- Area rossa: mesi con temperatura sopra la media.
- Area blu: mesi con temperatura sotto la media.

**Come leggerlo**: Le anomalie positive durante la fase di fioritura del caffè (Settembre-Novembre) o di maturazione (Febbraio-Aprile) aumentano lo stress idrico della pianta e possono ridurre la qualità e la resa del raccolto.

---

### Scheda 2: 🔥 Incendi

#### Grafico 2.1 & 2.2 — Mappe Arabica e Robusta con Incendi NASA (Matplotlib)
**Tipo**: Mappa geografica statica con layer multipli.
**Cosa mostra (mappa sinistra)**: Produzione di Arabica per stato (gradiente verde, più scuro = più produzione) + focolai NASA degli ultimi 5 giorni.
**Cosa mostra (mappa destra)**: Stessa struttura per la Robusta (gradiente viola).
**Focolari piccoli** (FRP ≤ 50 MW): Punti grigi semitrasparenti — fuochi minori, rumore di fondo.
**Focolari grandi** (FRP > 50 MW): Punti colorati scala `hot` (rosso → giallo), dimensionati per intensità.

**Come leggerlo**: La sovrapposizione tra focolai intensi (punti rosso/arancio) e aree ad alta produzione (colori intensi) indica un rischio diretto per il raccolto in corso o per quello della stagione successiva. Lo stato di Minas Gerais (MG, verde intenso) è il principale produttore di Arabica — ogni incendio lì ha impatto significativo sul mercato.

#### Grafico 2.3 — Serie Temporale Conteggi Mensili Incendi (Ultimi 24 mesi)
**Tipo**: Linea con marcatori.
**Cosa mostra**: Il numero di focolai rilevati mensilmente negli ultimi 2 anni.
**Come leggerlo**: I picchi si verificano tipicamente tra Agosto e Ottobre (stagione secca del Cerrado). Un picco anomalo fuori stagione può segnalare eventi straordinari. Confrontare con il grafico ONI per verificare la correlazione con siccità da La Niña.

#### Grafico 2.4 — Barre Focolai per Macro-Regione
**Tipo**: Grafico a barre orizzontale.
**Cosa mostra**: La distribuzione geografica degli incendi per macro-regione (Nord, Nord-Est, Centro-Ovest, Sud-Est, Sud).
**Come leggerlo**: Il Centro-Ovest (Cerrado) e il Nord (Amazzonia) dominano tipicamente. Se il Sud-Est sale in modo anomalo, significa che regioni produttrici come Minas Gerais o Espírito Santo sono direttamente coinvolte.

---

### Scheda 3: ⚓ Navi & Porti

#### Sezione 3.1 — Pannello Diagnostico AIS
**Cos'è**: Un pannello tecnico che mostra le metriche della connessione WebSocket AIS.
**Metriche**:
- **Messaggi Ricevuti**: Totale messaggi raw dal WebSocket.
- **Position Reports**: Messaggi di posizione nave.
- **Static Data Msgs**: Messaggi con dati statici (tipo nave, nome).
- **In Bbox**: Position report che ricadono nelle bounding box monitorate.
- **Finale Tracciato**: Navi effettivamente registrate dopo il filtro tipo cargo.

**Come leggerlo**: Se "Messaggi Ricevuti" è 0, la connessione è stabilita ma non arriva traffico (tipicamente per i porti brasiliani con il tier gratuito). Se "In Bbox" è 0 ma ci sono messaggi, le bounding box potrebbero essere troppo strette o non c'è traffico nella zona in quel momento.

#### Sezione 3.2 — Demo Live Porti Globali
**Cosa mostra**: Navi cargo (codici AIS 70-89) nei porti di Singapore, Rotterdam e Los Angeles, divise per "In Transito" (SOG > 1 nodo) e "All'Ancora/Ormeggiate" (SOG < 1 nodo o stato navigazionale 1/5).
**Perché globale e non brasiliana**: Come spiegato nella sezione API, il tier gratuito AIS non copre i porti brasiliani con sufficiente densità di segnale. Questa sezione dimostra la **capacità tecnologica** del sistema: con un feed AIS premium, lo stesso codice funzionerebbe in tempo reale sui porti di Santos, Vitória, ecc.

#### Grafico 3.3 — Tendenze Ritardi Brasiliani (Ultimi 12 mesi)
**Tipo**: Grafico a linee multi-serie.
**Cosa mostra**: L'andamento stimato del ritardo medio in giorni per ciascuno dei 5 porti brasiliani, basato su un modello che incorpora stress climatici (deficit pluviometrico, incendi) e dati storici di throughput.
**Come leggerlo**: Un ritardo elevato a Santos coincide spesso con periodi di alta siccità che rallentano i trasporti terrestri verso il porto, o con picchi stagionali di export (Luglio-Settembre).

#### Grafico 3.4 — Mappa Rischio Porti
**Tipo**: Scatter map su mappa interattiva.
**Cosa mostra**: I 5 porti brasiliani, dimensionati per ritardo stimato e colorati per livello di rischio (verde=basso, arancio=medio, rosso=alto).
**Come leggerlo**: Passare il mouse su ogni punto per vedere i valori esatti. Un porto in rosso con alto ritardo è il segnale per anticipare forniture o diversificare i percorsi di spedizione.

---

### Scheda 4: 📈 Prezzi di Mercato

#### Grafico 4.1 — Prezzi Arabica e Robusta (10 anni, EUR/kg)
**Tipo**: Doppio asse Y con due linee.
**Cosa mostra**: L'andamento storico dei prezzi mensili di Arabica (asse sinistro) e Robusta (asse destro) in EUR/kg.
**Come leggerlo**: Osservare la divergenza tra le due curve nel tempo. In periodi di stress climatico in Brasile, l'Arabica tende a salire più della Robusta, ampliando il differenziale.

#### Grafico 4.2 — Differenziale Arabica-Robusta con Media Mobile 3 mesi
**Tipo**: Barre + linea.
**Cosa mostra**: La differenza di prezzo Arabica − Robusta per ogni mese. La linea rossa è la media mobile su 3 mesi.
**Come leggerlo**: Un differenziale in crescita indica che il mercato sta pagando un premio crescente per la qualità Arabica — segnale di scarsità relativa o di percezione di qualità superiore. Un differenziale in calo può indicare che il mercato accetta Robusta come sostituto, o che l'offerta di Arabica è abbondante.

#### Grafico 4.3 — Heatmap Variazione % MoM Arabica (Mese × Anno)
**Tipo**: Mappa di calore.
**Cosa mostra**: La variazione percentuale mese su mese del prezzo Arabica, organizzata per mese (righe) e anno (colonne).
- Verde: mese con prezzo salito rispetto al mese precedente.
- Rosso: mese con prezzo sceso.
**Come leggerlo**: Permette di identificare la **stagionalità dei prezzi**. Se certi mesi sono sistematicamente verdi (es. Luglio-Agosto), indica che storicamente i prezzi salgono in quel periodo — tipicamente a causa del picco di export post-raccolto che riduce le scorte.

#### Grafico 4.4 — Influenza Macro FX: BRL/EUR vs Prezzo Arabica
**Tipo**: Doppio asse con area riempita (BRL/EUR) e linea (Arabica).
**Cosa mostra**: La correlazione visiva tra il tasso di cambio BRL/EUR e il prezzo in euro dell'Arabica.
**Come leggerlo**: Quando il BRL si deprezza (linea BRL/EUR sale), i produttori brasiliani ricevono più Real per lo stesso dollaro, incentivando le esportazioni e potenzialmente spingendo i prezzi internazionali verso l'alto.

#### Grafico 4.5 — Prezzo Medio Annuale Arabica vs Media 10 anni
**Tipo**: Barre + linea tratteggiata.
**Cosa mostra**: Il prezzo medio annuale dell'Arabica in EUR/kg per ogni anno, con la media decennale come riferimento.
**Come leggerlo**: Gli anni significativamente sopra la media sono stati tipicamente associati a eventi estremi: la gelata brasiliana del 2021, la siccità del 2010-11, ecc. Vedere in quale contesto climatico (scheda ENSO, Incendi) si trovavano quegli anni aiuta a costruire la narrativa causale.

---

### Scheda 5: 🌾 Produttività delle Colture

#### Grafico 5.1 — FAOSTAT: Produzione e Area Raccolta (1990–Presente)
**Tipo**: Doppio asse — barre (produzione) + linea (area).
**Cosa mostra**: La produzione brasiliana di caffè in tonnellate (barre, asse sinistro) e l'area raccoltata in ettari (linea, asse destro) dal 1990 ad oggi.
**Fonte dati**: FAOSTAT QCL dataset, aggiornato annualmente con un ritardo di 1-2 anni.
**Come leggerlo**: L'aumento dell'area coltivata mostra l'espansione geografica delle piantagioni. L'aumento della produzione proporzionalmente maggiore rispetto all'area indica **guadagni di efficienza (resa per ettaro)**. I cali biennali sono chiaramente visibili: anno on (alta produzione) e anno off (produzione ridotta).

#### Grafico 5.2 — Produzione Totale Arabica + Robusta per Anno (USDA PSD)
**Tipo**: Barre impilate.
**Cosa mostra**: Il volume totale in sacchi da 60 kg per anno, distinto per varietà.
**Fonte dati**: USDA PSD (dati live) o modello simulato.
**Come leggerlo**: Il ciclo biennale è evidente. La quota Robusta (arancione) è cresciuta negli ultimi anni grazie alla sua maggiore resistenza alla siccità, alla riduzione dei costi di produzione e all'aumento della domanda per espresso e miscele.

#### Grafico 5.3 — Export Totali vs Scorte Finali (Doppio Asse)
**Tipo**: Linea + linea tratteggiata su doppio asse.
**Cosa mostra**: L'export annuale totale (asse sinistro) e le scorte di fine anno (asse destro).
**Come leggerlo**: Quando le esportazioni crescono mentre le scorte calano, si crea una situazione di **tightening dell'offerta** — condizione che tipicamente precede un rialzo dei prezzi. Quando entrambe salgono, la produzione è abbondante.

#### Grafico 5.4 — Scatter Resa vs Produzione per Stato (CONAB)
**Tipo**: Scatter/bubble chart.
**Cosa mostra**: Ogni bolla è uno stato brasiliano. Asse X = resa (sacchi/ettaro). Asse Y = produzione totale. Dimensione della bolla proporzionale alla produzione.
**Come leggerlo**: Gli stati nell'angolo in alto a destra (alta produzione, alta resa) sono i campioni di efficienza. Minas Gerais domina per volume. Espírito Santo si distingue per alta resa di Robusta (Conilon) pur con volumi minori.

#### Grafico 5.5 — Quota di Mercato Arabica/Robusta (Donut, Anno Più Recente)
**Tipo**: Grafico a ciambella.
**Cosa mostra**: La percentuale di produzione Arabica vs Robusta nell'anno più recente.
**Come leggerlo**: Il Brasile è storicamente 70-75% Arabica. Un trend verso la parità indicherebbe un cambiamento strutturale nel profilo produttivo del paese, con implicazioni importanti per le miscele e per la disponibilità di materia prima di qualità.

---

### Scheda 6: 🌧️ Precipitazioni

#### Grafico 6.1 — Deficit Pluviometrico Mensile con Media Mobile (Ultimi 24 mesi)
**Tipo**: Barre colorate + linea media mobile.
**Cosa mostra**: Il deficit pluviometrico percentuale per ogni mese (quanto le precipitazioni sono sotto la norma). Colorazione: verde < 10%, arancio 10-20%, rosso > 20%. La linea nera è la media mobile a 12 mesi.
**Come leggerlo**: Un deficit prolungato oltre il 15-20% nelle regioni di Minas Gerais e Cerrado durante la stagione di fioritura (Settembre-Novembre) è il principale indicatore di stress agronomico per l'Arabica. Confrontare con il grafico ONI per la verifica causale.

#### Grafico 6.2 — Deficit Pluviometrico per Stato (Orizzontale)
**Tipo**: Barre orizzontali con gradiente colore.
**Cosa mostra**: Il deficit medio annuo per ogni stato produttore brasiliano.
**Come leggerlo**: Gli stati con deficit elevato richiedono maggiore dipendenza dall'irrigazione, aumentando i costi di produzione e la vulnerabilità alle stagioni siccitose. Confrontare con la mappa di produzione per identificare le aree a maggiore esposizione al rischio.

#### Grafico 6.3 — Heatmap Stagionale Deficit (Mese × Anno)
**Tipo**: Mappa di calore.
**Cosa mostra**: Il valore di deficit pluviometrico per ogni mese (righe) e anno (colonne).
- Giallo: deficit basso (piogge normali).
- Arancio/Rosso intenso: deficit elevato (siccità).
**Come leggerlo**: Il blocco Giugno-Settembre dovrebbe essere sistematicamente più scuro (stagione secca del Cerrado). Se il blocco rosso si estende a Ottobre-Novembre (fioritura) o a Dicembre-Gennaio (sviluppo del frutto), l'impatto produttivo è significativo.

---

## PARTE 4 — DOMANDE FREQUENTI DURANTE LA PRESENTAZIONE

### Domande di Business

**D: Quanto sono affidabili questi dati? Posso usarli per decisioni di acquisto?**
R: I dati provengono da fonti istituzionali di massima autorevolezza (NASA, NOAA, Banca Mondiale, USDA, FAO). Per il monitoraggio climatico e dei prezzi, l'affidabilità è molto alta. I dati di produzione (USDA/FAOSTAT) hanno un ritardo di aggiornamento di qualche mese e sono stime che vengono revisionate. I dati AIS sui porti brasiliani, con il tier gratuito, sono stimati da modello — per dati live affidabili sarebbe necessario un feed premium. La dashboard è uno strumento di **intelligence strategica e monitoraggio**, non di esecuzione operativa in tempo reale.

**D: Perché le navi brasiliane non mostrano dati live?**
R: Il sistema AIS gratuito non ha copertura sufficiente nei porti brasiliani. La parte live dimostra la capacità tecnologica del sistema (che funziona su Singapore, Rotterdam, Los Angeles). Per portarlo su Santos e Vitória in produzione, è necessario sottoscrivere un feed AIS premium (costo tipico: $500-5000/mese a seconda del volume).

**D: Con quale frequenza si aggiornano i dati?**
R: Dipende dalla fonte:
- Prezzi commodity e FX: ogni ora (cache 1h)
- NASA FIRMS (incendi): ogni 12 ore (aggiornamento satellite)
- NOAA ENSO: ogni 24 ore (dati mensili)
- USDA PSD: ogni ora (cache 1h, ma i dati cambiano mensilmente)
- FAOSTAT: ogni 24 ore (dati annuali)
- AIS live: on-demand (bottone manuale, ~10 secondi di ascolto)

**D: Cosa significa "Dati Simulati" nella sidebar?**
R: La dashboard ha due modalità: "Dati API Reali" chiama tutti gli endpoint live; "Dati Simulati" usa dataset generati con numeri pseudorandom a seed fisso, utili per demo offline o sviluppo. In produzione si usa sempre la modalità API Reali.

**D: Possiamo aggiungere altre fonti dati?**
R: Assolutamente. L'architettura è modulare. Ogni fonte è un blocco `fetch_*()` indipendente con la sua cache e il suo log di salute. Aggiungere nuove fonti (es. prezzi futures ICE diretti, dati meteo orari, report CECAFÉ) richiede solo di aggiungere la relativa funzione e richiamarla nel tab appropriato.

---

### Domande Tecniche

**D: Cos'è un WebSocket e perché lo usiamo per AIS?**
R: Un WebSocket è una connessione bidirezionale persistente tra il browser/server e un servizio remoto, a differenza delle normali chiamate HTTP che aprono e chiudono la connessione ad ogni richiesta. AIS usa i WebSocket perché i dati arrivano in flusso continuo — la nave trasmette la posizione ogni 2-10 secondi, e il WebSocket consente di ricevere questi aggiornamenti in tempo reale senza polling continuo.

**D: Cosa succede se un'API va giù?**
R: Ogni fetch function è protetta da `try/except` multiplo (Timeout, HTTPError, ConnectionError, Exception generica). Se una chiamata fallisce, la dashboard:
1. Registra l'errore nel pannello "Salute delle API" con il messaggio esatto.
2. Cade automaticamente sul dato simulato per quella specifica fonte.
3. Mostra gli altri dati normalmente — un'API giù non blocca il resto della dashboard.

**D: Come funziona il caching?**
R: La dashboard usa `@st.cache_data` di Streamlit, che salva il risultato di ogni funzione di fetch in memoria. Il parametro `ttl` (Time To Live) definisce per quanti secondi il dato viene considerato valido prima di richiedere un refresh. Questo evita di chiamare le API ad ogni interazione dell'utente.

**D: Cos'è GeoPandas e come viene usato?**
R: GeoPandas è una libreria Python che estende Pandas aggiungendo supporto per dati geografici. Nella dashboard viene usata per:
1. Caricare il file GeoJSON dei confini brasiliani come DataFrame spaziale.
2. Eseguire un "spatial join" (unione spaziale) tra i focolari NASA (punti lat/lon) e gli stati brasiliani (poligoni), per sapere a quale stato appartiene ogni incendio.
3. Renderizzare la mappa con Matplotlib colorando ogni stato per produzione.

**D: Perché alcuni grafici usano Matplotlib e altri Plotly?**
R: Plotly è usato per la maggior parte dei grafici perché produce visualizzazioni interattive (hover, zoom, pan) direttamente nel browser. Matplotlib viene usato per le mappe degli incendi perché permette di gestire più layer (coropleth + scatter points) con maggiore controllo sulla renderizzazione, e perché GeoPandas integra nativamente con Matplotlib per i plot geografici.

**D: Cosa sono i "sacchi da 60 kg" e perché sono l'unità di misura standard?**
R: Il sacco da 60 kg (noto come "bag" nel commercio internazionale) è l'unità di misura standard nel mercato del caffè verde, stabilita storicamente da quando il caffè veniva fisicamente trasportato in sacchi di iuta. Tutti i dati USDA e CONAB sono espressi in migliaia di sacchi da 60 kg. La conversione da Metric Ton a sacchi è: 1 MT = 16.667 sacchi.

**D: Cosa significa "marketing year" per il caffè brasiliano?**
R: Il marketing year (anno commerciale) per il caffè brasiliano va da **Aprile a Marzo** dell'anno successivo. Questo perché il raccolto principale in Brasile avviene tra Maggio e Settembre, e l'anno commerciale inizia appena prima per catturare l'intera stagione. Tutti i dati USDA usano questa convenzione — il marketing year 2024 copre Aprile 2024-Marzo 2025.

**D: Cosa è il "ciclo biennale" della produzione brasiliana?**
R: Le piante di caffè Arabica hanno un ciclo naturale di alternanza produttiva: un anno producono abbondantemente (anno "on"), l'anno successivo producono meno perché hanno esaurito le riserve energetiche (anno "off"). Questo fenomeno è visibile chiaramente nei grafici di produzione come oscillazione regolare tra anni dispari e pari. Il Brasile ha lavorato per mitigarlo tramite irrigazione e pratiche agronomiche avanzate, ma il ciclo persiste.

---

### Domande su ENSO e Clima

**D: El Niño o La Niña — qual è peggio per il caffè brasiliano?**
R: Entrambi causano problemi, ma di tipo diverso. El Niño porta siccità nel Centro-Ovest e nell'Amazzonia (meno piogge durante la fioritura → rese inferiori). La Niña porta eccesso di piogge nel Sud (che causa malattie fungine nelle piantagioni di Paraná) e siccità nel Nord-Est. Statisticamente, gli anni di El Niño coincidono spesso con picchi di prezzo dell'Arabica perché il Brasile è il maggior produttore mondiale.

**D: Come si collega il grafico ENSO ai prezzi del caffè?**
R: La correlazione esiste ma con un ritardo di 6-18 mesi: gli effetti climatici durante la fioritura (Settembre-Novembre) si manifestano sul raccolto nella primavera-estate successiva (Maggio-Settembre), e sui prezzi ancora qualche mese dopo una volta che il mercato prende atto della produzione effettiva. Questo ritardo rende il monitoraggio ENSO anticipatorio rispetto ai mercati.

**D: Perché usate sia ONI che SOI? Non basta uno?**
R: L'ONI misura la componente oceanica dell'ENSO (la temperatura del mare), mentre il SOI misura la risposta atmosferica. Possono essere temporaneamente discordanti durante le fasi di sviluppo o dissipazione di un evento. Quando sono concordanti (evento "accoppiato"), la previsione degli impatti agricoli è molto più affidabile. Usarli insieme è la pratica standard della climatologia applicata all'agricoltura.

---

## PARTE 5 — GLOSSARIO TECNICO

| Termine | Definizione |
|---------|-------------|
| **API** | Application Programming Interface — sistema che permette a due software di comunicare. |
| **AIS** | Automatic Identification System — sistema di tracciamento delle navi commerciali via radio VHF. |
| **Arabica** | Coffea arabica — varietà di caffè premium, coltivata in altitudine, con 60-70% della produzione mondiale. |
| **Robusta (Conilon)** | Coffea canephora — varietà più resistente, con maggiore contenuto di caffeina, usata in miscele ed espresso. |
| **Cache TTL** | Time To Live — periodo di validità di un dato in memoria prima di richiedere un aggiornamento. |
| **ENSO** | El Niño-Southern Oscillation — fenomeno climatico ciclico del Pacifico che altera le precipitazioni globali. |
| **FRP** | Fire Radiative Power — misura dell'energia termica emessa da un incendio in Megawatt. |
| **GeoJSON** | Formato standard per dati geografici vettoriali (punti, linee, poligoni) in formato JSON. |
| **GeoPandas** | Libreria Python per analisi di dati geografici, estensione di Pandas. |
| **ICE** | Intercontinental Exchange — borsa commodity dove si negoziano i futures del caffè. |
| **Marketing Year** | Anno commerciale agricolo, che non coincide con l'anno solare. |
| **MMSI** | Maritime Mobile Service Identity — identificativo univoco di ogni nave (9 cifre). |
| **ONI** | Oceanic Niño Index — misura l'anomalia termica del Pacifico Centrale. |
| **PSD** | Production, Supply and Distribution — database USDA di riferimento per le commodity agricole. |
| **Pink Sheet** | Nome colloquiale del dataset mensile prezzi commodity della Banca Mondiale. |
| **QCL** | Crops and Livestock Primary — dataset FAOSTAT per colture e produzione zootecnica. |
| **Robusta** | Vedi Conilon. |
| **Sacco 60 kg** | Unità di misura standard internazionale per il caffè verde. |
| **SOG** | Speed Over Ground — velocità della nave rispetto al fondale in nodi. |
| **SOI** | Southern Oscillation Index — misura la differenza di pressione atmosferica tra Tahiti e Darwin. |
| **Streamlit** | Framework Python per creare dashboard web interattive con puro codice Python. |
| **VIIRS** | Visible Infrared Imaging Radiometer Suite — sensore satellitare NASA per rilevamento termico. |
| **WebSocket** | Protocollo di comunicazione bidirezionale persistente per dati in streaming. |

---

## PARTE 6 — ARCHITETTURA TECNICA IN SINTESI

```
app_standalone.py
│
├── COSTANTI & CONFIG          Endpoint URL, API key, coordinate, colori
├── FUNZIONI DI FETCH          Una per ogni fonte dati, con @st.cache_data
│   ├── fetch_prices()         World Bank + ER-API
│   ├── fetch_enso_data()      NOAA ONI
│   ├── fetch_soi_data()       NOAA SOI
│   ├── fetch_climate()        Modello interno basato su ONI
│   ├── fetch_firms_data()     NASA FIRMS
│   ├── fetch_usda()           USDA PSD (per-year keyed fetch)
│   ├── fetch_faostat()        FAOSTAT via libreria Python
│   ├── fetch_conab_states()   File CSV da fetch_conab.py
│   ├── build_port_history()   Modello interno (stima da clima)
│   └── _fetch_ais_snapshot()  AISStream.io WebSocket (async)
├── FUNZIONI DI RENDERING      Una per ogni scheda (tab)
│   ├── render_tab_1()         Clima & ENSO
│   ├── render_tab_2()         Incendi (Matplotlib + Plotly)
│   ├── render_tab_3()         Navi & Porti
│   ├── render_tab_4()         Prezzi
│   ├── render_tab_5()         Produttività
│   └── render_tab_6()         Precipitazioni
└── main()                     Orchestrazione: fetch → sidebar → tabs

fetch_conab.py (script separato)
│
├── Scraping pagina CONAB       BeautifulSoup + requests
├── Download file Excel          Link dinamico estratto dalla pagina
├── Parsing Excel               Ricerca intelligente colonne (d) e (f)
└── Export CSV                  data_sources/conab/conab_data.csv
```
