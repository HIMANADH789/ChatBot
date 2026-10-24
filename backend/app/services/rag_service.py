"""
RAG Orchestrator Service:
Coordinates context management, conversational flow, hybrid retrieval,
LLM generation, and UI artifact resolution across channels.

Modular architecture:
  - app.services.retrieval: Pure hybrid retrieval (vector, BM25, HyDE, reranker)
  - app.services.artifacts: WhatsApp and channel artifact components (menus, images, maps, inclusion texts)
  - app.services.llm_response: Structured JSON parsing, think-tag cleanup, stream filtering
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional, Any

from app.config import settings
from app.db.collections import QUERY_LOGS, CLIENTS
from app.db.mongodb import get_db
from app.models.client import get_setup
from app.providers.base import EmbeddingProvider, LLMProvider, VectorStoreProvider
from app.services.chat_service import add_message, get_history, get_or_create_session, count_session_queries
from app.services.profile_compiler import get_compiled_profile
from app.utils.rate_limiter import RateLimiter

# Modular sub-services
from app.services.retrieval import (
    retrieve_context,
    retrieve_and_rerank,
    resolve_contextual_query,
    extract_query_metadata,
    build_where_filter,
    hypothetical_embedding,
    decompose_question,
    check_clarification,
    _retrieve_and_rerank,
    _resolve_contextual_query,
    _extract_query_metadata,
    _build_where_filter,
    _hypothetical_embedding,
    _decompose_question,
    _check_clarification,
)
from app.services.artifacts import (
    resolve_artifacts,
    apply_artifact_safety_nets,
    build_artifact_delivery_history,
    append_inclusion_content,
    _resolve_artifacts,
    _apply_artifact_safety_nets,
    _build_artifact_delivery_history,
)
from app.services.llm_response import (
    parse_llm_json_response,
    parse_json_response,
    clean_markdown,
    filter_thinking_stream,
    _parse_llm_json_response,
    _parse_json_response,
    _clean_markdown,
    _filter_thinking_stream,
)

logger = logging.getLogger(__name__)

_rate_limiter = RateLimiter(
    rpm_limit=settings.GEMINI_RPM_LIMIT,
    daily_limit=settings.GEMINI_DAILY_LIMIT,
)

FALLBACK_MESSAGE = (
    "I don't have specific information about that in our knowledge base. "
    "Please contact the administration directly for further assistance."
)

DEFAULT_SYSTEM_PROMPT = """You are a helpful, knowledgeable, and polite AI assistant. You assist visitors, clients, and prospective candidates with clear, accurate, and engaging guidance.

Key Guidelines:
- Style & Tone: Warm, engaging, professional, and conversational (like an expert front desk counselor on WhatsApp).
- Length: Keep responses small-medium (around 80-130 words). Provide direct, relevant information without clumsy or overwhelming walls of text.
- Formatting & Readability:
  - Use clear section headings with markdown (e.g., *Highlights*, *Eligibility*, *Next Steps*).
  - Use **bold** for key names, prerequisites, numbers, and important takeaways.
  - Use clean bullet points (- item) for easy scanning on mobile.
  - Incorporate moderate, tasteful emojis (🎓, 💼, 📌, 📚) to keep the text visually appealing and structured.
