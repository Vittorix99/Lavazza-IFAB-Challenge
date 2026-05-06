#!/usr/bin/env bash
# setup_doppler.sh — Configura Doppler come key vault per il progetto.
# Esegui una sola volta su ogni nuovo computer.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/lavazza-coffee-agent/.env"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${CYAN}▶${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "${RED}✗${NC} $*"; exit 1; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║      Lavazza — Setup Doppler Vault       ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Installa CLI ──────────────────────────────────────────────────────────
if ! command -v doppler &>/dev/null; then
    info "Installo Doppler CLI..."
    brew install dopplerhq/cli/doppler
fi
ok "Doppler CLI $(doppler --version) trovata."

# ── 2. Controlla login ───────────────────────────────────────────────────────
if ! doppler me &>/dev/null; then
    echo ""
    err "Non sei autenticato su Doppler. Esegui prima nel tuo terminale:

    doppler login

  Poi riesegui questo script."
fi
DOPPLER_USER=$(doppler me --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('email',''))" 2>/dev/null || echo "?")
ok "Autenticato come $DOPPLER_USER"

# ── 3. Crea progetto se non esiste ───────────────────────────────────────────
PROJECT="lavazza-ifab"
info "Verifico progetto '$PROJECT' su Doppler..."
if ! doppler projects get "$PROJECT" &>/dev/null; then
    doppler projects create "$PROJECT" --description "Lavazza IFAB Coffee Intelligence"
    ok "Progetto '$PROJECT' creato."
else
    ok "Progetto '$PROJECT' già esistente."
fi

# ── 4. Configura repo locale ─────────────────────────────────────────────────
cd "$REPO_ROOT"
doppler setup --project "$PROJECT" --config dev --no-interactive
ok "Repository configurato → progetto: $PROJECT / config: dev"

# ── 5. Carica segreti da .env ────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
    info "Carico segreti da lavazza-coffee-agent/.env su Doppler..."
    ARGS=()
    while IFS= read -r line; do
        # salta righe vuote e commenti
        [[ -z "$line" || "$line" == \#* ]] && continue
        [[ "$line" == *"="* ]] || continue
        key="${line%%=*}"
        val="${line#*=}"
        # salta chiavi vuote o con spazi
        [[ -z "$key" || "$key" == *" "* ]] && continue
        ARGS+=("$key=$val")
    done < "$ENV_FILE"

    if [[ ${#ARGS[@]} -gt 0 ]]; then
        doppler secrets set "${ARGS[@]}"
        ok "${#ARGS[@]} segreti caricati su Doppler."
    else
        warn "Nessun segreto trovato nel file .env."
    fi
else
    warn "File $ENV_FILE non trovato — carica i segreti manualmente con:"
    warn "  doppler secrets set CHIAVE=VALORE"
fi

# ── 6. Riepilogo ─────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════"
ok "Setup completato. Da ora in poi:"
echo ""
echo "  Avvio dashboard:"
echo "    ${CYAN}doppler run -- streamlit run lavazza-coffee-agent/dashboard/app.py${NC}"
echo ""
echo "  Oppure usa lo script (gestisce Doppler automaticamente):"
echo "    ${CYAN}./scripts/start.sh${NC}"
echo ""
echo "  Su un nuovo computer, esegui di nuovo questo script:"
echo "    ${CYAN}./scripts/setup_doppler.sh${NC}"
echo ""
echo "  Aggiungi/modifica un segreto:"
echo "    ${CYAN}doppler secrets set NOME_VARIABILE=valore${NC}"
echo ""
echo "  Visualizza tutti i segreti:"
echo "    ${CYAN}doppler secrets${NC}"
echo "══════════════════════════════════════════════════════"
echo ""
