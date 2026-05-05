"""
atlas_whitelist_ip.py — Aggiunge l'IP pubblico corrente alla whitelist MongoDB Atlas.

━━━ MODO 1 — Service Account (raccomandato, non-interattivo) ━━━
    Crea un Service Account su Atlas:
      Organization → Access Manager → Applications → Service Accounts → Create
      Nome: lavazza-dev | Ruolo org: Organization Member
      Poi: Project → Access Manager → Service Accounts → Add → ruolo: Project Network Access Admin
      Genera il client secret → copia Client ID e Client Secret

    Aggiungi a lavazza-coffee-agent/.env:
      ATLAS_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxx
      ATLAS_CLIENT_SECRET=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
      ATLAS_PROJECT_ID=xxxxxxxxxxxxxxxxxxxx  ← Atlas → Project Settings → Project ID

    Usa:
      python scripts/atlas_whitelist_ip.py

━━━ MODO 2 — API Keys (alternativa) ━━━
    Organization → Access Manager → API Keys → Create
    Ruolo: Project Network Access Admin

    Aggiungi a lavazza-coffee-agent/.env:
      ATLAS_PUBLIC_KEY=xxxxxxxx
      ATLAS_PRIVATE_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
      ATLAS_PROJECT_ID=xxxxxxxxxxxxxxxxxxxx

    Usa:
      python scripts/atlas_whitelist_ip.py --apikey

━━━ MODO 3 — Solo stampa IP (istruzioni manuali) ━━━
    python scripts/atlas_whitelist_ip.py --manual
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime

try:
    import requests
    from requests.auth import HTTPDigestAuth
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

ATLAS_API    = "https://cloud.mongodb.com/api/atlas/v2"
ATLAS_TOKEN  = "https://cloud.mongodb.com/api/oauth/token"
ENV_PATH     = os.path.join(os.path.dirname(__file__), "..", "lavazza-coffee-agent", ".env")


# ── Utilities ────────────────────────────────────────────────────────────────

def get_public_ip() -> str:
    with urllib.request.urlopen("https://api.ipify.org", timeout=5) as r:
        return r.read().decode().strip()


def load_env() -> None:
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


def require_env(*names: str) -> dict:
    load_env()
    values = {n: os.environ.get(n, "") for n in names}
    missing = [n for n, v in values.items() if not v]
    if missing:
        print(f"\n✗ Variabili mancanti in lavazza-coffee-agent/.env: {', '.join(missing)}")
        print("  Leggi le istruzioni in cima allo script.")
        sys.exit(1)
    return values


# ── Modo 1 — Service Account OAuth ──────────────────────────────────────────

def get_oauth_token(client_id: str, client_secret: str) -> str:
    if not HAS_REQUESTS:
        print("Installa requests:  pip install requests")
        sys.exit(1)
    resp = requests.post(
        ATLAS_TOKEN,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"✗ OAuth fallito ({resp.status_code}): {resp.text}")
        sys.exit(1)
    return resp.json()["access_token"]


def add_via_service_account(ip: str, comment: str) -> None:
    creds = require_env("ATLAS_CLIENT_ID", "ATLAS_CLIENT_SECRET", "ATLAS_PROJECT_ID")
    print("Ottengo token OAuth...")
    token = get_oauth_token(creds["ATLAS_CLIENT_ID"], creds["ATLAS_CLIENT_SECRET"])

    url     = f"{ATLAS_API}/groups/{creds['ATLAS_PROJECT_ID']}/accessList"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept":        "application/vnd.atlas.2023-01-01+json",
        "Content-Type":  "application/json",
    }
    resp = requests.post(url, json=[{"ipAddress": ip, "comment": comment}], headers=headers, timeout=10)

    if resp.status_code in (200, 201):
        print(f"✓ IP {ip} aggiunto alla whitelist Atlas.")
    elif resp.status_code == 409:
        print(f"✓ IP {ip} era già in whitelist.")
    else:
        print(f"✗ Errore {resp.status_code}: {resp.text}")
        sys.exit(1)


# ── Modo 2 — API Keys (Digest) ───────────────────────────────────────────────

def add_via_apikey(ip: str, comment: str) -> None:
    if not HAS_REQUESTS:
        print("Installa requests:  pip install requests")
        sys.exit(1)
    creds = require_env("ATLAS_PUBLIC_KEY", "ATLAS_PRIVATE_KEY", "ATLAS_PROJECT_ID")

    url     = f"{ATLAS_API}/groups/{creds['ATLAS_PROJECT_ID']}/accessList"
    headers = {"Accept": "application/vnd.atlas.2023-01-01+json", "Content-Type": "application/json"}
    resp    = requests.post(
        url,
        json=[{"ipAddress": ip, "comment": comment}],
        auth=HTTPDigestAuth(creds["ATLAS_PUBLIC_KEY"], creds["ATLAS_PRIVATE_KEY"]),
        headers=headers,
        timeout=10,
    )
    if resp.status_code in (200, 201):
        print(f"✓ IP {ip} aggiunto alla whitelist Atlas.")
    elif resp.status_code == 409:
        print(f"✓ IP {ip} era già in whitelist.")
    else:
        print(f"✗ Errore {resp.status_code}: {resp.text}")
        sys.exit(1)


# ── Modo 3 — Manuale ────────────────────────────────────────────────────────

def print_manual(ip: str) -> None:
    print(f"""
╔══════════════════════════════════════════════════════╗
║         MongoDB Atlas — Aggiungi IP manualmente      ║
╚══════════════════════════════════════════════════════╝

IP pubblico corrente:  {ip}

  1. Vai su  https://cloud.mongodb.com
  2. Progetto Lavazza → Security → Network Access
  3. [+ ADD IP ADDRESS]
  4. Incolla: {ip}
  5. Commento: "dev - {datetime.now().strftime('%Y-%m-%d')}"
  6. [Confirm] — attendi ~30 secondi

Per automatizzare: configura il Service Account (vedi --help)
""")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Aggiunge l'IP corrente alla whitelist MongoDB Atlas")
    group  = parser.add_mutually_exclusive_group()
    group.add_argument("--apikey", action="store_true", help="Usa API Keys da .env (ATLAS_PUBLIC_KEY + ATLAS_PRIVATE_KEY)")
    group.add_argument("--manual", action="store_true", help="Stampa solo IP e istruzioni manuali")
    parser.add_argument("--comment", default="", help="Commento whitelist (default: 'dev - YYYY-MM-DD')")
    args = parser.parse_args()

    print("Recupero IP pubblico...")
    try:
        ip = get_public_ip()
        print(f"IP corrente: {ip}")
    except Exception as e:
        print(f"✗ Impossibile recuperare IP: {e}")
        sys.exit(1)

    comment = args.comment or f"dev - {datetime.now().strftime('%Y-%m-%d')}"

    if args.manual:
        print_manual(ip)
    elif args.apikey:
        add_via_apikey(ip, comment)
    else:
        # default: Service Account
        add_via_service_account(ip, comment)


if __name__ == "__main__":
    main()
