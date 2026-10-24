"""
Retrieval Service:
Handles pure search and context retrieval:
  1. Context-Adaptive Query Resolution (rewrites pronouns/fragments with session context)
  2. Query Metadata Extraction & Where-Filtering
  3. HyDE (Hypothetical Document Embeddings with circuit breaker)
  4. Query Decomposition for multi-part questions
  5. Clarification Detection
  6. Hybrid Search (Dense ChromaDB + Sparse BM25 + Reciprocal Rank Fusion)
  7. Cross-Encoder Reranking
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional, Any

from app.config import settings
from app.providers.base import EmbeddingProvider, LLMProvider, VectorStoreProvider
from app.services.bm25_search import bm25_registry, reciprocal_rank_fusion
from app.services.llm_response import clean_markdown, parse_json_response
from app.utils import reranker as reranker_util

logger = logging.getLogger(__name__)

# Circuit breaker: skip HyDE for 60s after 3 consecutive failures
_hyde_fail_count = 0
_hyde_open_until: float = 0.0


# ── Context-Adaptive Query Resolution ─────────────────────────────────────────

_CONTEXT_REWRITE_PROMPT = """You are a precise search query reformulator for an institutional knowledge assistant.
Given the conversation history, active user session context, and latest user message, rewrite the user's latest message into a single standalone, unambiguous search query for vector retrieval.

Instructions:
1. If the user refers to something from previous turns with pronouns ("it", "its", "they", "their", "this", "that", "those", "same"), replace them with the explicit subject/entity mentioned previously or in the active user session context.
2. If the user asks a follow-up fragment (e.g. "what is the fee structure?", "how to apply?", "eligibility?", "duration?"), combine it with the active interested course or qualification from the Active User Session Profile Context (e.g. "Finance & Accounting course fee structure for B.Com graduate").
3. Specific tracking criteria for this institution:
{context_instructions}
4. If the latest user message is already clear, complete, and self-contained, or is a simple greeting, return it UNCHANGED.
5. Do NOT answer the question. Do NOT add preamble or reasoning. Return ONLY the rewritten search query.

{user_context_block}Conversation history:
{history_text}

Latest user message: {query}
Standalone search query:"""


async def resolve_contextual_query(
    query: str,
    history: list,
    llm: LLMProvider,
    context_mode: str = "none",
    context_instructions: str = "",
    context_capacity: int = 4,
    context_variables: Optional[dict] = None,
    rate_limiter: Any = None,
) -> str:
    """
    Resolves pronouns, elided subjects, and conversational context into a self-contained
    search query before vector retrieval.
    """
    effective_mode = context_mode or "none"
    if effective_mode == "none":
        return query

    user_context_block = ""
    if context_variables:
        active_vars = [f"• {k.replace('_', ' ').title()}: {v}" for k, v in context_variables.items() if v]
        if active_vars:
            user_context_block = "Active User Session Profile Context:\n" + "\n".join(active_vars) + "\n\n"

    if not history or len(history) <= 1:
        if not context_variables or not any(k in context_variables for k in ("interested_course", "target_course", "qualification")):
            return query

    history_slice = history[-(context_capacity * 2 + 1):-1] if history else []

    if effective_mode == "adaptive":
        lower = query.lower().strip()
        pronoun_triggers = {
            "it", "its", "they", "them", "their", "theirs", "this", "that", "these", "those",
            "he", "him", "his", "she", "her", "hers", "same", "there", "then", "above", "mentioned"
        }
        words = re.findall(r"\b\w+\b", lower)
        has_pronoun = any(w in pronoun_triggers for w in words)
        is_fragment = len(words) <= 5 and any(w in lower for w in (
            "fee", "fees", "cost", "eligibility", "process", "date", "deadline", "how", "what", "where",
            "when", "apply", "criteria", "contact", "syllabus", "hostel", "cutoff", "quota", "seat",
            "timing", "requirement", "placement", "faculty", "location", "address", "structure", "duration"
        ))
        if not has_pronoun and not is_fragment and len(words) > 6 and not user_context_block:
            return query

    lines = []
    for msg in history_slice:
        role = "User" if msg.get("role") == "user" else "Assistant"
        content = str(msg.get("content", "")).strip().replace("\n", " ")
        if content:
            lines.append(f"{role}: {content[:200]}")
    history_text = "\n".join(lines)
    if not history_text and not user_context_block:
        return query

    instructions = context_instructions.strip() if context_instructions else "Preserve specific courses, branches, departments, dates, fees, and admission criteria."

    try:
        if rate_limiter:
            await rate_limiter.acquire()
        prompt = _CONTEXT_REWRITE_PROMPT.format(
            query=query,
            user_context_block=user_context_block,
            history_text=history_text or "No previous history turns.",
            context_instructions=instructions,
        )
        resp = await llm.generate(prompt, temperature=0.0, max_tokens=100)
        rewritten = clean_markdown(resp.text).strip().strip('"').strip("'")
        if rewritten and len(rewritten) >= 3 and not rewritten.lower().startswith(("here is", "i have", "rewritten", "standalone")):
            logger.info("Contextual RAG query resolved: '%s' -> '%s' (user_context=%s)", query, rewritten, context_variables)
            return rewritten
    except Exception as e:
        logger.debug("Contextual query rewrite failed: %s", e)

    return query


# ── Metadata Extraction & Filtering ──────────────────────────────────────────

_QUERY_METADATA_PROMPT = """Extract metadata from this user question as JSON.

