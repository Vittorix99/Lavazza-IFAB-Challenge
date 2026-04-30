#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_DIR="$REPO_ROOT/lavazza-coffee-agent"
DOCKER_DIR="$REPO_ROOT/docker"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
info() { echo -e "${CYAN}▶${NC}  $*"; }
err()  { echo -e "${RED}✗${NC} $*"; exit 1; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Lavazza Coffee Intelligence — START    ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Prerequisiti ─────────────────────────────────────────────────────────────
command -v docker  >/dev/null 2>&1 || err "Docker non trovato. Installa Docker Desktop."
command -v python3 >/dev/null 2>&1 || err "Python 3 non trovato."

# ── Sorgente segreti: Doppler o .env ─────────────────────────────────────────
USE_DOPPLER=false
DOPPLER_PREFIX=""

if command -v doppler &>/dev/null && doppler me &>/dev/null 2>&1; then
    # verifica che il progetto sia configurato in questo repo
    if doppler secrets download --no-file --format env &>/dev/null 2>&1; then
        USE_DOPPLER=true
        DOPPLER_PREFIX="doppler run --"
        DOPPLER_USER=$(doppler me --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('email','?'))" 2>/dev/null || echo "?")
        ok "Segreti: Doppler ($DOPPLER_USER)"
    else
        warn "Doppler installato ma progetto non configurato in questo repo."
        warn "Esegui: ./scripts/setup_doppler.sh"
    fi
fi

if [[ "$USE_DOPPLER" == false ]]; then
    [[ -f "$AGENT_DIR/.env" ]] || err "Manca lavazza-coffee-agent/.env e Doppler non è configurato. Esegui ./scripts/setup_doppler.sh"
    if grep -q "CHANGE-ME" "$AGENT_DIR/.env" 2>/dev/null; then
        warn ".env ha valori 'CHANGE-ME' non compilati."
    fi
    ok "Segreti: file lavazza-coffee-agent/.env"
fi

[[ -f "$DOCKER_DIR/.env" ]] || err "Manca docker/.env — copia docker/.env.example e compila."

# ── Whitelist IP su Atlas ─────────────────────────────────────────────────────
echo ""
info "Aggiorno IP sulla whitelist MongoDB Atlas..."
WHITELIST_CMD="$AGENT_DIR/.venv/bin/python3 $REPO_ROOT/scripts/atlas_whitelist_ip.py"
if $DOPPLER_PREFIX $WHITELIST_CMD 2>/dev/null; then
    ok "IP aggiunto alla whitelist Atlas."
else
    warn "Whitelist Atlas fallita — aggiungila manualmente se la connessione non funziona."
fi

# ── Docker: solo n8n + ais-port-probe ────────────────────────────────────────
# MongoDB → Atlas Cloud  |  Qdrant → Qdrant Cloud  →  container locali non necessari
echo ""
info "Avvio servizi Docker (n8n, ais-port-probe)..."
cd "$DOCKER_DIR"
docker compose up -d n8n ais-port-probe

echo ""
ok "n8n      → http://localhost:5678"
ok "MongoDB  → Atlas Cloud"
ok "Qdrant   → Qdrant Cloud"

# ── Venv Python ──────────────────────────────────────────────────────────────
echo ""
info "Controllo virtual environment Python..."
cd "$AGENT_DIR"

if [[ ! -f ".venv/bin/activate" ]]; then
    info "Creo .venv e installo dipendenze..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -q -r requirements.txt
    ok "Dipendenze installate."
else
    source .venv/bin/activate
    ok "Venv trovato."
fi

# ── Avvia Dashboard ───────────────────────────────────────────────────────────
echo ""
info "Avvio Dashboard Streamlit..."
echo "   Premi Ctrl+C per fermare (i container Docker rimangono attivi)."
echo ""

if [[ "$USE_DOPPLER" == true ]]; then
    doppler run -- .venv/bin/streamlit run dashboard/app.py
else
    streamlit run dashboard/app.py
fi
