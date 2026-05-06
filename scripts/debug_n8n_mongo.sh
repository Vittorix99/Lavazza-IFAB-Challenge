#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_DIR="$REPO_ROOT/docker"

cd "$DOCKER_DIR"

if ! docker compose ps n8n --status running >/dev/null 2>&1; then
  echo "n8n non risulta running. Avvia: ./scripts/start.sh"
  exit 1
fi

echo "== n8n env MongoDB =="
docker compose exec -T n8n sh -lc '
  if [ -n "${MONGODB_URI:-}" ]; then echo "MONGODB_URI=present"; else echo "MONGODB_URI=missing"; fi
  if [ -n "${MONGODB_DB:-}" ]; then echo "MONGODB_DB=${MONGODB_DB}"; else echo "MONGODB_DB=missing"; fi
'

echo ""
echo "== n8n -> MongoDB ping/count =="
docker compose exec -T n8n node - <<'NODE'
const uri = process.env.MONGODB_URI;
const dbName = process.env.MONGODB_DB || "lavazza_ifab";

if (!uri) {
  console.log("MONGODB_URI non presente nel container n8n.");
  console.log("Nota: i nodi MongoDB n8n possono comunque usare credenziali salvate in n8n.");
  process.exit(2);
}

async function main() {
  let mongodb;
  try {
    mongodb = require("mongodb");
  } catch (err) {
    console.log("Modulo npm 'mongodb' non disponibile nel container n8n.");
    console.log("Usa la UI n8n -> Credentials -> MongoDB account -> Test, oppure esegui scripts/debug_mongo.py lato agenti.");
    process.exit(3);
  }

  const client = new mongodb.MongoClient(uri, { serverSelectionTimeoutMS: 8000 });
  await client.connect();
  await client.db("admin").command({ ping: 1 });
  const db = client.db(dbName);
  const collections = ["raw_geo", "raw_prices", "raw_crops", "raw_environment", "ingestion_log"];
  for (const name of collections) {
    const count = await db.collection(name).countDocuments({});
    console.log(`${name}: ${count}`);
  }
  await client.close();
}

main().catch((err) => {
  console.error(`${err.name}: ${err.message}`);
  process.exit(1);
});
NODE
