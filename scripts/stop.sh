#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_DIR="$REPO_ROOT/docker"

GREEN='\033[0;32m'; NC='\033[0m'
ok() { echo -e "${GREEN}✓${NC} $*"; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Lavazza Coffee Intelligence — STOP     ║"
echo "╚══════════════════════════════════════════╝"
echo ""

cd "$DOCKER_DIR"
docker compose stop
ok "Tutti i container fermati (i dati sono preservati nei volumi Docker)."
echo ""
echo "   Per rimuovere anche i volumi (reset completo):  docker compose down -v"
echo "   Per riavviare:                                  ./scripts/start.sh"
echo ""
