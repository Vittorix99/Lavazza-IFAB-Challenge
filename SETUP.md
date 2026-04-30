# Setup — Lavazza Coffee Intelligence

Guida per far girare il progetto su un nuovo computer (macOS / Linux).

---

## Architettura servizi

| Servizio | Dove gira | Note |
|----------|-----------|------|
| **MongoDB** | Atlas Cloud | nessun container locale necessario |
| **Qdrant** | Qdrant Cloud | nessun container locale necessario |
| **n8n** | Docker locale | http://localhost:5678 |
| **ais-port-probe** | Docker locale | rete interna, non esposto |

I segreti di accesso (API key, URI, password) sono gestiti su **Doppler** — nessun file `.env` da condividere manualmente.

---

## Prerequisiti

| Tool | Come installare |
|------|-----------------|
| Docker Desktop | https://docs.docker.com/get-docker/ |
| Python 3.11+ | `brew install python` |
| Git | incluso su macOS |

---

## Setup su un nuovo computer (3 passi)

### Passo 1 — Clona il repo

```bash
git clone <URL-del-repo>
cd Lavazza-IFAB-Challenge
```

### Passo 2 — Login Doppler e setup segreti

I segreti sono nel vault Doppler del progetto (`lavazza-ifab`). Fai il login una sola volta per computer, poi lo script fa tutto il resto:

```bash
doppler login                  # apre il browser — accedi con l'account del team
./scripts/setup_doppler.sh     # installa CLI se manca, configura il repo, scarica i segreti
```

> Se non sei ancora stato invitato al progetto Doppler, chiedi a chi ha già accesso di andare su
> https://dashboard.doppler.com → progetto **lavazza-ifab** → **Team → Invite** con la tua email.

### Passo 3 — Avvia tutto

```bash
./scripts/start.sh
```

Lo script fa in automatico:
1. Rileva Doppler e inietta i segreti
2. Aggiunge il tuo IP alla whitelist MongoDB Atlas
3. Avvia Docker (n8n + ais-port-probe)
4. Crea il virtual environment Python se non esiste
5. Avvia la Dashboard → http://localhost:8501

Per fermare i container:
```bash
./scripts/stop.sh
```

---

## Import workflow n8n (solo la prima volta su un nuovo PC)

1. Apri http://localhost:5678
2. **Settings → Import workflow**
3. Importa i 13 sub-workflow da `docker/local-files/workflows/split/`
4. Importa il master: `docker/local-files/workflows/Lavazza-MASTER-RUN.json`
5. Aggiorna i `workflowId` nel master con i nuovi ID assegnati da n8n
6. Re-inserisci le credenziali API (OpenAI, NASA, USDA, AISSTREAM) nell'editor n8n → Credentials

---

## Gestione segreti — riferimento rapido

```bash
doppler secrets                              # visualizza tutti i segreti
doppler secrets set CHIAVE=valore            # aggiunge o aggiorna un segreto
doppler secrets delete CHIAVE               # rimuove un segreto
doppler run -- python3 script.py            # esegui uno script con i segreti iniettati
```

| Segreto | Cosa è |
|---------|--------|
| `ANTHROPIC_API_KEY` | Claude API — https://console.anthropic.com |
| `OPENAI_API_KEY` | OpenAI API — https://platform.openai.com |
| `MONGODB_URI` | Stringa connessione MongoDB Atlas |
| `MONGODB_DB` | Nome database (`lavazza_ifab`) |
| `QDRANT_URL` | URL cluster Qdrant Cloud |
| `QDRANT_API_KEY` | API key Qdrant Cloud |
| `ATLAS_CLIENT_ID` | Service account Atlas (whitelist IP) |
| `ATLAS_CLIENT_SECRET` | Service account Atlas (whitelist IP) |
| `ATLAS_PROJECT_ID` | Project ID MongoDB Atlas |

---

## Fallback senza Doppler

Se Doppler non è disponibile, `start.sh` legge automaticamente dai file `.env` locali.

```bash
cp lavazza-coffee-agent/.env.example lavazza-coffee-agent/.env   # segreti agenti
cp docker/.env.example docker/.env                                # variabili n8n/Docker
# compila i valori CHANGE-ME
```

---

## Troubleshooting

| Errore | Causa | Soluzione |
|--------|-------|-----------|
| `Authentication failed` su Atlas | IP non in whitelist | `doppler run -- .venv/bin/python3 scripts/atlas_whitelist_ip.py` |
| `bad auth` su Atlas | Password DB scaduta | Atlas → Database Access → Edit user → Autogenerate password → aggiorna su Doppler |
| `USER_CANNOT_ACCESS_GROUP` whitelist | Service account non nel progetto | Atlas → Access Manager → Service Accounts → Add existing |
| `Connection refused` Qdrant | URL/API key errati | `doppler secrets set QDRANT_URL=...` |
| `ModuleNotFoundError` | Venv non attivo | `source lavazza-coffee-agent/.venv/bin/activate` |
| Doppler: `project not configured` | Setup non eseguito | `./scripts/setup_doppler.sh` |
| n8n non parte | Docker non avviato | Apri Docker Desktop, poi `./scripts/start.sh` |
