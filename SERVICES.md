# Service Endpoints

Tutti i servizi definiti in `docker/compose.yml` sono esposti solo in locale su `127.0.0.1`, quindi gli indirizzi sono raggiungibili solo dalla macchina host.

## Browser / HTTP

- n8n editor: `http://localhost:5678`
- n8n webhook base URL: `http://localhost:5678/`
- Qdrant REST API: `http://localhost:6333`

## Client dedicati

- MongoDB: `mongodb://localhost:27017`
  - Database applicativo: `lavazza_ifab`
  - Credenziali: vedi `docker/.env`
- Qdrant gRPC: `localhost:6334`

## Note

- MongoDB non espone una UI web in questo `compose`; per ispezionarlo usa MongoDB Compass, `mongosh` o un client equivalente.
- Se cambi porte o credenziali in `docker/.env`, aggiorna anche questo file.