Question: {query}

Return ONLY a JSON object:
{{
  "year": "1st | 2nd | 3rd | 4th | null",
  "semester": "1 | 2 | null",
  "department": "department name or null",
  "course": "course name or null"
}}
Use null for any field not mentioned. Return ONLY valid JSON."""


async def extract_query_metadata(query: str, llm: LLMProvider) -> dict:
    try:
        resp = await llm.generate(_QUERY_METADATA_PROMPT.format(query=query), temperature=0.0, max_tokens=150)
        return parse_json_response(resp.text)
    except Exception:
        return {}


def build_where_filter(metadata: dict) -> Optional[dict]:
    """
    Build a ChromaDB `where` filter from query metadata.
    Only filter on fields that were explicitly mentioned in the query.
    """
    conditions = []
    for key in ("year", "semester", "department", "course"):
        val = metadata.get(key)
        if val and val != "null":
            conditions.append({key: {"$eq": val}})
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


# ── HyDE ─────────────────────────────────────────────────────────────────────

_HYDE_PROMPT = """Write a brief, factual answer to this question as if it came from an official document.
Keep it under 100 words. Be specific and direct.

Question: {query}
Answer:"""


async def hypothetical_embedding(
    query: str, llm: LLMProvider, embeddings: EmbeddingProvider
) -> list[float]:
    """Generate a hypothetical answer and embed it for richer semantic retrieval."""
    global _hyde_fail_count, _hyde_open_until

    if time.time() < _hyde_open_until:
        return await embeddings.embed_query(query)

    try:
        resp = await llm.generate(
            _HYDE_PROMPT.format(query=query), temperature=0.1, max_tokens=150
        )
        _hyde_fail_count = 0
        hyp_text = resp.text.strip()
        return await embeddings.embed_query(hyp_text)
    except Exception as e:
        _hyde_fail_count += 1
        if _hyde_fail_count >= 3:
            _hyde_open_until = time.time() + 60.0
            _hyde_fail_count = 0
            logger.warning("HyDE circuit breaker opened for 60s (quota/rate-limit pressure)")
        else:
            logger.debug("HyDE skipped, falling back to query embedding: %s", type(e).__name__)
        return await embeddings.embed_query(query)


# ── Sub-Question Decomposition ───────────────────────────────────────────────

async def decompose_question(message: str, llm: LLMProvider) -> list[str]:
    prompt = f"""You are a query decomposition assistant.
Given a user question, break it into 1-3 focused sub-questions for a knowledge base lookup.
If the question is already simple, return just the original question.

User question: {message}

