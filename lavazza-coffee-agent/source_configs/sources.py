"""
Configurazioni centralizzate delle fonti dati.

Tutto cio' che descrive una source (alias, cadenza, area, titolo, collection
Qdrant) deve vivere qui, non dentro agenti o dashboard.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator


QdrantSourceTarget = tuple[str, str]
SourceWithCadence = tuple[str, str]


RAW_COLLECTION_AREAS: dict[str, str] = {
    "raw_geo": "geo",
    "raw_prices": "prices",
    "raw_crops": "crops",
    "raw_environment": "environment",
}


AREA_RAW_COLLECTIONS: dict[str, list[str]] = {
    "geo": ["raw_geo"],
    "prices": ["raw_prices"],
    "crops": ["raw_crops"],
    "environment": ["raw_environment"],
}


AREA_QDRANT_COLLECTIONS: dict[str, list[str]] = {
    "geo": ["geo_texts"],
    "crops": ["crops_texts"],
    "prices": [],
    "environment": [],
}


# keyword utente -> (collection Qdrant, valore payload source)
DEFAULT_QDRANT_SOURCE_KEYWORDS: dict[str, QdrantSourceTarget] = {
    "gdelt": ("geo_texts", "GDELT"),
    "wto": ("geo_texts", "WTO_RSS"),
    "wto rss": ("geo_texts", "WTO_RSS"),
    "nasa": ("geo_texts", "NASA_FIRMS"),
    "nasa firms": ("geo_texts", "NASA_FIRMS"),
    "ais": ("geo_texts", "AISSTREAM_PORT_CONGESTION"),
    "port congestion": ("geo_texts", "AISSTREAM_PORT_CONGESTION"),
    "congestion": ("geo_texts", "AISSTREAM_PORT_CONGESTION"),
    "conab": ("crops_texts", "CONAB"),
    "faostat": ("crops_texts", "FAOSTAT"),
}


def normalize_area(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"colture", "crop"}:
        return "crops"
    if normalized in {"price", "prezzi"}:
        return "prices"
    if normalized in {"ambiente", "env"}:
        return "environment"
    if normalized in {"geopolitics", "geopolitical"}:
        return "geo"
    return normalized


def get_area_for_raw_collection(collection: str, default: str = "") -> str:
    return RAW_COLLECTION_AREAS.get(collection, default)


def get_raw_collections_for_area(area: str) -> list[str]:
    return list(AREA_RAW_COLLECTIONS.get(normalize_area(area), []))


def get_qdrant_collections_for_area(area: str) -> list[str]:
    return list(AREA_QDRANT_COLLECTIONS.get(normalize_area(area), []))


def get_qdrant_collection_area(collection: str) -> str:
    for area, collections in AREA_QDRANT_COLLECTIONS.items():
        if collection in collections:
            return area
    if collection == "reports_archive":
        return "reports"
    return ""


# Fallback cadenze per fonti che non memorizzano "cadenza" nel documento raw.
SOURCE_CADENCE: dict[str, str] = {
    "BCB_PTAX": "daily",
    "ECB_DATA_PORTAL": "daily",
    "WB_PINK_SHEET": "monthly",
    "WORLD_BANK_PINKSHEET": "monthly",
    "NOAA_ENSO": "monthly",
    "NASA_FIRMS": "hourly",
    "GDELT": "hourly",
    "WTO_RSS": "6h",
    "USDA_FAS_PSD": "weekly",
    "IBGE_SIDRA": "weekly",
    "IBGE_SIDRA_LSPA": "weekly",
    "COMEX_STAT": "monthly",
    "CONAB": "weekly",
    "CONAB_PDF": "weekly",
    "CONAB_CAFE_SAFRA": "weekly",
    "FAOSTAT": "monthly",
    "FAOSTAT_QCL": "monthly",
    "AISSTREAM_PORT_CONGESTION": "daily",
}


FRESHNESS_DAYS: dict[str, int] = {
    "hourly": 1,
    "6h": 1,
    "daily": 2,
    "weekly": 10,
    "settimanale": 10,
    "monthly": 35,
    "mensile": 35,
    "unknown": 30,
}


CROPS_SOURCES: list[SourceWithCadence] = [
    ("USDA_FAS_PSD", "weekly"),
    ("IBGE_SIDRA_LSPA", "weekly"),
    ("COMEX_STAT", "monthly"),
    ("CONAB_CAFE_SAFRA", "weekly"),
    ("FAOSTAT_QCL", "monthly"),
]


SOURCE_TITLES: dict[str, str] = {
    "WORLD_BANK_PINKSHEET": "Prezzo Arabica — World Bank Pink Sheet",
    "WB_PINK_SHEET": "Prezzo Arabica — World Bank Pink Sheet",
    "BCB_PTAX": "Tasso di cambio BRL/USD — BCB PTAX",
    "ECB_DATA_PORTAL": "Tasso EUR/BRL — BCE",
    "NOAA_ENSO": "Indice ENSO — NOAA",
    "NASA_FIRMS": "Incendi attivi — NASA FIRMS",
    "USDA_FAS_PSD": "Bilancio produzione/stock — USDA FAS",
    "IBGE_SIDRA": "Produzione agricola — IBGE SIDRA",
    "IBGE_SIDRA_LSPA": "Produzione agricola — IBGE SIDRA",
    "COMEX_STAT": "Export caffè Brasile — Comex Stat",
    "CONAB": "Previsioni raccolto — CONAB",
    "CONAB_PDF": "Previsioni raccolto — CONAB",
    "CONAB_CAFE_SAFRA": "Previsioni raccolto — CONAB",
    "FAOSTAT": "Produzione storica — FAOSTAT",
    "FAOSTAT_QCL": "Produzione storica — FAOSTAT",
    "GDELT": "News geopolitiche — GDELT",
    "WTO_RSS": "Comunicati commercio — WTO",
    "AISSTREAM_PORT_CONGESTION": "Congestione porti — AIS Stream",
}


SOURCE_AREAS: dict[str, str] = {
    "WORLD_BANK_PINKSHEET": "prices",
    "WB_PINK_SHEET": "prices",
    "BCB_PTAX": "prices",
    "ECB_DATA_PORTAL": "prices",
    "NOAA_ENSO": "environment",
    "NASA_FIRMS": "environment",
    "USDA_FAS_PSD": "crops",
    "IBGE_SIDRA": "crops",
    "IBGE_SIDRA_LSPA": "crops",
    "COMEX_STAT": "crops",
    "CONAB": "crops",
    "CONAB_PDF": "crops",
    "CONAB_CAFE_SAFRA": "crops",
    "FAOSTAT": "crops",
    "FAOSTAT_QCL": "crops",
    "GDELT": "geo",
    "WTO_RSS": "geo",
    "AISSTREAM_PORT_CONGESTION": "geo",
}


def get_source_cadence(source: str, default: str = "unknown") -> str:
    return SOURCE_CADENCE.get(str(source).upper(), default)


def get_freshness_threshold_days(cadence: str, default: int = 30) -> int:
    return FRESHNESS_DAYS.get(str(cadence).strip().lower(), default)


def get_crops_sources() -> list[SourceWithCadence]:
    return list(CROPS_SOURCES)


def get_source_title(source: str) -> str:
    normalized = str(source).upper()
    return SOURCE_TITLES.get(normalized, f"Dati {source}")


def get_source_area(source: str, default: str = "") -> str:
    return SOURCE_AREAS.get(str(source).upper(), default)


def get_all_raw_collections() -> list[str]:
    return list(RAW_COLLECTION_AREAS.keys())


def get_all_qdrant_collections(include_reports: bool = True) -> list[str]:
    seen: list[str] = []
    for collections in AREA_QDRANT_COLLECTIONS.values():
        for collection in collections:
            if collection not in seen:
                seen.append(collection)
    if include_reports:
        seen.append("reports_archive")
    return seen


def get_qdrant_source_keyword_map() -> dict[str, QdrantSourceTarget]:
    """
    Restituisce la mappa keyword -> target Qdrant.

    I default coprono le fonti attuali. L'env JSON permette di aggiungere,
    sovrascrivere o rimuovere alias quando cambiano le fonti n8n/Qdrant.
    """
    mapping = dict(DEFAULT_QDRANT_SOURCE_KEYWORDS)
    raw = (os.environ.get("QDRANT_SOURCE_KEYWORDS_JSON") or "").strip()
    if not raw:
        return mapping

    try:
        overrides = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[source-configs] QDRANT_SOURCE_KEYWORDS_JSON non valido: {exc}")
        return mapping

    if not isinstance(overrides, dict):
        print("[source-configs] QDRANT_SOURCE_KEYWORDS_JSON deve essere un oggetto JSON")
        return mapping

    for keyword, target in overrides.items():
        normalized_keyword = str(keyword).strip().lower()
        if not normalized_keyword:
            continue

        if target is None:
            mapping.pop(normalized_keyword, None)
            continue

        if isinstance(target, dict):
            collection = str(target.get("collection", "")).strip()
            source = str(target.get("source", "")).strip()
        elif isinstance(target, (list, tuple)) and len(target) == 2:
            collection = str(target[0]).strip()
            source = str(target[1]).strip()
        else:
            print(f"[source-configs] Target ignorato per '{normalized_keyword}': formato non valido")
            continue

        if collection and source:
            mapping[normalized_keyword] = (collection, source)

    return mapping


def iter_qdrant_source_targets(question: str) -> Iterator[tuple[str, str, str]]:
    """
    Trova le fonti nominate nella domanda.

    Yield: (keyword_matchata, collection_qdrant, payload_source).
    Deduplica target equivalenti: "wto" e "wto rss" non generano due query.
    """
    question_lower = question.lower()
    seen_targets: set[QdrantSourceTarget] = set()

    keyword_map = get_qdrant_source_keyword_map()
    for keyword, target in sorted(keyword_map.items(), key=lambda item: len(item[0]), reverse=True):
        if keyword not in question_lower or target in seen_targets:
            continue

        seen_targets.add(target)
        collection, source = target
        yield keyword, collection, source
