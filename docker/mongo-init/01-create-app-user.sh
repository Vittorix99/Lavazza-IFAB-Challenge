#!/bin/bash
set -euo pipefail

: "${MONGO_APP_DATABASE:?MONGO_APP_DATABASE is required}"
: "${MONGO_APP_USERNAME:?MONGO_APP_USERNAME is required}"
: "${MONGO_APP_PASSWORD:?MONGO_APP_PASSWORD is required}"

mongosh --host 127.0.0.1 \
  --port 27017 \
  --username "$MONGO_INITDB_ROOT_USERNAME" \
  --password "$MONGO_INITDB_ROOT_PASSWORD" \
  --authenticationDatabase admin <<MONGO_INIT
use ${MONGO_APP_DATABASE}
db.createUser({
  user: "${MONGO_APP_USERNAME}",
  pwd: "${MONGO_APP_PASSWORD}",
  roles: [
    { role: "readWrite", db: "${MONGO_APP_DATABASE}" }
  ]
})
MONGO_INIT
