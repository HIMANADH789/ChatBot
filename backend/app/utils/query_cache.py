"""
State-Machine Aware Semantic Query Cache backed by MongoDB.

Stores query embeddings + template-generalized responses.
Integrates with Layer 2 UserSessionState to maintain full coherence with
the dynamic State Machine architecture.

Features:
  - Template Generalization: Sanitizes session-specific variables ({user_name}) into placeholders before caching.
  - State Hydration: Dynamically injects the active session's UserSessionState attributes upon cache hit.
  - Similarity Matching: Threshold 0.85 catches paraphrases and near-duplicates.
  - Invalidation: Automatic TTL and per-client cache purging on profile/document updates.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Any, Dict, List

from app.db.mongodb import get_db
from app.db.collections import QUERY_CACHE
from app.config import settings

# Maximum entries to scan per client per request (performance guard)
_MAX_SCAN = 500


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def generalize_response_for_cache(response: str, context_variables: Optional[Dict[str, Any]] = None) -> str:
    """
    Generalize session-specific state variables (e.g. user_name) into reusable
    template placeholders before saving into the semantic cache.
    """
    if not response or not context_variables:
        return response

    template_text = response
    user_name = context_variables.get("user_name")
    if user_name and len(str(user_name).strip()) >= 2:
        pattern = r"\b" + re.escape(str(user_name).strip()) + r"\b"
        template_text = re.sub(pattern, "{user_name}", template_text, flags=re.IGNORECASE)

    return template_text


def hydrate_cached_response(template_text: str, context_variables: Optional[Dict[str, Any]] = None) -> str:
    """
    Hydrate template placeholders in cached response with the active session's context variables.
    """
    if not template_text:
        return template_text

    context = context_variables or {}
    user_name = context.get("user_name")

    hydrated = template_text
    if "{user_name}" in hydrated:
        if user_name:
            hydrated = hydrated.replace("{user_name}", str(user_name))
        else:
            hydrated = re.sub(r"\b(hello|hi|welcome|greetings)\s+\{user_name\}[\!\,]?", r"\1!", hydrated, flags=re.IGNORECASE)
            hydrated = hydrated.replace("{user_name}", "")

    # Cleanup fallback for any un-templated residual greetings in legacy entries
    if user_name:
        hydrated = re.sub(
            r"\b(hello|hi|welcome|greetings)\s+[A-Za-z0-9_\-\.]+\b",
            lambda m: f"{m.group(1)} {user_name}",
            hydrated,
            flags=re.IGNORECASE,
        )

    return hydrated


async def check_cache(
    client_id: str,
    query_embedding: list[float],
    context_variables: Optional[Dict[str, Any]] = None,
    active_node_id: Optional[str] = None,
) -> Optional[dict]:
    """
    State-machine coherent cache lookup:
    Returns state-hydrated {response, sources, node_id} if a semantically similar
    cached entry exists, otherwise None.
    """
    db = get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.CACHE_TTL_HOURS)

    cursor = db[QUERY_CACHE].find(
        {"client_id": client_id, "created_at": {"$gte": cutoff}},
        {"_id": 1, "query_embedding": 1, "response": 1, "sources": 1, "node_id": 1},
    ).sort("hit_count", -1).limit(_MAX_SCAN)

    entries = await cursor.to_list(length=_MAX_SCAN)

    best_score = 0.0
    best_entry = None
    for entry in entries:
        sim = _cosine_similarity(query_embedding, entry["query_embedding"])
        if sim > best_score:
            best_score = sim
            best_entry = entry

    if best_score >= settings.CACHE_SIMILARITY_THRESHOLD and best_entry:
        await db[QUERY_CACHE].update_one(
            {"_id": best_entry["_id"]},
            {"$inc": {"hit_count": 1}, "$set": {"last_hit_at": datetime.now(timezone.utc)}},
        )
        hydrated_resp = hydrate_cached_response(best_entry["response"], context_variables)
        return {
            "response": hydrated_resp,
            "sources": best_entry.get("sources", []),
            "node_id": best_entry.get("node_id"),
        }

    return None


async def store_cache(
    client_id: str,
    query_text: str,
    query_embedding: list[float],
    response: str,
    sources: list,
    context_variables: Optional[Dict[str, Any]] = None,
    active_node_id: Optional[str] = None,
) -> None:
    """
    Store a RAG response into the semantic cache, template-generalizing state variables
    to maintain state machine coherence across all future user sessions.
    """
    db = get_db()
    template_response = generalize_response_for_cache(response, context_variables)
    await db[QUERY_CACHE].insert_one({
        "client_id": client_id,
        "query_text": query_text,
        "query_embedding": query_embedding,
        "response": template_response,
        "sources": sources,
        "node_id": active_node_id,
        "created_at": datetime.now(timezone.utc),
        "hit_count": 0,
        "last_hit_at": None,
    })


async def invalidate_client_cache(client_id: str) -> None:
    """Call this whenever documents or tenant state profiles are added, updated, or removed."""
    db = get_db()
    result = await db[QUERY_CACHE].delete_many({"client_id": client_id})
    return result.deleted_count
