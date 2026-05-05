# Service Endpoints — Lavazza Coffee Intelligence

---

## Servizi cloud (sempre attivi, nessun container locale)

### MongoDB Atlas

- **URI:** iniettata da Doppler come `MONGODB_URI`
- **Database:** `lavazza_ifab`
- **Cluster:** `lavazzacluster.pczp7pp.mongodb.net`
- **Utente DB:** `highdreams290_db_user`
- **Collections:** `raw_geo`, `raw_crops`, `raw_prices`, `raw_environment`, `ingestion_log`, `agent_runs`, `coffee_regions`
- **Admin:** https://cloud.mongodb.com → progetto Lavazza

> Accesso richiede IP in whitelist. Lo script `start.sh` lo aggiorna automaticamente.
> Per aggiungere l'IP manualmente: `doppler run -- .venv/bin/python3 scripts/atlas_whitelist_ip.py`

### Qdrant Cloud

- **URL:** iniettato da Doppler come `QDRANT_URL`
- **Cluster:** `eu-west-2` (AWS)
- **Collections:** `geo_texts`, `crops_texts`, `reports_archive`
- **Admin:** https://cloud.qdrant.io

---

## Servizi Docker locali

Avviati con `./scripts/start.sh` o `cd docker && docker compose up -d n8n ais-port-probe`.

### n8n

- **URL:** http://localhost:5678
- **Funzione:** orchestrazione workflow di ingestion (13 connettori dati)
- **Dati persistenti:** volume Docker `n8n_data`

### ais-port-probe

- **URL interno:** `http://ais-port-probe:8080/snapshot` (solo rete Docker interna)
- **Funzione:** microservizio AIS per congestionamento porti brasiliani
- **Non esposto** sulla macchina host

---

## Porte locali in uso

| Porta | Servizio |
|-------|----------|
| 5678 | n8n editor |

---

## Note operative

- MongoDB e Qdrant **non hanno container Docker locali** — tutto gira su cloud.
- I segreti di accesso (URI, API key, password) sono in **Doppler** → progetto `lavazza-ifab` / config `dev`.
- Per ispezionare MongoDB usa [MongoDB Compass](https://www.mongodb.com/products/compass) con la stringa `MONGODB_URI` da Doppler.
- Per ispezionare Qdrant usa la dashboard web su https://cloud.qdrant.io.
- Se cambi una credenziale, aggiornala su Doppler: `doppler secrets set CHIAVE=nuovo_valore`.