- Dynamically adapt to the visitor's stated background, interests, and preferences throughout the conversation.
- For greetings or pleasantries, reply warmly and concisely in 1-2 friendly sentences.
- End informational answers with a warm, interactive follow-up question offering specific next steps.
- Never output internal thought processes, reasoning steps, conflict resolutions, scratchpads, or <think> tags. Output ONLY the direct response."""

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
    "i", "did", "have", "had", "worked", "working", "completed", "pursuing", "doing",
    "got", "done", "passed", "graduated", "studied", "studying", "joined", "joining",
}

STOP_AFTER_WORDS = {
    "from", "in", "at", "and", "with", "for", "here", "to", "who", "seeking", "wanting",
    "can", "could", "would", "please", "want", "need", "will", "should", "may",
    "how", "what", "where", "which", "why", "when", "is", "are", "am", "give", "show", "tell",
    "i", "did", "have", "had", "worked", "working", "completed", "pursuing", "doing",
    "got", "done", "passed", "graduated", "studied", "studying", "joined", "joining",
}


def extract_user_name(text: str) -> Optional[str]:
    """Extract candidate user name from conversational intro patterns."""
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


def _is_lightweight_query(message: str) -> bool:
    """Check if a message is short/conversational enough to skip RAG retrieval."""
    lower = message.lower().strip().rstrip("?!.")
    if lower in CONVERSATIONAL_TRIGGERS:
        return True
    if len(lower.split()) <= 3 and any(t in lower for t in CONVERSATIONAL_TRIGGERS):
        return True
    return False


_is_conversational = _is_lightweight_query


def _build_history_text(history: list) -> str:
    """Format past turns into a readable conversation snippet for the LLM."""
    if len(history) <= 1:
        return ""
    lines = ["\nRecent conversation:"]
    for msg in history[:-1]:
        role = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


def _build_rag_prompt(
    context: str,
    history_text: str,
    message: str,
    context_variables: Optional[dict] = None,
    artifact_delivery_history: str = "",
) -> str:
    """Build the user-turn prompt for the unified LLM call."""
    user_context_block = ""
    if context_variables:
        active_vars = [f"• {k.replace('_', ' ').title()}: {v}" for k, v in context_variables.items() if v]
        if active_vars:
            user_context_block = "Active User Session Context:\n" + "\n".join(active_vars) + "\n\n"

    rag_block = ""
    if context and context.strip():
        rag_block = f"Retrieved knowledge base context:\n{context}\n\n"

    delivery_block = ""
    if artifact_delivery_history and artifact_delivery_history != "None sent yet.":
        delivery_block = f"Artifacts already sent this session (do NOT re-send unless user explicitly asks):\n{artifact_delivery_history}\n\n"

    turn_hint = ""
    if not history_text or not history_text.strip():
        turn_hint = "Turn Context: This is the FIRST message/interaction of this session with the student. Note: If any artifact (e.g. MENU_ROOT) specifies in its 'When' description to display at the start of conversation or initial greeting, you MUST include its ID in 'send_artifacts' so the student can immediately explore options.\n\n"

    return f"""{rag_block}{user_context_block}{delivery_block}{turn_hint}{history_text}
User message: {message}

