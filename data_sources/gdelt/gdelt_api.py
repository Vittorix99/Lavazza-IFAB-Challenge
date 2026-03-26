"""
GDELT Brazil — Test API
========================
Recupera articoli e li mostra in una tabella, simulando
la struttura MongoDB finale (event_type e severity mostrati come NULL).
"""

import uuid
import time
import logging
from datetime import datetime, timezone

import requests
from tabulate import tabulate

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
GDELT_BASE_URL    = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_BASE_FILTER = "sourcecountry:BR"

GDELT_QUERIES = [
    f'("protesto" OR "manifestação" OR "crise política" OR "instabilidade") {GDELT_BASE_FILTER}',
    f'("greve" OR "paralisação" OR "sindicato") AND ("porto" OR "Santos" OR "Paranaguá") {GDELT_BASE_FILTER}',
    f'("política" OR "subsídio" OR "imposto") AND ("café" OR "agronegócio" OR "soja") {GDELT_BASE_FILTER}',
    f'("enchente" OR "seca" OR "queimada" OR "chuva extrema" OR "desastre") {GDELT_BASE_FILTER}',
]
# ---------------------------------------------------------------------------


def _parse_date(date_str: str) -> datetime:
    try:
        return datetime.strptime(date_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(tz=timezone.utc)


def fetch_articles() -> list[dict]:
    seen: dict[str, dict] = {}

    for query in GDELT_QUERIES:
        log.info("Query: %s...", query[:70])
        params = {
            "query":      query,
            "mode":       "artlist",
            "format":     "json",
            "maxrecords": "25",
            "sort":       "DateDesc",
        }

        for attempt in range(1, 4):
            try:
                r = requests.get(GDELT_BASE_URL, params=params, timeout=30)
                if r.status_code == 429:
                    wait = 30 * attempt
                    log.warning("  429 rate-limit — attendo %ds...", wait)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                for art in r.json().get("articles", []):
                    url = art.get("url")
                    if url and url not in seen:
                        seen[url] = art
                log.info("  OK — %d articoli unici totali.", len(seen))
                break
            except requests.exceptions.Timeout:
                log.warning("  Timeout (tentativo %d/3)...", attempt)
                time.sleep(5)
            except requests.exceptions.RequestException as e:
                log.error("  Errore di rete: %s — salto query.", e)
                break

        log.info("  Pausa 10s...")
        time.sleep(10)

    return list(seen.values())


def build_rows(articles: list[dict]) -> list[dict]:
    rows = []
    for art in articles:
        rows.append({
            "event_id":   str(uuid.uuid4())[:8] + "…",   # troncato per leggibilità
            "country":    "BR",
            "source":     "gdelt",
            "event_date": _parse_date(art.get("seendate", "")).strftime("%Y-%m-%d %H:%M"),
            "event_type": "NULL",                          # → geo_agent
            "severity":   "NULL",                          # → geo_agent
            "title":      (art.get("title") or "")[:60] + ("…" if len(art.get("title", "")) > 60 else ""),
            "summary":    "NULL",                          # → geo_agent
            "url":        (art.get("url") or "")[:45] + "…",
            "domain":     art.get("domain", ""),
            "language":   art.get("language", ""),
        })
    return rows


def print_table(rows: list[dict]):
    if not rows:
        print("\nNessun articolo trovato.\n")
        return

    headers = [
        "event_id", "country", "source", "event_date",
        "event_type", "severity", "title", "summary", "url", "domain", "language"
    ]
    table = [[r[h] for h in headers] for r in rows]

    print("\n" + "=" * 120)
    print(f"  GDELT BRAZIL — {len(rows)} articoli unici  |  event_type / severity / summary → saranno popolati dal geo_agent")
    print("=" * 120)
    print(tabulate(table, headers=headers, tablefmt="rounded_outline", maxcolwidths=50))
    print(f"\nTotale righe: {len(rows)}\n")


if __name__ == "__main__":
    print("\nAvvio test GDELT API per il Brasile...\n")
    articles = fetch_articles()
    rows     = build_rows(articles)
    print_table(rows)