Return ONLY a numbered list of sub-questions, nothing else."""
    response = await llm.generate(prompt, temperature=0.0, max_tokens=200)
    lines = [l.strip() for l in response.text.strip().splitlines() if l.strip()]
    sub_questions = [line.lstrip("0123456789. ").strip() for line in lines if line]
    return [q for q in sub_questions if q] or [message]


# ── Clarification Detection ──────────────────────────────────────────────────

_CLARIFICATION_PROMPT = """You are a helpful assistant deciding whether a user's question needs clarification before it can be answered accurately.

User question: "{query}"

Retrieved context snippets (these are what we found in our knowledge base):
{context_snippets}

Decide if the user's question is too vague or broad to answer accurately based on the retrieved snippets.
A question needs clarification when:
- The context provides multiple completely different answers depending on a missing detail (e.g., year, department).
- The question is out of context and you need more specifics to help them.

If you can provide a helpful, general answer covering the possibilities, do that instead of asking for clarification.
If you DO need clarification, write ONE short, polite, and customer-friendly question (max 15 words) asking for the missing detail.
Otherwise, return needs_clarification: false.

Respond ONLY with valid JSON (no markdown, no explanation):
{{"needs_clarification": true, "question": "Which department are you asking about?"}}
or
{{"needs_clarification": false}}"""


async def check_clarification(
    query: str,
    candidates: list[dict],
    llm: LLMProvider,
    history: list | None = None,
    rate_limiter: Any = None,
) -> Optional[str]:
    """
    Decide if the query needs clarification before a good answer can be given.
    """
    if not candidates:
        return None

    if history:
        for msg in reversed(history[:-1]):
            if msg.get("role") == "assistant":
                if str(msg.get("content", "")).strip().endswith("?"):
                    return None
                break

    query_words = query.strip().split()
    if len(query_words) <= 4 and not any(
        w in query.lower() for w in ("what", "who", "when", "where", "how", "which", "why")
    ):
        return None

    entity_keys = ("year", "semester", "department", "course")
    diversity: dict[str, set] = {k: set() for k in entity_keys}
    for c in candidates:
        meta = c.get("metadata", {})
        for k in entity_keys:
            val = meta.get(k)
            if val and val not in ("null", None, ""):
                diversity[k].add(str(val))

    has_metadata_ambiguity = any(len(v) >= 3 for v in diversity.values())
    scores = [c.get("score", 0.0) for c in candidates]
    top_score = max(scores) if scores else 0.0
    low_confidence = top_score < 0.35 and len(candidates) >= 3

    if not has_metadata_ambiguity and not low_confidence:
        return None

    snippets = []
    for i, c in enumerate(candidates[:4], 1):
        text = c.get("text", "")[:120].replace("\n", " ")
        snippets.append(f"{i}. {text}…")
    context_snippets = "\n".join(snippets)

    try:
        if rate_limiter:
            await rate_limiter.acquire()
        resp = await llm.generate(
            _CLARIFICATION_PROMPT.format(query=query, context_snippets=context_snippets),
            temperature=0.0,
            max_tokens=80,
        )
        data = parse_json_response(resp.text)
        if data.get("needs_clarification") and data.get("question"):
            return str(data["question"])
    except Exception as e:
        logger.debug("Clarification check failed: %s", type(e).__name__)

    return None


# ── Core Hybrid Retrieval & Reranking ────────────────────────────────────────

async def retrieve_and_rerank(
    client_id: str,
    message: str,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    vectordb: VectorStoreProvider,
    rate_limiter: Any = None,
) -> tuple[list[dict], list[dict]]:
    """
    Runs the Hybrid Retrieval Pipeline:
      - Sub-question decomposition (for multi-part queries)
      - Query metadata extraction & pre-filtering
      - Dense vector search (ChromaDB / VectorStore)
      - Sparse keyword search (In-memory BM25 index)
      - Reciprocal Rank Fusion (RRF)
      - Cross-encoder reranking
    Returns (all_sources, top_candidates).
    """
    DECOMPOSE_SIGNALS = ["and", "also", "as well", "additionally", "what about", "along with"]
    words = message.lower().split()
    should_decompose = (
        len(words) > 12
        and any(sig in message.lower() for sig in DECOMPOSE_SIGNALS)
        and message.count("?") > 1
    )

    if should_decompose:
        sub_questions = await decompose_question(message, llm)
        if rate_limiter:
            await rate_limiter.acquire()
    else:
        sub_questions = [message]

    query_meta = await extract_query_metadata(message, llm)
    where_filter = build_where_filter(query_meta)
    if where_filter:
        logger.debug("Applying metadata filter: %s", where_filter)

    bm25_index = await bm25_registry.ensure_indexed(client_id)

    seen_chunks: set[str] = set()
    all_candidates: list[dict] = []

    for sq in sub_questions:
        if settings.HYDE_ENABLED:
            if rate_limiter:
                await rate_limiter.acquire()
            sq_embedding = await hypothetical_embedding(sq, llm, embeddings)
        else:
            sq_embedding = await embeddings.embed_query(sq)

        # 1. Dense vector candidate retrieval
        dense_candidates = await vectordb.search(
            client_id,
            sq_embedding,
            top_k=25,
            where=where_filter,
        )

        # 2. Sparse BM25 keyword candidate retrieval
        sparse_candidates = bm25_index.search(sq, top_k=25)

        # 3. Hybrid fusion via Reciprocal Rank Fusion (RRF)
        fused_sq_candidates = reciprocal_rank_fusion(
            dense_results=dense_candidates,
            sparse_results=sparse_candidates,
            top_k=25,
            dense_weight=0.6,
            sparse_weight=0.4,
        )

        for r in fused_sq_candidates:
            chunk_key = f"{r.get('metadata', {}).get('doc_id','')}_{r.get('metadata', {}).get('chunk_index','')}"
            if chunk_key not in seen_chunks:
                seen_chunks.add(chunk_key)
                all_candidates.append(r)

    if not all_candidates:
        return [], []

    # Cross-encoder reranking
    if settings.RERANK_ENABLED and len(all_candidates) > settings.RETRIEVAL_TOP_K:
        top_candidates = await reranker_util.rerank(
            message, all_candidates, top_k=settings.RETRIEVAL_TOP_K
        )
    else:
        top_candidates = all_candidates[:settings.RETRIEVAL_TOP_K]

    all_sources = []
    seen_docs = set()
    for c in top_candidates:
        doc_id = c.get("metadata", {}).get("doc_id", "")
        if doc_id not in seen_docs:
            seen_docs.add(doc_id)
            all_sources.append({
                "doc_id": doc_id,
                "filename": c.get("metadata", {}).get("filename", ""),
                "chunk_index": c.get("metadata", {}).get("chunk_index", 0),
                "score": round(c.get("score", 0.0), 3),
                "text_preview": c.get("text", "")[:200],
            })

    return all_sources, top_candidates


async def retrieve_context(
    client_id: str,
    message: str,
    history: list,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    vectordb: VectorStoreProvider,
    context_mode: str = "none",
    context_instructions: str = "",
    context_capacity: int = 4,
    context_variables: Optional[dict] = None,
    rate_limiter: Any = None,
) -> tuple[str, list[dict], list[dict]]:
    """
    High-level retrieval pipeline:
    1. Resolves contextual search query from message and history
    2. Performs hybrid retrieval + reranking
    3. Formats candidates into formatted context string
    Returns: (context_text, all_sources, top_candidates)
    """
    search_query = await resolve_contextual_query(
        message,
        history,
        llm,
        context_mode=context_mode,
        context_instructions=context_instructions,
        context_capacity=context_capacity,
        context_variables=context_variables,
        rate_limiter=rate_limiter,
    )
    all_sources, top_candidates = await retrieve_and_rerank(
        client_id, search_query, llm, embeddings, vectordb, rate_limiter=rate_limiter
    )
    context_text = "\n\n---\n\n".join(c["text"] for c in top_candidates) if top_candidates else ""
    return context_text, all_sources, top_candidates


# Backward compatibility aliases
_extract_query_metadata = extract_query_metadata
_build_where_filter = build_where_filter
_hypothetical_embedding = hypothetical_embedding
_decompose_question = decompose_question
_check_clarification = check_clarification
_resolve_contextual_query = resolve_contextual_query
_retrieve_and_rerank = retrieve_and_rerank
