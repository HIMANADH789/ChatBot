"""
RAG pipeline with six enhancements:
  1. Clarification detection  — asks for context when retrieved chunks are ambiguous
  2. Cross-encoder reranking  — re-scores top-K candidates with a cross-encoder
  3. Contextual chunk headers — chunks already contain document-level context (done at upload)
  4. Metadata filtering       — narrows ChromaDB search using query-extracted entities
  5. HyDE                     — embeds a hypothetical answer instead of the raw query
  6. Semantic query cache      — returns cached answers for near-duplicate queries
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.db.collections import QUERY_LOGS, CLIENTS
from app.db.mongodb import get_db
from app.models.client import get_setup
from app.providers.base import EmbeddingProvider, LLMProvider, VectorStoreProvider
from app.services.chat_service import add_message, get_history, get_or_create_session
from app.utils.rate_limiter import RateLimiter
from app.utils import reranker as reranker_util
from app.utils.query_cache import check_cache, store_cache
from app.services.bm25_search import bm25_registry, reciprocal_rank_fusion

logger = logging.getLogger(__name__)

_rate_limiter = RateLimiter(
    rpm_limit=settings.GEMINI_RPM_LIMIT,
    daily_limit=settings.GEMINI_DAILY_LIMIT,
)

FALLBACK_MESSAGE = (
    "I don't have specific information about that in our knowledge base. "
    "Please contact the administration directly for further assistance."
)

DEFAULT_SYSTEM_PROMPT = """You are a helpful, knowledgeable, and polite AI assistant for the institution. You assist students, parents, faculty, and visitors by answering questions accurately using the official information provided to you.