Remember: respond with the JSON format specified in your instructions. Include your conversational response in "message", any artifact IDs to attach in "send_artifacts", and any new user context you extracted in "context_updates"."""


def _get_fallback_llm(current_llm: LLMProvider) -> LLMProvider:
    """Select fallback LLM when primary provider is rate-limited."""
    model_name = current_llm.get_model_name().lower()
    if ("gemini" in model_name or model_name.startswith("models/")) and settings.GROQ_API_KEY:
        from app.providers.llm.groq import GroqProvider
        return GroqProvider(api_key=settings.GROQ_API_KEY, model=settings.GROQ_MODEL)
    if model_name.startswith("llama") and settings.GEMINI_API_KEY:
        from app.providers.llm.gemini import GeminiProvider
        return GeminiProvider(api_key=settings.GEMINI_API_KEY, model=settings.GEMINI_MODEL)
    if settings.OLLAMA_URL:
        from app.providers.llm.ollama import OllamaProvider
        return OllamaProvider(base_url=settings.OLLAMA_URL)
    return current_llm


async def _log_query(
    client_id: str,
    session_id: str,
    query_text: str,
    response: str,
    sources: list,
    response_time_ms: int,
    model: str,
    usage: dict,
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
    session_state: Optional[Any] = None,
) -> dict:
    """
    Main non-streaming RAG entrypoint:
    Orchestrates session, context retrieval, LLM generation, and artifact resolution.
    """
    start = time.time()
    db = get_db()

    session_id = await get_or_create_session(client_id, session_id)
    await add_message(session_id, "user", message)

    client = await db[CLIENTS].find_one({"client_id": client_id})
    cs = (client or {}).get("settings", {})

    # Load pre-compiled client runtime profile snapshot
    profile = await get_compiled_profile(client_id, channel)
    system_prompt = profile.get("compiled_system_prompt") or DEFAULT_SYSTEM_PROMPT
    ctx_cfg = profile.get("context_config", {})
    context_mode = ctx_cfg.get("mode") or cs.get("context_mode", "none")
    raw_cap = ctx_cfg.get("capacity") if ctx_cfg.get("capacity") is not None else cs.get("context_capacity")
    context_capacity = int(raw_cap) if raw_cap is not None else 4

    # Extract dynamic visitor name
    extracted_name = extract_user_name(message)
    if context_variables is None:
        context_variables = {}
    if extracted_name:
        context_variables["user_name"] = extracted_name

    active_name = context_variables.get("user_name") or extracted_name
    if active_name:
        system_prompt += f"\n\nMANDATORY VISITOR IDENTITY INSTRUCTION:\n- Visitor's active name is '{active_name}'. Always address them warmly as '{active_name}' in your response."

    # Context history loading
    if context_mode == "none" or context_capacity <= 0:
        history = []
    else:
        configured_history = int(cs.get("max_history_turns", 3) or 3)
        max_history = min(configured_history, context_capacity) if context_capacity > 0 else configured_history
        history = await get_history(session_id, max_turns=max_history)

    # Session query limit check
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
    artifact_delivery_history = build_artifact_delivery_history(session_state)

    # Context retrieval via modular retrieval service
    is_light = _is_lightweight_query(message)
    all_sources = []
    context = ""

    if not is_light:
        context, all_sources, _ = await retrieve_context(
            client_id=client_id,
            message=message,
            history=history,
            llm=llm,
            embeddings=embeddings,
            vectordb=vectordb,
            context_mode=context_mode,
            context_instructions=ctx_cfg.get("instructions", ""),
            context_capacity=context_capacity,
            context_variables=context_variables,
            rate_limiter=_rate_limiter,
        )

    prompt = _build_rag_prompt(
        context=context,
        history_text=history_text,
        message=message,
        context_variables=context_variables,
        artifact_delivery_history=artifact_delivery_history,
    )

    can_proceed = await _rate_limiter.acquire()
    if not can_proceed:
        llm = _get_fallback_llm(llm)

    llm_response_obj = await llm.generate(
        prompt,
        system_prompt=system_prompt,
        temperature=0.3,
        max_tokens=1024,
    )

    # Parse structured JSON response
    parsed = parse_llm_json_response(llm_response_obj.text)
    text = parsed.get("message", "").strip()
    if not text:
        text = clean_markdown(llm_response_obj.text)
    if not text or len(text.strip()) == 0:
        text = FALLBACK_MESSAGE

    artifact_ids = parsed.get("send_artifacts", []) or []
    context_updates = parsed.get("context_updates", {}) or {}
    if isinstance(context_updates, dict) and context_variables is not None:
        for k, v in context_updates.items():
            if isinstance(v, str) and v.strip() and v.lower() != "null":
                context_variables[k] = v.strip()

    # Resolve UI artifact components via modular artifacts service
    matched_menu, matched_images, matched_maps, matched_inclusions = resolve_artifacts(artifact_ids, profile)
    matched_menu = apply_artifact_safety_nets(matched_menu, profile, session_state=session_state, is_light=is_light, history=history)
    text = append_inclusion_content(text, matched_inclusions)

    await add_message(session_id, "assistant", text, all_sources)
    response_time = int((time.time() - start) * 1000)
    await _log_query(
        client_id,
        session_id,
        message,
        text,
        all_sources,
        response_time,
        llm_response_obj.model,
        llm_response_obj.usage,
        channel=channel,
    )

    return {
        "response": text,
        "sources": all_sources,
        "session_id": session_id,
        "interactive_menu": matched_menu,
        "context_images": matched_images,
        "context_maps": matched_maps,
        "inclusion_texts": matched_inclusions,
        "context_variables": context_variables,
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
    session_state: Optional[Any] = None,
):
    """
    Main streaming RAG entrypoint:
    Orchestrates session, context retrieval, LLM streaming generation, and artifact resolution.
    """
    start = time.time()
    db = get_db()

    session_id = await get_or_create_session(client_id, session_id)
    await add_message(session_id, "user", message)

    client = await db[CLIENTS].find_one({"client_id": client_id})
    cs = (client or {}).get("settings", {})

    profile = await get_compiled_profile(client_id, channel)
    system_prompt = profile.get("compiled_system_prompt") or DEFAULT_SYSTEM_PROMPT
    ctx_cfg = profile.get("context_config", {})
    context_mode = ctx_cfg.get("mode") or cs.get("context_mode", "none")
    raw_cap = ctx_cfg.get("capacity") if ctx_cfg.get("capacity") is not None else cs.get("context_capacity")
    context_capacity = int(raw_cap) if raw_cap is not None else 4

    extracted_name = extract_user_name(message)
    if context_variables is None:
        context_variables = {}
    if extracted_name:
        context_variables["user_name"] = extracted_name

    active_name = context_variables.get("user_name") or extracted_name
    if active_name:
        system_prompt += f"\n\nMANDATORY VISITOR IDENTITY INSTRUCTION:\n- Visitor's active name is '{active_name}'. Always address them warmly as '{active_name}' in your response."

    if context_mode == "none" or context_capacity <= 0:
        history = []
    else:
        configured_history = int(cs.get("max_history_turns", 3) or 3)
        max_history = min(configured_history, context_capacity) if context_capacity > 0 else configured_history
        history = await get_history(session_id, max_turns=max_history)

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
    artifact_delivery_history = build_artifact_delivery_history(session_state)

    is_light = _is_lightweight_query(message)
    all_sources = []
    context = ""

    if not is_light:
        context, all_sources, _ = await retrieve_context(
            client_id=client_id,
            message=message,
            history=history,
            llm=llm,
            embeddings=embeddings,
            vectordb=vectordb,
            context_mode=context_mode,
            context_instructions=ctx_cfg.get("instructions", ""),
            context_capacity=context_capacity,
            context_variables=context_variables,
            rate_limiter=_rate_limiter,
        )

    prompt = _build_rag_prompt(
        context=context,
        history_text=history_text,
        message=message,
        context_variables=context_variables,
        artifact_delivery_history=artifact_delivery_history,
    )

    can_proceed = await _rate_limiter.acquire()
    if not can_proceed:
        llm = _get_fallback_llm(llm)

    llm_response_obj = await llm.generate(
        prompt,
        system_prompt=system_prompt,
        temperature=0.3,
        max_tokens=1024,
    )

    parsed = parse_llm_json_response(llm_response_obj.text)
    text = parsed.get("message", "").strip()
    if not text:
        text = clean_markdown(llm_response_obj.text)
    if not text or len(text.strip()) == 0:
        text = FALLBACK_MESSAGE

    artifact_ids = parsed.get("send_artifacts", []) or []
    context_updates = parsed.get("context_updates", {}) or {}
    if isinstance(context_updates, dict) and context_variables is not None:
        for k, v in context_updates.items():
            if isinstance(v, str) and v.strip() and v.lower() != "null":
                context_variables[k] = v.strip()

    matched_menu, matched_images, matched_maps, matched_inclusions = resolve_artifacts(artifact_ids, profile)
    matched_menu = apply_artifact_safety_nets(matched_menu, profile, session_state=session_state, is_light=is_light, history=history)
    text = append_inclusion_content(text, matched_inclusions)

    await add_message(session_id, "assistant", text, all_sources)
    response_time = int((time.time() - start) * 1000)
    await _log_query(
        client_id,
        session_id,
        message,
        text,
        all_sources,
        response_time,
        llm_response_obj.model,
        llm_response_obj.usage,
        channel=channel,
    )

    yield {"type": "token", "text": text}
    yield {
        "type": "done",
        "session_id": session_id,
        "sources": all_sources,
        "interactive_menu": matched_menu,
        "context_images": matched_images,
        "context_maps": matched_maps,
        "inclusion_texts": matched_inclusions,
    }
