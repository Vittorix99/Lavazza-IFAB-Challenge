#!/usr/bin/env bash
set -euo pipefail

# Clears all documents in the target MongoDB database except one collection.
# Defaults are aligned with this repository's docker-compose setup.
#
# Usage:
#   scripts/clear_mongo_except_raw_geo.sh
#   scripts/clear_mongo_except_raw_geo.sh --yes
#   scripts/clear_mongo_except_raw_geo.sh --keep raw_geo --db lavazza_ifab --yes
#   scripts/clear_mongo_except_raw_geo.sh --dry-run

KEEP_COLLECTION="raw_geo"
DB_NAME="${MONGO_APP_DATABASE:-${MONGODB_DB:-}}"
COMPOSE_FILE="docker/compose.yml"
MONGO_SERVICE="mongo"
ASSUME_YES=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep)
      KEEP_COLLECTION="${2:-}"
      shift 2
      ;;
    --db)
      DB_NAME="${2:-}"
      shift 2
      ;;
    --yes|-y)
      ASSUME_YES=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --help|-h)
      sed -n '1,20p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${KEEP_COLLECTION}" ]]; then
  echo "KEEP collection cannot be empty." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found in PATH." >&2
  exit 1
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "Compose file not found: ${COMPOSE_FILE}" >&2
  exit 1
fi

if ! docker compose -f "${COMPOSE_FILE}" ps --status running "${MONGO_SERVICE}" >/dev/null 2>&1; then
  echo "Mongo service '${MONGO_SERVICE}' is not running. Start it first (e.g. docker compose up -d mongo)." >&2
  exit 1
fi

if [[ -z "${DB_NAME}" ]]; then
  DB_NAME="$(docker compose -f "${COMPOSE_FILE}" exec -T "${MONGO_SERVICE}" sh -lc 'printf "%s" "${MONGO_APP_DATABASE:-}"' || true)"
fi

if [[ -z "${DB_NAME}" ]]; then
  echo "Database name not found. Set MONGO_APP_DATABASE (or use --db)." >&2
  exit 1
fi

echo "Target DB: ${DB_NAME}"
echo "Collection kept: ${KEEP_COLLECTION}"
if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "Mode: DRY RUN (no deletion)"
fi

if [[ "${ASSUME_YES}" -ne 1 ]]; then
  read -r -p "Proceed and clear all other collections? [y/N] " reply
  case "${reply}" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 0 ;;
  esac
fi

MONGO_JS="$(cat <<'JS'
const dbName = process.env.DB_NAME;
const keep = process.env.KEEP_COLLECTION;
const dryRun = process.env.DRY_RUN === '1';
if (!dbName) throw new Error('Missing DB_NAME');
if (!keep) throw new Error('Missing KEEP_COLLECTION');

const target = db.getSiblingDB(dbName);
const names = target
  .getCollectionNames()
  .filter((name) => !name.startsWith('system.') && name !== keep);

print(`[info] db=${dbName}`);
print(`[info] keep=${keep}`);
print(`[info] affected_collections=${names.length}`);

if (!names.length) {
  print('[done] Nothing to clear.');
  quit(0);
}

let totalDeleted = 0;
for (const name of names) {
  if (dryRun) {
    const count = target.getCollection(name).countDocuments({});
    print(`[dry-run] ${name}: would delete ${count} documents`);
    continue;
  }
  const result = target.getCollection(name).deleteMany({});
  const deleted = result && typeof result.deletedCount === 'number' ? result.deletedCount : 0;
  totalDeleted += deleted;
  print(`[cleared] ${name}: deleted ${deleted}`);
}

if (dryRun) {
  print('[done] Dry-run complete.');
} else {
  print(`[done] Cleared ${names.length} collections. Total deleted documents: ${totalDeleted}.`);
}
JS
)"

docker compose -f "${COMPOSE_FILE}" exec -T \
  -e DB_NAME="${DB_NAME}" \
  -e KEEP_COLLECTION="${KEEP_COLLECTION}" \
  -e DRY_RUN="${DRY_RUN}" \
  "${MONGO_SERVICE}" \
  sh -lc 'mongosh --quiet --host 127.0.0.1 --port 27017 --username "$MONGO_APP_USERNAME" --password "$MONGO_APP_PASSWORD" --authenticationDatabase "$DB_NAME" --eval "$0"' "${MONGO_JS}"