Key Instructions:
- Answer naturally, clearly, and directly.
- For simple greetings or conversational pleasantries (e.g., "hi", "hello", "thank you"), reply in a warm, friendly, and concise manner (1-2 sentences).
- For informational questions, provide accurate and well-structured answers. When listing steps, rules, fees, dates, or requirements, use clean bullet points (•).
- Never fabricate information. Never output internal thought processes, reasoning steps, conflict resolutions, scratchpads, or <think> tags. Provide ONLY the direct final response for the user."""

CONVERSATIONAL_TRIGGERS = {
    "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
    "how are you", "thanks", "thank you", "bye", "goodbye", "ok", "okay",
    "what can you do", "help", "who are you", "what are you",
}

NON_NAME_WORDS = {
    "a", "an", "the", "here", "there", "ready", "new", "student", "interested",
    "looking", "going", "trying", "asking", "wondering", "writing", "calling",
    "fine", "good", "okay", "ok", "happy", "sure", "sorry", "just", "also",
    "can", "could", "would", "please", "want", "need", "will", "should", "may",
    "how", "what", "where", "which", "why", "when", "is", "are", "am", "give", "show", "tell",
}

STOP_AFTER_WORDS = {
    "from", "in", "at", "and", "with", "for", "here", "to", "who", "seeking", "wanting",
    "can", "could", "would", "please", "want", "need", "will", "should", "may",
    "how", "what", "where", "which", "why", "when", "is", "are", "am", "give", "show", "tell",
}

def extract_user_name(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"\b(?:my name is|i am|i'm|this is|call me)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)\b",
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            parts = candidate.split()
            valid_parts = []
            for p in parts:
                if p.lower() in STOP_AFTER_WORDS or p.lower() in NON_NAME_WORDS:
                    break
                if len(p) >= 2:
                    valid_parts.append(p.title())
            if valid_parts:
                return " ".join(valid_parts)
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_conversational(message: str) -> bool:
    lower = message.lower().strip().rstrip("?!.")
    if lower in CONVERSATIONAL_TRIGGERS:
        return True
    if len(lower.split()) <= 3 and any(t in lower for t in CONVERSATIONAL_TRIGGERS):
        return True
    return False


async def _get_media_triggers(message: str, context: str, profile: dict, history: list, llm: LLMProvider):
    from app.services.context_media_service import (
        evaluate_menu_triggers,
        evaluate_image_triggers,
    )
    menu_tree = profile.get("menu_tree", [])
    context_imgs = profile.get("context_images", [])
    matched_menu = await evaluate_menu_triggers(message, menu_tree, history, llm)
    matched_images = await evaluate_image_triggers(message, context, context_imgs, history, llm)
    return matched_menu, matched_images


def _clean_markdown(text: str) -> str:
    if not text:
        return ""

    # 1. Remove closed <think>...</think>, <thought>...</thought>, <reasoning>...</reasoning> blocks
    text = re.sub(r"<(think|thought|reasoning)>[\s\S]*?</\1>", "", text, flags=re.IGNORECASE).strip()

    # 2. Remove unclosed <think>, <thought>, or <reasoning> blocks (e.g. max_tokens cutoff or opening tag without close)
    if re.search(r"<(think|thought|reasoning)>", text, flags=re.IGNORECASE):
        text = re.sub(r"<(think|thought|reasoning)>[\s\S]*", "", text, flags=re.IGNORECASE).strip()

    # 3. Strip any stray closing or opening thinking tags
    text = re.sub(r"</?(think|thought|reasoning)>", "", text, flags=re.IGNORECASE).strip()

    # 4. Remove chain-of-thought / reasoning meta-monologue patterns generated by models like Qwen or DeepSeek
    # Matches patterns like: "Here's a thinking process:", "Thinking Process:", "Conflict Resolution:", etc.
    thought_headers = [
        r"^Here'?s a thinking process:?[\s\S]*?(?=\n\n|\Z)",
        r"^(?:\*?\*?(?:Thinking Process|Thought Process|Internal reasoning|Chain of Thought|Reasoning Process)\*?\*?:?)[\s\S]*?(?=\n\n|\Z)",
        r"^(?:\*?\*?Conflict Resolution\*?\*?:?|Conflict:\*?|Decision:\*?|Re-reading the System Prompt:\*?|Re-reading the User Prompt:\*?)[\s\S]*?(?=\n\n|\Z)",
    ]
    for pattern in thought_headers:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE).strip()

    # 5. Check if the text is dominated by an internal conflict/reasoning debate (common in Qwen when resolving instructions)
    # e.g., lines containing "Conflict Resolution:*", "Decision:*", "CRITICAL OUTPUT INSTRUCTIONS", "Resolution:*"
    if any(k in text for k in ("Conflict Resolution:", "Conflict Resolution:*", "CRITICAL OUTPUT INSTRUCTIONS", "Decision:*", "Resolution:*")):
        # Try to find where the actual answer begins (often after "Decision:*" or after the last reasoning paragraph)
        # Look for explicit answer marker
        answer_match = re.search(r"(?:Final Answer|Answer|Response|Assistant):\s*([\s\S]+)", text, flags=re.IGNORECASE)
        if answer_match:
            text = answer_match.group(1).strip()
        else:
            # Split into paragraphs and filter out paragraphs that contain meta-reasoning words
            paragraphs = text.split("\n\n")
            clean_paras = []
            for p in paragraphs:
                p_lower = p.lower()
                if any(bad in p_lower for bad in (
                    "conflict resolution", "system prompt", "user prompt", "rlhf",
                    "critical output instructions", "hard constraint", "specific prompt instruction",
                    "decision:*", "resolution:*", "standard constraint"
                )):
                    continue
                clean_paras.append(p)
            text = "\n\n".join(clean_paras).strip()

    # 6. Standard markdown cleanup
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def _filter_thinking_stream(raw_stream):
    """
    Suppresses <think>...</think>, <thought>...</thought>, and <reasoning>...</reasoning> blocks
    in real-time during token streaming so internal reasoning is never emitted to the user.
    """
    in_think = False
    buffer = ""
    emitted_any = False
    think_accumulator = ""

    async for chunk in raw_stream:
        buffer += chunk

        while buffer:
            if not in_think:
                lower_buf = buffer.lower()
                think_pos = lower_buf.find("<think>")
                thought_pos = lower_buf.find("<thought>")
                reason_pos = lower_buf.find("<reasoning>")

                positions = [p for p in (think_pos, thought_pos, reason_pos) if p != -1]
                if positions:
                    first_pos = min(positions)
                    pre_text = buffer[:first_pos]
                    if pre_text:
                        if not emitted_any:
                            pre_text = re.sub(r"^Here'?s a thinking process:?\s*", "", pre_text, flags=re.IGNORECASE)
                        if pre_text:
                            emitted_any = True
                            yield pre_text

                    tag_len = 7 if (first_pos == think_pos) else (9 if first_pos == thought_pos else 11)
                    buffer = buffer[first_pos + tag_len:]
                    in_think = True
                else:
                    tag_start = buffer.rfind("<")
                    if tag_start != -1 and (len(buffer) - tag_start) <= 11 and (
                        "<think>".startswith(buffer[tag_start:].lower()) or
                        "<thought>".startswith(buffer[tag_start:].lower()) or
                        "<reasoning>".startswith(buffer[tag_start:].lower())
                    ):
                        emit_text = buffer[:tag_start]
                        buffer = buffer[tag_start:]
                        if emit_text:
                            if not emitted_any:
                                emit_text = re.sub(r"^Here'?s a thinking process:?\s*", "", emit_text, flags=re.IGNORECASE)
                            if emit_text:
                                emitted_any = True
                                yield emit_text
                        break
                    else:
                        emit_text = buffer
                        buffer = ""
                        if not emitted_any:
                            emit_text = re.sub(r"^Here'?s a thinking process:?\s*", "", emit_text, flags=re.IGNORECASE)
                        if emit_text:
                            emitted_any = True
                            yield emit_text
            else:
                lower_buf = buffer.lower()
                close_think = lower_buf.find("</think>")
                close_thought = lower_buf.find("</thought>")
                close_reason = lower_buf.find("</reasoning>")

                close_positions = [p for p in (close_think, close_thought, close_reason) if p != -1]
                if close_positions:
                    first_close = min(close_positions)
                    think_accumulator += buffer[:first_close]
                    tag_len = 8 if (first_close == close_think) else (10 if first_close == close_thought else 12)
                    buffer = buffer[first_close + tag_len:]
                    in_think = False
                else:
                    close_tag_start = buffer.rfind("<")
                    if close_tag_start != -1 and (len(buffer) - close_tag_start) <= 12 and (
                        "</think>".startswith(buffer[close_tag_start:].lower()) or
                        "</thought>".startswith(buffer[close_tag_start:].lower()) or
                        "</reasoning>".startswith(buffer[close_tag_start:].lower())
                    ):
                        think_accumulator += buffer[:close_tag_start]
                        buffer = buffer[close_tag_start:]
                        break
                    else:
                        think_accumulator += buffer
                        buffer = ""

    if not emitted_any:
        fallback_text = _clean_markdown(think_accumulator or buffer)
        if fallback_text:
            yield fallback_text


def _parse_json_response(text: str) -> dict:
    """Best-effort JSON extraction from an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text.strip())
    except Exception:
        return {}


# ── Enhancement 4: Query-time metadata extraction ────────────────────────────

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


async def _extract_query_metadata(query: str, llm: LLMProvider) -> dict:
    try:
        resp = await llm.generate(_QUERY_METADATA_PROMPT.format(query=query), temperature=0.0, max_tokens=150)
        return _parse_json_response(resp.text)
    except Exception:
        return {}


