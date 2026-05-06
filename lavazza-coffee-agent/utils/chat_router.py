"""
Router semantico per il chatbot RAG.

Pipeline:
domanda -> embedding -> source_catalog MongoDB -> Qdrant evidence ->
ranking area/source -> piano MongoDB selettivo.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np

from utils.chat_router_config import (
    CHAT_CONTEXT_MAX_CHARS,
    CHAT_ROUTER_AREA_COVERAGE_MIN_SCORE,
    CHAT_ROUTER_MAX_AREAS,
    CHAT_ROUTER_MIN_SOURCE_SCORE,
    CHAT_ROUTER_TOP_SOURCES,
)
from source_configs.sources import (
    get_all_qdrant_collections,
    get_all_raw_collections,
    get_qdrant_collection_area,
    get_qdrant_collections_for_area,
    get_raw_collections_for_area,
    get_source_area,
    get_source_title,
    normalize_area,
)


def _empty_route(reason: str) -> dict:
    raw_collections = get_all_raw_collections()
    qdrant_collections = get_all_qdrant_collections(include_reports=True)
    return {
        "mode": "fallback_broad",
        "reason": reason,
        "areas": ["geo", "environment", "crops", "prices"],
        "source_scores": {},
        "area_scores": {},
        "selected_sources": [],
        "mongo_plan": {collection: [] for collection in raw_collections},
        "mongo_collections": raw_collections,
        "qdrant_collections": qdrant_collections,
        "qdrant_limits": {collection: 3 for collection in qdrant_collections},
        "context_max_chars": CHAT_CONTEXT_MAX_CHARS,
    }


def _load_catalog(db, country: str) -> list[dict]:
    return list(
        db["source_catalog"].find(
            {"country": country, "active": {"$ne": False}, "embedding": {"$type": "array"}},
            projection={
                "_id": 0,
                "source": 1,
                "area": 1,
                "raw_collection": 1,
                "title": 1,
                "description": 1,
                "embedding": 1,
                "latest_collected_at": 1,
                "doc_count": 1,
            },
        )
    )


def route_from_source_catalog(
    db,
    question_embedding: list[float] | None,
    country: str = "BR",
) -> dict:
    """
    Ranking semantico delle source reali presenti in MongoDB.

    Se catalogo/embedding mancano, ritorna fallback broad ma budgettato.
    """
    if not question_embedding:
        return _empty_route("embedding non disponibile")

    try:
        catalog = _load_catalog(db, country)
    except Exception as exc:
        return _empty_route(f"source_catalog non leggibile: {type(exc).__name__}: {exc}")

    if not catalog:
        return _empty_route("source_catalog vuoto: esegui scripts/build_source_catalog.py")

    min_score = CHAT_ROUTER_MIN_SOURCE_SCORE
    top_sources = CHAT_ROUTER_TOP_SOURCES
    area_min_score = CHAT_ROUTER_AREA_COVERAGE_MIN_SCORE
    max_areas = CHAT_ROUTER_MAX_AREAS

    query_vector = np.asarray(question_embedding, dtype=float)
    query_norm = np.linalg.norm(query_vector)
    valid_items = [
        item
        for item in catalog
        if len(item.get("embedding") or []) == len(question_embedding)
    ]
    vectors = np.asarray([item.get("embedding") or [] for item in valid_items], dtype=float)
    if len(valid_items) and query_norm:
        vector_norms = np.linalg.norm(vectors, axis=1)
        denominators = vector_norms * query_norm
        scores = np.divide(
            vectors @ query_vector,
            denominators,
            out=np.zeros(len(valid_items), dtype=float),
            where=denominators != 0,
        )
        ranked = [{**item, "score": float(score)} for item, score in zip(valid_items, scores)]
    else:
        ranked = [{**item, "score": 0.0} for item in catalog]

    ranked.sort(key=lambda item: item["score"], reverse=True)
    selected = [item for item in ranked if item["score"] >= min_score][:top_sources]
    if not selected:
        selected = ranked[: min(3, len(ranked))]

    best_by_area: dict[str, dict] = {}
    for item in ranked:
        area = normalize_area(item.get("area", "")) or get_source_area(item.get("source", ""))
        if not area:
            continue
        if item["score"] < area_min_score:
            continue
        if area not in best_by_area or item["score"] > best_by_area[area]["score"]:
            best_by_area[area] = item

    def _source_key(item: dict) -> tuple[str, str]:
        return (str(item.get("raw_collection", "")), str(item.get("source", "")))

    selected_keys = {_source_key(item) for item in selected}
    for coverage_item in sorted(best_by_area.values(), key=lambda item: item["score"], reverse=True)[:max_areas]:
        coverage_area = normalize_area(coverage_item.get("area", "")) or get_source_area(coverage_item.get("source", ""))
        selected_areas = {
            normalize_area(item.get("area", "")) or get_source_area(item.get("source", ""))
            for item in selected
        }
        if coverage_area in selected_areas or _source_key(coverage_item) in selected_keys:
            continue

        if len(selected) < top_sources:
            selected.append(coverage_item)
            selected_keys.add(_source_key(coverage_item))
            continue

        area_counts: dict[str, int] = defaultdict(int)
        for item in selected:
            area = normalize_area(item.get("area", "")) or get_source_area(item.get("source", ""))
            if area:
                area_counts[area] += 1

        replace_index = None
        for idx, item in sorted(enumerate(selected), key=lambda pair: pair[1]["score"]):
            area = normalize_area(item.get("area", "")) or get_source_area(item.get("source", ""))
            if area_counts.get(area, 0) > 1:
                replace_index = idx
                break

        if replace_index is not None:
            selected[replace_index] = coverage_item
            selected_keys = {_source_key(item) for item in selected}

    selected.sort(key=lambda item: item["score"], reverse=True)

    area_scores: dict[str, float] = defaultdict(float)
    source_scores: dict[str, float] = {}
    mongo_plan: dict[str, set[str]] = defaultdict(set)

    for item in selected:
        source = item.get("source", "")
        area = normalize_area(item.get("area", "")) or get_source_area(source)
        raw_collection = item.get("raw_collection", "")
        score = float(item.get("score", 0.0))

        if source:
            source_scores[source] = max(source_scores.get(source, 0.0), score)
        if area:
            area_scores[area] = max(area_scores[area], score)
        if raw_collection and source:
            mongo_plan[raw_collection].add(source)

    areas = sorted(area_scores.keys(), key=lambda area: area_scores[area], reverse=True)
    qdrant_collections = ["reports_archive"]
    for area in areas:
        for collection in get_qdrant_collections_for_area(area):
            if collection not in qdrant_collections:
                qdrant_collections.append(collection)

    if not qdrant_collections:
        qdrant_collections = ["reports_archive"]

    return {
        "mode": "semantic_source_catalog",
        "reason": "ranking embedding domanda vs source_catalog",
        "areas": areas,
        "source_scores": source_scores,
        "area_scores": dict(area_scores),
        "selected_sources": [
            {
                "source": item.get("source"),
                "title": item.get("title") or get_source_title(item.get("source", "")),
                "area": normalize_area(item.get("area", "")),
                "raw_collection": item.get("raw_collection"),
                "score": round(float(item.get("score", 0.0)), 4),
                "latest_collected_at": item.get("latest_collected_at"),
            }
            for item in selected
        ],
        "mongo_plan": {collection: sorted(sources) for collection, sources in mongo_plan.items()},
        "mongo_collections": sorted(mongo_plan.keys()),
        "qdrant_collections": qdrant_collections,
        "qdrant_limits": {
            "reports_archive": 3,
            "geo_texts": 6 if "geo" in areas else 3,
            "crops_texts": 5 if "crops" in areas else 3,
        },
        "context_max_chars": CHAT_CONTEXT_MAX_CHARS,
    }


def merge_qdrant_evidence(route: dict, qdrant_hits_by_collection: dict[str, list[dict]]) -> dict:
    """
    Usa le hit Qdrant come evidenza aggiuntiva per allargare leggermente il piano MongoDB.
    """
    source_scores = dict(route.get("source_scores", {}))
    area_scores = dict(route.get("area_scores", {}))
    mongo_plan = {
        collection: set(sources)
        for collection, sources in (route.get("mongo_plan") or {}).items()
    }

    for collection, hits in qdrant_hits_by_collection.items():
        area = get_qdrant_collection_area(collection)
        if area and area != "reports":
            area_scores[area] = max(area_scores.get(area, 0.0), 0.35)
            for raw_collection in get_raw_collections_for_area(area):
                mongo_plan.setdefault(raw_collection, set())

        for rank, hit in enumerate(hits[:5], start=1):
            source = hit.get("source")
            if not source:
                continue
            score = max(0.2, 0.5 - rank * 0.05)
            source_scores[source] = max(source_scores.get(source, 0.0), score)
            source_area = get_source_area(source, area if area != "reports" else "")
            if source_area:
                area_scores[source_area] = max(area_scores.get(source_area, 0.0), score)
                for raw_collection in get_raw_collections_for_area(source_area):
                    mongo_plan.setdefault(raw_collection, set()).add(source)

    areas = sorted(area_scores.keys(), key=lambda area: area_scores[area], reverse=True)
    route = {**route}
    route["areas"] = areas
    route["source_scores"] = source_scores
    route["area_scores"] = area_scores
    route["mongo_plan"] = {collection: sorted(sources) for collection, sources in mongo_plan.items()}
    route["mongo_collections"] = sorted(route["mongo_plan"].keys())
    return route


def summarize_route_for_debug(route: dict) -> dict[str, Any]:
    return {
        "mode": route.get("mode"),
        "reason": route.get("reason"),
        "areas": route.get("areas", []),
        "mongo_plan": route.get("mongo_plan", {}),
        "qdrant_collections": route.get("qdrant_collections", []),
        "selected_sources": route.get("selected_sources", []),
        "context_max_chars": route.get("context_max_chars"),
    }
