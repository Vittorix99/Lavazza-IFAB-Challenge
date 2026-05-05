"""
setup_coffee_regions.py
=======================
Carica in MongoDB la collection `coffee_regions` con due livelli:

  level=1  → polygon dei 5 stati brasiliani produttori di caffè
  level=2  → polygon dei comuni brasiliani con produzione caffè (PAM IBGE)

Fonti:
  - IBGE Malhas API  → confini stati e comuni (GeoJSON)
  - IBGE SIDRA t5457 → PAM: comuni con produzione caffè (lista ID)

Uso:
  python scripts/setup_coffee_regions.py

Requisiti: pymongo, requests, python-dotenv
"""

import os
import sys
import time
import requests
from pymongo import MongoClient, GEOSPHERE
from dotenv import load_dotenv

load_dotenv(
    dotenv_path=os.path.join(os.path.dirname(__file__), "../lavazza-coffee-agent/.env")
)

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB  = os.getenv("MONGODB_DB",  "lavazza_ifab")

# ---------------------------------------------------------------------------
# Livello 1 — Stati produttori caffè
# ---------------------------------------------------------------------------

COFFEE_STATES = [
    {"id": "31", "name": "Minas Gerais",   "uf": "MG"},
    {"id": "35", "name": "São Paulo",      "uf": "SP"},
    {"id": "32", "name": "Espírito Santo", "uf": "ES"},
    {"id": "29", "name": "Bahia",          "uf": "BA"},
    {"id": "11", "name": "Rondônia",       "uf": "RO"},
    {"id": "41", "name": "Paraná",         "uf": "PR"},
]

IBGE_STATE_URL = "https://servicodados.ibge.gov.br/api/v3/malhas/estados/{id}?formato=application/vnd.geo+json"


def fetch_state_polygon(state: dict) -> dict | None:
    url = IBGE_STATE_URL.format(id=state["id"])
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        gj = r.json()
        # IBGE restituisce FeatureCollection con una Feature
        features = gj.get("features", [])
        if not features:
            print(f"  ⚠️  {state['name']}: nessuna feature")
            return None
        geometry = features[0]["geometry"]
        return {
            "level": 1,
            "region_type": "state",
            "name": state["name"],
            "uf": state["uf"],
            "ibge_id": state["id"],
            "geometry": geometry,
        }
    except Exception as e:
        print(f"  ❌ {state['name']}: {e}")
        return None


# ---------------------------------------------------------------------------
# Livello 2 — Comuni produttori caffè (PAM IBGE SIDRA)
# ---------------------------------------------------------------------------

# IBGE API v3: tabella 1613 (PAM lavouras permanentes)
# variável 214 = Quantidade produzida (Toneladas)
# classificação 82, categoria 2723 = Café (em grão) Total
# nível N6 = município
IBGE_PAM_URL = "https://servicodados.ibge.gov.br/api/v3/agregados/1613/periodos/last/variaveis/214"

IBGE_MUNI_URL = "https://servicodados.ibge.gov.br/api/v3/malhas/municipios/{id}?formato=application/vnd.geo+json"


def fetch_coffee_municipalities() -> dict[str, str]:
    """
    Scarica da IBGE API v3 (PAM) i comuni con produzione caffè > 0.
    Restituisce {ibge_id: nome_comune}.
    """
    print("  Fetching PAM coffee municipalities from IBGE API v3...")
    try:
        r = requests.get(
            IBGE_PAM_URL,
            params={"localidades": "N6[all]", "classificacao": "82[2723]"},
            timeout=60,
        )
        r.raise_for_status()
        d = r.json()
        series = d[0].get("resultados", [{}])[0].get("series", [])

        result = {}
        for item in series:
            value = list(item.get("serie", {}).values())[-1] if item.get("serie") else ""
            value = str(value).strip()
            if value and value not in ("-", "...", "X", "", "0"):
                try:
                    if float(value) > 0:
                        muni_id = str(item["localidade"]["id"])
                        muni_name = item["localidade"]["nome"]
                        result[muni_id] = muni_name
                except (ValueError, KeyError):
                    pass

        print(f"  Trovati {len(result)} comuni produttori caffè")
        return result
    except Exception as e:
        print(f"  ❌ PAM error: {e}")
        return {}


