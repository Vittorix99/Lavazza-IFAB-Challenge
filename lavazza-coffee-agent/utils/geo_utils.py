"""
geo_utils.py — Utility geospaziali per il tagging dei fuochi NASA FIRMS.

Usato da environment_agent per arricchire i documenti raw_environment
con informazioni sulle zone di coltivazione caffè (Livello 2 — comuni).

Level 1 (stati) è già fatto a ingestion time nel workflow n8n.
Level 2 (comuni) è fatto qui via MongoDB $geoIntersects su coffee_regions.
"""

from pymongo.database import Database


def tag_fires_with_coffee_zones(doc: dict, db: Database) -> dict:
    """
    Arricchisce un documento NASA FIRMS con informazioni sulle zone caffè.

    Per ogni detection nell'array doc['detections']:
      - Controlla se il punto cade in un comune produttore caffè (Level 2)
      - Aggiunge i campi: in_coffee_municipality, municipality_name

    Aggiunge al documento di primo livello:
      - coffee_zone_detections: count fuochi in zone caffè (L1 + L2)
      - coffee_zone_ratio: % fuochi in zone caffè su totale
      - affected_regions: lista regioni/comuni colpiti
    """
    detections = doc.get("detections", [])
    if not detections:
        return doc

    # Solo i punti già marcati L1 (in_coffee_state=True dal workflow n8n)
    # vengono controllati a L2 — riduce le query MongoDB
    coffee_detections = 0
    affected_municipalities = set()
    affected_states = set()

    enriched = []
    for det in detections:
        lat = det.get("latitude")
        lon = det.get("longitude")

        # L1 già fatto in n8n
        in_state = det.get("in_coffee_state", False)
        if in_state:
            affected_states.add(det.get("coffee_state_uf", ""))
            coffee_detections += 1

        # L2 — query MongoDB solo se lat/lon validi e in stato caffè
        municipality_name = None
        if in_state and lat is not None and lon is not None:
            try:
                point = {"type": "Point", "coordinates": [lon, lat]}
                result = db["coffee_regions"].find_one(
                    {
                        "level": 2,
                        "geometry": {"$geoIntersects": {"$geometry": point}},
                    },
                    {"name": 1, "uf": 1, "_id": 0},
                )
                if result:
                    municipality_name = result["name"]
                    affected_municipalities.add(result["name"])
            except Exception:
                pass

        enriched.append({
            **det,
            "in_coffee_municipality": municipality_name is not None,
            "municipality_name": municipality_name,
        })

    total = len(detections)
    ratio = round(coffee_detections / total, 3) if total > 0 else 0.0

    return {
        **doc,
        "detections": enriched,
        "coffee_zone_detections": coffee_detections,
        "coffee_zone_ratio": ratio,
        "affected_states": sorted(affected_states - {""}),
        "affected_municipalities": sorted(affected_municipalities),
    }