def _build_where_filter(metadata: dict) -> Optional[dict]:
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




# ── Enhancement 5: HyDE ──────────────────────────────────────────────────────

_HYDE_PROMPT = """Write a brief, factual answer to this question as if it came from an official document.
Keep it under 100 words. Be specific and direct.

Question: {query}
Answer:"""

# Circuit breaker: skip HyDE for 60s after 3 consecutive failures
_hyde_fail_count = 0
_hyde_open_until: float = 0.0


async def _hypothetical_embedding(
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


# ── Enhancement 1: Clarification detection ───────────────────────────────────

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
{"needs_clarification": true, "question": "Which department are you asking about?"}
or
{"needs_clarification": false}"""


async def _check_clarification(
    query: str,
    candidates: list[dict],
    llm: LLMProvider,
    history: list | None = None,
) -> Optional[str]:
    """
    Decide if the query needs clarification before a good answer can be given.

    Two-pass approach:
    1. Fast heuristics: skip unless there is genuine metadata diversity OR
       very low confidence across all retrieved chunks.
    2. If heuristic fires, ask LLM to confirm and generate the question.
    Returns a clarifying question string, or None if the answer can proceed.
    """
    if not candidates:
        return None

    # ── Skip if user is answering a previous clarification ───────────────────
    # If the last assistant message ended with "?", the user is replying to our
    # clarification — don't loop back into another clarification check.
    if history:
        for msg in reversed(history[:-1]):  # exclude last user message
            if msg.get("role") == "assistant":
                if str(msg.get("content", "")).strip().endswith("?"):
                    return None
                break  # only look at the most recent assistant turn

    # ── Skip for very short clarification-answering patterns ─────────────────
    # A reply like "Computer Science" or "3rd year CSE" should go straight to answer.
    query_words = query.strip().split()
    if len(query_words) <= 4 and not any(
        w in query.lower() for w in ("what", "who", "when", "where", "how", "which", "why")
    ):
        return None

    # ── Heuristic 1: metadata diversity ──────────────────────────────────────
    entity_keys = ("year", "semester", "department", "course")
    diversity: dict[str, set] = {k: set() for k in entity_keys}
    for c in candidates:
        meta = c.get("metadata", {})
        for k in entity_keys:
            val = meta.get(k)
            if val and val not in ("null", None, ""):
                diversity[k].add(str(val))

    # Require at least 3 distinct values in a field to flag ambiguity
    has_metadata_ambiguity = any(len(v) >= 3 for v in diversity.values())

    # ── Heuristic 2: very low confidence ─────────────────────────────────────
    scores = [c.get("score", 0.0) for c in candidates]
    top_score = max(scores) if scores else 0.0
    # Flag when top retrieval score is fairly low and there are multiple candidates
    low_confidence = top_score < 0.35 and len(candidates) >= 3

    if not has_metadata_ambiguity and not low_confidence:
        return None

    # ── LLM-based clarification check ────────────────────────────────────────
    snippets = []
    for i, c in enumerate(candidates[:4], 1):
        text = c.get("text", "")[:120].replace("\n", " ")
        snippets.append(f"{i}. {text}…")
    context_snippets = "\n".join(snippets)

    try:
        await _rate_limiter.acquire()
        resp = await llm.generate(
            _CLARIFICATION_PROMPT.format(query=query, context_snippets=context_snippets),
            temperature=0.0,
            max_tokens=80,
        )
        data = _parse_json_response(resp.text)
        if data.get("needs_clarification") and data.get("question"):
            return str(data["question"])
    except Exception as e:
        logger.debug("Clarification check failed: %s", type(e).__name__)

    return None


# ── Sub-question decomposition (unchanged) ────────────────────────────────────

async def _decompose_question(message: str, llm: LLMProvider) -> list[str]:
    prompt = f"""You are a query decomposition assistant.
Given a user question, break it into 1-3 focused sub-questions for a knowledge base lookup.
If the question is already simple, return just the original question.

User question: {message}

Return ONLY a numbered list of sub-questions, nothing else."""
    response = await llm.generate(prompt, temperature=0.0, max_tokens=200)
    lines = [l.strip() for l in response.text.strip().splitlines() if l.strip()]
    sub_questions = [line.lstrip("0123456789. ").strip() for line in lines if line]
    return [q for q in sub_questions if q] or [message]


# ── Enhancement 7: Context-Adaptive RAG Query Resolution ──────────────────────

_CONTEXT_REWRITE_PROMPT = """You are a precise search query reformulator for an institutional knowledge assistant.
Given the conversation history and the latest user message, rewrite the user's latest message into a single standalone, unambiguous search query for vector retrieval.

Instructions:
1. If the user refers to something from previous turns with pronouns ("it", "its", "they", "their", "this", "that", "those", "same"), replace them with the explicit subject/entity mentioned previously (e.g. course name, department, program, fee category).
2. If the user asks a follow-up fragment (e.g. "what is the fee?", "how to apply?", "eligibility?", "what about hostel?"), combine it with the specific subject being discussed into a complete query (e.g. "B.Tech Computer Science fee structure", "MCA admission eligibility").
3. Specific tracking criteria for this institution:
{context_instructions}
4. If the latest user message is already clear, complete, and self-contained, or is a simple greeting, return it UNCHANGED.
5. Do NOT answer the question. Do NOT add preamble or reasoning. Return ONLY the rewritten search query.

Conversation history:
{history_text}

Latest user message: {query}
Standalone search query:"""


async def _resolve_contextual_query(
    query: str,
    history: list,
    llm: LLMProvider,
    context_mode: str = "none",
    context_instructions: str = "",
    context_capacity: int = 4,
) -> str:
    """
    Context-Adaptive RAG: resolves pronouns, elided subjects, and conversational context
    into a self-contained search query before vector retrieval.
    """
    effective_mode = context_mode or "none"

    if effective_mode == "none" or not history or len(history) <= 1:
        return query

    # Trim history to context_capacity turns (each turn has user+assistant = 2 msgs)
    history_slice = history[-(context_capacity * 2 + 1):-1]
    if not history_slice:
        return query

    # In adaptive mode, check if rewrite is needed (pronoun / fragment / elision)
    if effective_mode == "adaptive":
        lower = query.lower().strip()
        pronoun_triggers = {
            "it", "its", "they", "them", "their", "theirs", "this", "that", "these", "those",
            "he", "him", "his", "she", "her", "hers", "same", "there", "then", "above", "mentioned"
        }
        words = re.findall(r"\b\w+\b", lower)
        has_pronoun = any(w in pronoun_triggers for w in words)
        is_fragment = len(words) <= 5 and any(w in lower for w in (
            "fee", "cost", "eligibility", "process", "date", "deadline", "how", "what", "where",
            "when", "apply", "criteria", "contact", "syllabus", "hostel", "cutoff", "quota", "seat",
            "timing", "requirement", "placement", "faculty", "location", "address"
        ))
        # If query is already long and has no pronoun/fragment, skip rewrite
        if not has_pronoun and not is_fragment and len(words) > 6:
            return query

    lines = []
    for msg in history_slice:
        role = "User" if msg.get("role") == "user" else "Assistant"
        content = str(msg.get("content", "")).strip().replace("\n", " ")
        if content:
            lines.append(f"{role}: {content[:200]}")
    history_text = "\n".join(lines)
    if not history_text:
        return query

    instructions = context_instructions.strip() if context_instructions else "Preserve specific courses, branches, departments, dates, fees, and admission criteria."

    try:
        await _rate_limiter.acquire()
        prompt = _CONTEXT_REWRITE_PROMPT.format(
            query=query,
            history_text=history_text,
            context_instructions=instructions,
        )
        resp = await llm.generate(prompt, temperature=0.0, max_tokens=100)
        rewritten = _clean_markdown(resp.text).strip().strip('"').strip("'")
        if rewritten and len(rewritten) >= 3 and not rewritten.lower().startswith(("here is", "i have", "rewritten", "standalone")):
            logger.info("Contextual RAG query resolved: '%s' -> '%s'", query, rewritten)
            return rewritten
    except Exception as e:
        logger.debug("Contextual query rewrite failed: %s", e)

    return query


# ── Core retrieval (shared by query() and query_stream()) ─────────────────────

async def _retrieve_and_rerank(
    client_id: str,
    message: str,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    vectordb: VectorStoreProvider,
) -> tuple[list[dict], list[dict]]:
    """
    Runs the Hybrid Retrieval Pipeline:
      - Optional HyDE embedding
      - Optional metadata filtering
      - Sub-question decomposition (for complex multi-part queries)
      - Dense vector search (ChromaDB / VectorStore)
      - Sparse keyword search (In-memory BM25 index)
      - Reciprocal Rank Fusion (RRF) to combine dense + sparse candidate scores
      - Cross-encoder reranking for top precision
    Returns (all_sources, reranked_candidates).
    """
    DECOMPOSE_SIGNALS = ["and", "also", "as well", "additionally", "what about", "along with"]
    words = message.lower().split()
    should_decompose = (
        len(words) > 12
        and any(sig in message.lower() for sig in DECOMPOSE_SIGNALS)
        and message.count("?") > 1
    )

    if should_decompose:
        sub_questions = await _decompose_question(message, llm)
        await _rate_limiter.acquire()
    else:
        sub_questions = [message]

    # Enhancement 4: extract metadata from query for pre-filtering
    query_meta = await _extract_query_metadata(message, llm)
    where_filter = _build_where_filter(query_meta)
    if where_filter:
        logger.debug(f"Applying metadata filter: {where_filter}")

    # Ensure BM25 index is prepared for this tenant
    bm25_index = await bm25_registry.ensure_indexed(client_id)

    seen_chunks: set[str] = set()
    all_candidates: list[dict] = []

    for sq in sub_questions:
        # Enhancement 5: HyDE
        if settings.HYDE_ENABLED and not _is_conversational(sq):
            await _rate_limiter.acquire()
            sq_embedding = await _hypothetical_embedding(sq, llm, embeddings)
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

    # Enhancement 2: Cross-encoder reranking
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


def _build_rag_prompt(
    context: str,
    history_text: str,
    message: str,
    context_variables: Optional[dict] = None,
) -> str:
    user_context_block = ""
    active_name = None
    if context_variables:
        active_vars = [f"• {k.replace('_', ' ').title()}: {v}" for k, v in context_variables.items() if v]
        if active_vars:
            user_context_block = "Active User Session Profile Context (Dynamic State):\n" + "\n".join(active_vars) + "\n\n"
        active_name = context_variables.get("user_name")

    name_instruction = f"If addressing the user by name, address them as '{active_name}'." if active_name else ""

    return f"""Context from knowledge base:
{context}

{user_context_block}{history_text}
User question: {message}

Answer guidelines:
1. Answer using ONLY the context above. Provide complete, accurate, and direct information with maximum factual density. {name_instruction}
2. Keep your answer crisp, concise, and mobile-friendly. Avoid long wordy intros or fluff.
3. Structure your answer clearly using clean bullet points (•) for details, course breakdown, eligibility, or steps.
4. Do NOT invent or assume any information not present in the context.
5. Speak naturally, directly, and professionally. Never say "the context states", "based on the document", or similar meta-phrases.
6. Do NOT suggest contacting anyone or any department unless the question is completely unanswerable from the context.
7. Do NOT add a "Sources" section or mention internal document filenames.
8. Format: use bullet points (•) for lists, short paragraphs, normal sentence casing. No raw markdown headers (##, ###).
9. Output ONLY the direct final answer. Do NOT output <think> tags, reasoning steps, or scratchpad text."""


# ── Public API: non-streaming ─────────────────────────────────────────────────

async def query(
    client_id: str,
    message: str,
    session_id: Optional[str],
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    vectordb: VectorStoreProvider,
    channel: str = "widget",
    context_variables: Optional[dict] = None,
) -> dict:
    start = time.time()
    db = get_db()

    session_id = await get_or_create_session(client_id, session_id)
    await add_message(session_id, "user", message)

    client = await db[CLIENTS].find_one({"client_id": client_id})
    cs = (client or {}).get("settings", {})
    system_prompt = DEFAULT_SYSTEM_PROMPT
    # Load pre-compiled client runtime profile snapshot (O(1) in-memory cache)
    from app.services.profile_compiler import get_compiled_profile
    profile = await get_compiled_profile(client_id, channel)
    system_prompt = profile.get("compiled_system_prompt") or DEFAULT_SYSTEM_PROMPT
    ctx_cfg = profile.get("context_config", {})
    context_mode = ctx_cfg.get("mode") or cs.get("context_mode", "none")
    raw_cap = ctx_cfg.get("capacity") if ctx_cfg.get("capacity") is not None else cs.get("context_capacity")
    context_capacity = int(raw_cap) if raw_cap is not None else 4

    # Extract dynamic user name from introduction patterns (e.g. "I am Tarun", "my name is Amit")
    extracted_name = extract_user_name(message)
    if context_variables is None:
        context_variables = {}
    if extracted_name:
        context_variables["user_name"] = extracted_name

    active_name = context_variables.get("user_name") or extracted_name
    if active_name:
        system_prompt += f"\n\nMANDATORY VISITOR IDENTITY INSTRUCTION:\n- Visitor's active name is '{active_name}'. Always address them warmly as '{active_name}' in your response."

    # If context is disabled ("none") or context capacity is 0, operate completely stateless
    if context_mode == "none" or context_capacity <= 0:
        max_history = 0
        history = []
    else:
        configured_history = int(cs.get("max_history_turns", 3) or 3)
        max_history = min(configured_history, context_capacity) if context_capacity > 0 else configured_history
        history = await get_history(session_id, max_turns=max_history)

    # Session query limit
    from app.services.chat_service import count_session_queries
    query_count = await count_session_queries(session_id)
    _setup_cfg = get_setup((client or {}).get("settings", {}), channel)
    max_qs = _setup_cfg.get("max_queries_per_session", 50)
    if max_qs > 0 and query_count >= max_qs:
        limit_msg = f"You've reached the session limit of {max_qs} messages. Please start a new conversation."
        await add_message(session_id, "assistant", limit_msg)
        response_time = int((time.time() - start) * 1000)
        await _log_query(client_id, session_id, message, limit_msg, [], response_time, "limit", {}, channel=channel)
        return {"response": limit_msg, "sources": [], "session_id": session_id}

    history_text = _build_history_text(history)

    # Conversational shortcut — no retrieval
    if _is_conversational(message) or (extracted_name and len(message.split()) <= 6):
        await _rate_limiter.acquire()
        if extracted_name:
            text = f"Hello {extracted_name}! What would you like to explore about our institution today?"
            model_name = "identity_parser"
            usage_stats = {}
        else:
            conv_prompt = f"{history_text}\nUser: {message}\n\nRespond directly as a friendly front desk assistant in 1-2 sentences."
            llm_response = await llm.generate(conv_prompt, system_prompt=system_prompt, temperature=0.4, max_tokens=256)
            text = _clean_markdown(llm_response.text)
            model_name = llm_response.model
            usage_stats = llm_response.usage
        if not text or len(text.strip()) == 0:
            text = "Hello! How can I assist you today?"
        await add_message(session_id, "assistant", text)
        response_time = int((time.time() - start) * 1000)
        await _log_query(client_id, session_id, message, text, [], response_time, model_name, usage_stats, channel=channel)

        from app.services.context_media_service import (
            evaluate_menu_triggers,
            evaluate_image_triggers,
        )
        menu_tree = profile.get("menu_tree", [])
        context_imgs = profile.get("context_images", [])
        matched_menu = await evaluate_menu_triggers(message, menu_tree, history, llm)
        matched_images = await evaluate_image_triggers(message, "", context_imgs, history, llm)

        if matched_menu:
            label = matched_menu.get("label") or matched_menu.get("title") or "our options"
            name_prefix = f"Hello {extracted_name}! " if extracted_name else "Hello! "
            text = f"{name_prefix}Welcome to SV Professional Institute. Here are the available {label.lower()}:"

        return {
            "response": text,
            "sources": [],
            "session_id": session_id,
            "interactive_menu": matched_menu,
            "context_images": matched_images,
        }

    can_proceed = await _rate_limiter.acquire()
    if not can_proceed:
        llm = _get_fallback_llm(llm)

    # Context-Adaptive RAG settings from compiled snapshot
    ctx_cfg = profile.get("context_config", {})
    context_mode = ctx_cfg.get("mode", "none")
    context_instructions = ctx_cfg.get("instructions", "")
    context_capacity = int(ctx_cfg.get("capacity", 4))

    # Resolve contextual query (resolves pronouns / follow-up fragments)
    search_query = await _resolve_contextual_query(
        message,
        history,
        llm,
        context_mode=context_mode,
        context_instructions=context_instructions,
        context_capacity=context_capacity,
    )

    # Enhancement 6: semantic cache check
    if settings.CACHE_ENABLED:
        query_embedding_for_cache = await embeddings.embed_query(search_query)
        cached = await check_cache(client_id, query_embedding_for_cache)
        if cached:
            logger.debug("Cache hit for query: %s", search_query[:60])
            await add_message(session_id, "assistant", cached["response"], cached["sources"])
            response_time = int((time.time() - start) * 1000)
            await _log_query(client_id, session_id, message, cached["response"], cached["sources"], response_time, "cache", {}, channel=channel)
            matched_menu, matched_images = await _get_media_triggers(message, "", profile, history, llm)
            return {
                "response": cached["response"],
                "sources": cached["sources"],
                "session_id": session_id,
                "interactive_menu": matched_menu,
                "context_images": matched_images,
            }

    # Retrieve + rerank
    all_sources, top_candidates = await _retrieve_and_rerank(client_id, search_query, llm, embeddings, vectordb)

    if not top_candidates:
        logger.info("No vector document chunks found for query '%s'. Generating front-desk guidance via LLM.", search_query)
        await _rate_limiter.acquire()
        guidance_prompt = f"""{history_text}
User message: {message}

Instructions:
1. You are the AI Front Desk Assistant for this institution. Follow your system prompt persona, responsibilities, and tone.
2. If the user introduces themselves (e.g. gives their name, qualification, or educational background) or asks for career guidance, courses, or general information, address them warmly by name if provided, introduce the relevant programs offered (e.g. CA, CMA, ACCA, CS, B.Com), and explain how they can get started.
3. If they asked for specific verified facts (such as exact rupee fee structures or official registration dates) that require official document verification and none are available, provide a helpful general overview of the program and invite them to speak with the administrative desk for the latest official fee schedules.
4. Keep the response concise, mobile-friendly (use clean bullet points if listing courses), and end with an engaging next-step question.
5. Output ONLY the direct response. Do NOT output thinking tags (<think>...</think>) or internal reasoning."""

        llm_response = await llm.generate(guidance_prompt, system_prompt=system_prompt, temperature=0.3, max_tokens=650)
        text = _clean_markdown(llm_response.text)
        if not text or len(text.strip()) == 0:
            text = FALLBACK_MESSAGE

        await add_message(session_id, "assistant", text)
        response_time = int((time.time() - start) * 1000)
        await _log_query(client_id, session_id, message, text, [], response_time, llm_response.model, llm_response.usage, channel=channel)

        matched_menu, matched_images = await _get_media_triggers(message, "", profile, history, llm)
        return {
            "response": text,
            "sources": [],
            "session_id": session_id,
            "interactive_menu": matched_menu,
            "context_images": matched_images,
        }

    # Enhancement 1: clarification check
    clarification = await _check_clarification(search_query, top_candidates, llm, history=history)
    if clarification:
        await add_message(session_id, "assistant", clarification)
        response_time = int((time.time() - start) * 1000)
        await _log_query(client_id, session_id, message, clarification, [], response_time, llm.get_model_name(), {}, channel=channel)
        matched_menu, matched_images = await _get_media_triggers(message, "", profile, history, llm)
        return {
            "response": clarification,
            "sources": [],
            "session_id": session_id,
            "interactive_menu": matched_menu,
            "context_images": matched_images,
        }

    context = "\n\n---\n\n".join(c["text"] for c in top_candidates)
    prompt = _build_rag_prompt(context, history_text, message, context_variables=context_variables)

    can_proceed = await _rate_limiter.acquire()
    if not can_proceed:
        llm = _get_fallback_llm(llm)

    llm_response = await llm.generate(prompt, system_prompt=system_prompt, temperature=0.2, max_tokens=1024)
    text = _clean_markdown(llm_response.text)
    if not text or len(text.strip()) == 0:
        text = FALLBACK_MESSAGE

    await add_message(session_id, "assistant", text, all_sources)
    response_time = int((time.time() - start) * 1000)
    await _log_query(client_id, session_id, message, text, all_sources, response_time, llm_response.model, llm_response.usage, channel=channel)

    # Store in semantic cache (only cache valid non-fallback answers)
    if settings.CACHE_ENABLED and text != FALLBACK_MESSAGE and len(text) >= 20:
        await store_cache(client_id, search_query, query_embedding_for_cache, text, all_sources)

    matched_menu, matched_images = await _get_media_triggers(message, context, profile, history, llm)

    return {
        "response": text,
        "sources": all_sources,
        "session_id": session_id,
        "interactive_menu": matched_menu,
        "context_images": matched_images,
    }


# ── Public API: streaming ─────────────────────────────────────────────────────

async def query_stream(
    client_id: str,
    message: str,
    session_id: Optional[str],
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    vectordb: VectorStoreProvider,
    channel: str = "widget",
    context_variables: Optional[dict] = None,
):
    start = time.time()
    db = get_db()

    session_id = await get_or_create_session(client_id, session_id)
    await add_message(session_id, "user", message)

    client = await db[CLIENTS].find_one({"client_id": client_id})
    cs = (client or {}).get("settings", {})
    system_prompt = DEFAULT_SYSTEM_PROMPT

    from app.services.profile_compiler import get_compiled_profile
    profile = await get_compiled_profile(client_id, channel)

    system_prompt = profile.get("compiled_system_prompt") or DEFAULT_SYSTEM_PROMPT
    ctx_cfg = profile.get("context_config", {})
    context_mode = ctx_cfg.get("mode") or cs.get("context_mode", "none")
    raw_cap = ctx_cfg.get("capacity") if ctx_cfg.get("capacity") is not None else cs.get("context_capacity")
    context_capacity = int(raw_cap) if raw_cap is not None else 4

    # Extract dynamic user name from introduction patterns (e.g. "I am Tarun", "my name is Amit")
    extracted_name = extract_user_name(message)
    if context_variables is None:
        context_variables = {}
    if extracted_name:
        context_variables["user_name"] = extracted_name

    active_name = context_variables.get("user_name") or extracted_name
    if active_name:
        system_prompt += f"\n\nMANDATORY VISITOR IDENTITY INSTRUCTION:\n- Visitor's active name is '{active_name}'. Always address them warmly as '{active_name}' in your response."

    # If context is disabled ("none") or context capacity is 0, operate completely stateless
    if context_mode == "none" or context_capacity <= 0:
        max_history = 0
        history = []
    else:
        configured_history = int(cs.get("max_history_turns", 3) or 3)
        max_history = min(configured_history, context_capacity) if context_capacity > 0 else configured_history
        history = await get_history(session_id, max_turns=max_history)

    # Session query limit
    from app.services.chat_service import count_session_queries
    query_count = await count_session_queries(session_id)
    _setup_cfg = get_setup((client or {}).get("settings", {}), channel)
    max_qs = _setup_cfg.get("max_queries_per_session", 50)
    if max_qs > 0 and query_count >= max_qs:
        limit_msg = f"You've reached the session limit of {max_qs} messages. Please start a new conversation."
        await add_message(session_id, "assistant", limit_msg)
        response_time = int((time.time() - start) * 1000)
        await _log_query(client_id, session_id, message, limit_msg, [], response_time, "limit", {}, channel=channel)
        yield {"type": "token", "text": limit_msg}
        yield {"type": "done", "session_id": session_id, "sources": []}
        return

    history_text = _build_history_text(history)

    # Conversational shortcut
    if _is_conversational(message) or (extracted_name and len(message.split()) <= 6):
        await _rate_limiter.acquire()
        full_text = ""
        model_name = "identity_parser"
        if extracted_name:
            full_text = f"Hello {extracted_name}! What would you like to explore about our institution today?"
            yield {"type": "token", "text": full_text}
        else:
            conv_prompt = f"{history_text}\nUser: {message}\n\nRespond directly as a friendly front desk assistant in 1-2 sentences."
            raw_gen = llm.generate_stream(conv_prompt, system_prompt=system_prompt, temperature=0.4, max_tokens=256)
            async for chunk in _filter_thinking_stream(raw_gen):
                full_text += chunk
                yield {"type": "token", "text": chunk}
            full_text = _clean_markdown(full_text)
            model_name = llm.get_model_name()
            if not full_text:
                full_text = "Hello! How can I assist you today?"
                yield {"type": "token", "text": full_text}
        await add_message(session_id, "assistant", full_text)
        response_time = int((time.time() - start) * 1000)
        await _log_query(client_id, session_id, message, full_text, [], response_time, model_name, {}, channel=channel)

        from app.services.context_media_service import (
            evaluate_menu_triggers,
            evaluate_image_triggers,
        )
        menu_tree = profile.get("menu_tree", [])
        context_imgs = profile.get("context_images", [])
        matched_menu = await evaluate_menu_triggers(message, menu_tree, history, llm)
        matched_images = await evaluate_image_triggers(message, "", context_imgs, history, llm)

        yield {
            "type": "done",
            "session_id": session_id,
            "sources": [],
            "interactive_menu": matched_menu,
            "context_images": matched_images,
        }
        return

    can_proceed = await _rate_limiter.acquire()
    if not can_proceed:
        llm = _get_fallback_llm(llm)

    # Context-Adaptive RAG settings from compiled snapshot
    ctx_cfg = profile.get("context_config", {})
    context_mode = ctx_cfg.get("mode", "none")
    context_instructions = ctx_cfg.get("instructions", "")
    context_capacity = int(ctx_cfg.get("capacity", 4))

    # Resolve contextual query (resolves pronouns / follow-up fragments)
    search_query = await _resolve_contextual_query(
        message,
        history,
        llm,
        context_mode=context_mode,
        context_instructions=context_instructions,
        context_capacity=context_capacity,
    )

    # Enhancement 6: semantic cache
    query_embedding_for_cache = None
    if settings.CACHE_ENABLED:
        query_embedding_for_cache = await embeddings.embed_query(search_query)
        cached = await check_cache(client_id, query_embedding_for_cache)
        if cached:
            logger.debug("Cache hit (stream) for query: %s", search_query[:60])
            await add_message(session_id, "assistant", cached["response"], cached["sources"])
            response_time = int((time.time() - start) * 1000)
            await _log_query(client_id, session_id, message, cached["response"], cached["sources"], response_time, "cache", {}, channel=channel)
            matched_menu, matched_images = await _get_media_triggers(message, "", profile, history, llm)
            yield {"type": "token", "text": cached["response"]}
            yield {
                "type": "done",
                "session_id": session_id,
                "sources": cached["sources"],
                "interactive_menu": matched_menu,
                "context_images": matched_images,
            }
            return

    # Retrieve + rerank
    all_sources, top_candidates = await _retrieve_and_rerank(client_id, search_query, llm, embeddings, vectordb)

    if not top_candidates:
        logger.info("No vector document chunks found for query '%s'. Streaming front-desk guidance via LLM.", search_query)
        await _rate_limiter.acquire()
        guidance_prompt = f"""{history_text}
User message: {message}

Instructions:
1. You are the AI Front Desk Assistant for this institution. Follow your system prompt persona, responsibilities, and tone.
2. If the user introduces themselves (e.g. gives their name, qualification, or educational background) or asks for career guidance, courses, or general information, address them warmly by name if provided, introduce the relevant programs offered (e.g. CA, CMA, ACCA, CS, B.Com), and explain how they can get started.
3. If they asked for specific verified facts (such as exact rupee fee structures or official registration dates) that require official document verification and none are available, provide a helpful general overview of the program and invite them to speak with the administrative desk for the latest official fee schedules.
4. Keep the response concise, mobile-friendly (use clean bullet points if listing courses), and end with an engaging next-step question.
5. Output ONLY the direct response. Do NOT output thinking tags (<think>...</think>) or internal reasoning."""

        full_text = ""
        raw_gen = llm.generate_stream(guidance_prompt, system_prompt=system_prompt, temperature=0.3, max_tokens=1024)
        async for chunk in _filter_thinking_stream(raw_gen):
            full_text += chunk
            yield {"type": "token", "text": chunk}
        full_text = _clean_markdown(full_text)
        if not full_text:
            full_text = FALLBACK_MESSAGE
            yield {"type": "token", "text": FALLBACK_MESSAGE}

        await add_message(session_id, "assistant", full_text)
        response_time = int((time.time() - start) * 1000)
        await _log_query(client_id, session_id, message, full_text, [], response_time, llm.get_model_name(), {}, channel=channel)

        matched_menu, matched_images = await _get_media_triggers(message, "", profile, history, llm)
        yield {
            "type": "done",
            "session_id": session_id,
            "sources": [],
            "interactive_menu": matched_menu,
            "context_images": matched_images,
        }
        return

    # Enhancement 1: clarification check
    clarification = await _check_clarification(search_query, top_candidates, llm, history=history)
    if clarification:
        await add_message(session_id, "assistant", clarification)
        response_time = int((time.time() - start) * 1000)
        await _log_query(client_id, session_id, message, clarification, [], response_time, llm.get_model_name(), {}, channel=channel)
        matched_menu, matched_images = await _get_media_triggers(message, "", profile, history, llm)
        yield {"type": "token", "text": clarification}
        yield {
            "type": "done",
            "session_id": session_id,
            "sources": [],
            "interactive_menu": matched_menu,
            "context_images": matched_images,
        }
        return

    context = "\n\n---\n\n".join(c["text"] for c in top_candidates)
    prompt = _build_rag_prompt(context, history_text, message, context_variables=context_variables)

    can_proceed = await _rate_limiter.acquire()
    if not can_proceed:
        llm = _get_fallback_llm(llm)

    full_text = ""
    raw_gen = llm.generate_stream(prompt, system_prompt=system_prompt, temperature=0.2, max_tokens=1024)
    async for chunk in _filter_thinking_stream(raw_gen):
        full_text += chunk
        yield {"type": "token", "text": chunk}

    full_text = _clean_markdown(full_text)
    if not full_text or len(full_text) < 10:
        full_text = FALLBACK_MESSAGE
        yield {"type": "token", "text": FALLBACK_MESSAGE}

    await add_message(session_id, "assistant", full_text, all_sources)
    response_time = int((time.time() - start) * 1000)
    await _log_query(client_id, session_id, message, full_text, all_sources, response_time, llm.get_model_name(), {}, channel=channel)

    if settings.CACHE_ENABLED and query_embedding_for_cache is not None and full_text != FALLBACK_MESSAGE and len(full_text) >= 20:
        await store_cache(client_id, search_query, query_embedding_for_cache, full_text, all_sources)

    matched_menu, matched_images = await _get_media_triggers(message, context, profile, history, llm)

    yield {
        "type": "done",
        "session_id": session_id,
        "sources": all_sources,
        "interactive_menu": matched_menu,
        "context_images": matched_images,
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _build_history_text(history: list) -> str:
    if len(history) <= 1:
        return ""
    lines = ["\nRecent conversation:"]
    for msg in history[:-1]:
        role = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


def _get_fallback_llm(current_llm: LLMProvider) -> LLMProvider:
    # Try Groq if not current, then Gemini, then Ollama
    from app.config import settings
    model_name = current_llm.get_model_name().lower()
    # If current is Gemini and Groq is available, fallback to Groq
    if ("gemini" in model_name or model_name.startswith("models/")) and settings.GROQ_API_KEY:
        from app.providers.llm.groq import GroqProvider
        return GroqProvider(api_key=settings.GROQ_API_KEY, model=settings.GROQ_MODEL)
    # If current is Groq and Gemini is available, fallback to Gemini
    if model_name.startswith("llama") and settings.GEMINI_API_KEY:
        from app.providers.llm.gemini import GeminiProvider
        return GeminiProvider(api_key=settings.GEMINI_API_KEY, model=settings.GEMINI_MODEL)
    # Otherwise, fallback to Ollama if available
    if settings.OLLAMA_URL:
        from app.providers.llm.ollama import OllamaProvider
        return OllamaProvider(base_url=settings.OLLAMA_URL)
    return current_llm


async def _log_query(
    client_id: str, session_id: str, query_text: str, response: str,
    sources: list, response_time_ms: int, model: str, usage: dict,
    channel: str = "widget",
) -> None:
    db = get_db()
    await db[QUERY_LOGS].insert_one({
        "client_id": client_id,
        "session_id": session_id,
        "query": query_text,
        "response": response,
        "sources": sources,
        "response_time_ms": response_time_ms,
        "llm_provider": model,
        "tokens_used": usage,
        "channel": channel,
        "created_at": datetime.now(timezone.utc),
    })


def get_remaining_quota() -> int:
    return _rate_limiter.remaining_daily