def fetch_municipality_polygon(muni_id: str, muni_name: str = "") -> dict | None:
    url = IBGE_MUNI_URL.format(id=muni_id)
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        gj = r.json()
        features = gj.get("features", [])
        if not features:
            return None
        geometry = features[0]["geometry"]
        return {
            "level": 2,
            "region_type": "municipality",
            "name": muni_name or muni_id,
            "ibge_id": muni_id,
            "uf": muni_id[:2],  # prime 2 cifre = codice stato
            "geometry": geometry,
        }
    except Exception:
        return None



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    client = MongoClient(MONGODB_URI)
    db = client[MONGODB_DB]
    col = db["coffee_regions"]

    print("=" * 60)
    print("Setup coffee_regions MongoDB collection")
    print("=" * 60)

    # Drop e ricrea
    col.drop()
    print("Collection coffee_regions resettata.")

    # Indice 2dsphere
    col.create_index([("geometry", GEOSPHERE)], name="geo_2dsphere")
    col.create_index([("level", 1), ("uf", 1)], name="level_uf")
    print("Indici creati.")

    # -----------------------------------------------------------------------
    # Livello 1 — Stati
    # -----------------------------------------------------------------------
    print("\n--- Livello 1: Stati produttori ---")
    level1_docs = []
    for state in COFFEE_STATES:
        print(f"  Fetching {state['name']}...")
        doc = fetch_state_polygon(state)
        if doc:
            level1_docs.append(doc)
            print(f"  ✅ {state['name']} ({state['uf']})")
        time.sleep(0.3)

    if level1_docs:
        col.insert_many(level1_docs)
        print(f"Inseriti {len(level1_docs)} stati.")

    # -----------------------------------------------------------------------
    # Livello 2 — Comuni
    # -----------------------------------------------------------------------
    print("\n--- Livello 2: Comuni produttori caffè (PAM IBGE) ---")
    municipalities = fetch_coffee_municipalities()

    if not municipalities:
        print("  Nessun comune trovato — skip livello 2.")
    else:
        muni_items = list(municipalities.items())
        print(f"  Fetching {len(muni_items)} polygon comuni (può richiedere alcuni minuti)...")
        level2_docs = []
        failed = 0
        for i, (muni_id, muni_name) in enumerate(muni_items):
            doc = fetch_municipality_polygon(muni_id, muni_name)
            if doc:
                level2_docs.append(doc)
            else:
                failed += 1

            # Batch insert ogni 200 per non accumulare tutto in RAM
            if len(level2_docs) >= 200:
                col.insert_many(level2_docs)
                print(f"    Inseriti {i+1}/{len(muni_items)} comuni...")
                level2_docs = []

            # Rate limit gentile verso IBGE
            if i % 10 == 9:
                time.sleep(0.5)

        if level2_docs:
            col.insert_many(level2_docs)

        total_l2 = col.count_documents({"level": 2})
        print(f"  ✅ Inseriti {total_l2} comuni ({failed} falliti).")

    # -----------------------------------------------------------------------
    # Riepilogo
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("Riepilogo coffee_regions:")
    print(f"  Livello 1 (stati):  {col.count_documents({'level': 1})}")
    print(f"  Livello 2 (comuni): {col.count_documents({'level': 2})}")
    print(f"  Totale:             {col.count_documents({})}")
    print("=" * 60)

    # Test query: fuoco di esempio in Sul de Minas
    test_point = {"type": "Point", "coordinates": [-45.93, -21.77]}  # Varginha, MG
    hits = list(col.find(
        {"geometry": {"$geoIntersects": {"$geometry": test_point}}},
        {"name": 1, "level": 1, "uf": 1, "_id": 0}
    ))
    print(f"\nTest Varginha (MG) → {len(hits)} regioni trovate:")
    for h in hits:
        print(f"  Level {h['level']} — {h['name']} ({h.get('uf','')})")

    client.close()


if __name__ == "__main__":
    main()
