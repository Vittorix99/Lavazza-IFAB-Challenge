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

# ── Docker .env ──────────────────────────────────────────────────────────────
# Docker Compose legge solo docker/.env: se manca, lo creiamo dai default locali
# e, quando possibile, sovrascriviamo con i secret Doppler disponibili.
if [[ ! -f "$DOCKER_DIR/.env" ]]; then
    [[ -f "$DOCKER_DIR/.env.example" ]] || err "Manca docker/.env.example"

    warn "Manca docker/.env — lo creo da docker/.env.example"
    cp "$DOCKER_DIR/.env.example" "$DOCKER_DIR/.env"

    if grep -q "CHANGE-ME-run-openssl-rand-hex-32" "$DOCKER_DIR/.env" 2>/dev/null; then
        N8N_KEY="$(openssl rand -hex 32)"
        sed -i '' "s/CHANGE-ME-run-openssl-rand-hex-32/$N8N_KEY/" "$DOCKER_DIR/.env"
    fi

    if [[ "$USE_DOPPLER" == true ]]; then
        TMP_DOPPLER_ENV="$(mktemp)"
        if doppler secrets download --no-file --format env > "$TMP_DOPPLER_ENV"; then
            while IFS= read -r line; do
                [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
                key="${line%%=*}"
                tmp_file="$(mktemp)"
                awk -F= -v key="$key" '$1 != key { print }' "$DOCKER_DIR/.env" > "$tmp_file"
                mv "$tmp_file" "$DOCKER_DIR/.env"
                printf '%s\n' "$line" >> "$DOCKER_DIR/.env"
            done < "$TMP_DOPPLER_ENV"
        else
            warn "Non riesco a scaricare i secret Doppler per docker/.env — uso i default locali."
        fi
        rm -f "$TMP_DOPPLER_ENV"
    fi

    chmod 600 "$DOCKER_DIR/.env"
    ok "Creato docker/.env"
fi

# ── Validazione Qdrant Cloud ─────────────────────────────────────────────────
if [[ -f "$AGENT_DIR/.env" ]]; then
    if grep -q '^QDRANT_URL=.*cloud\.qdrant\.io' "$AGENT_DIR/.env" \
        && ! grep -q '^QDRANT_API_KEY=.\+' "$AGENT_DIR/.env"; then
        err "QDRANT_API_KEY mancante in Doppler/.env — Qdrant Cloud risponde 403 senza API key."
    fi
fi

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

# ── Test MongoDB Atlas per demo ──────────────────────────────────────────────
echo ""
info "Test connessione MongoDB Atlas..."
MONGO_DEBUG_CMD=".venv/bin/python3 $REPO_ROOT/scripts/debug_mongo.py --summary"
if $DOPPLER_PREFIX $MONGO_DEBUG_CMD; then
    ok "MongoDB Atlas raggiungibile e dati raw leggibili."
else
    warn "Test MongoDB Atlas fallito — controlla MONGODB_URI, whitelist IP e database."
fi

# ── Debug Qdrant Cloud opzionale ─────────────────────────────────────────────
if [[ "${QDRANT_DEBUG:-}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
    echo ""
    info "Debug Qdrant Cloud..."
    QDRANT_DEBUG_CMD=".venv/bin/python3 $REPO_ROOT/scripts/debug_qdrant.py --debug"
    if $DOPPLER_PREFIX $QDRANT_DEBUG_CMD; then
        ok "Qdrant raggiungibile."
    else
        warn "Debug Qdrant fallito — controlla QDRANT_URL e QDRANT_API_KEY."
    fi
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
