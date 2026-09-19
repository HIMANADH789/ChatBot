"""
Hybrid State-Machine & RAG Core Engine

The central orchestrator connecting:
- Layer 1: Gateway & UserEvent Normalization
- Layer 2: Deterministic State Engine (StateStore + StateMachineRouter)
- Layer 3: Context & Cache Management (Tenant Profile Registry + Short-term Memory)
- Layer 4: Hybrid RAG & Grounded Generation Engine
- Channel Renderer: Transforms engine output into channel-specific BotActions
"""
from __future__ import annotations

import logging
import time
from typing import Any, AsyncGenerator, Dict, Optional

from app.core.user_event import (
    UserEvent,
    EventType,
    EngineResponse,
    BotAction,
    ActionType,
)
from app.services.state_store import UserSessionState, state_store
from app.services.state_machine import state_machine
from app.services.profile_compiler import get_compiled_profile
from app.adapters.channel_renderer import get_channel_renderer
from app.providers.base import LLMProvider, EmbeddingProvider, VectorStoreProvider

logger = logging.getLogger(__name__)


async def _get_default_providers() -> tuple[LLMProvider, EmbeddingProvider, VectorStoreProvider]:
    from app.providers.registry import (
        get_llm_provider,
        get_embedding_provider,
        get_vectordb_provider,
    )
    llm = get_llm_provider()
    embeddings = get_embedding_provider()
    vectordb = get_vectordb_provider()
    return llm, embeddings, vectordb


class HybridEngine:
    """
    Decoupled Orchestrator for Hybrid State-Machine & RAG execution.
    After the state machine or RAG produces a response, the channel renderer
    transforms it into channel-specific BotAction payloads.
    """

    async def process_event(
        self,
        event: UserEvent,
        llm: Optional[LLMProvider] = None,
        embeddings: Optional[EmbeddingProvider] = None,
        vectordb: Optional[VectorStoreProvider] = None,
    ) -> EngineResponse:
        start_time = time.time()

        # ── Step 1: Retrieve & Refresh Dynamic Session State (Layer 2 - Dim 1) ───────
        state = await state_store.get_state(
            tenant_id=event.tenant_id,
            channel=event.channel,
            user_id=event.user_id,
        )

        from app.services.state_machine import refresh_dynamic_context
        state = await refresh_dynamic_context(event=event, state=state, history=[])

        # ── Step 2: Load Tenant Runtime Profile (Layer 3) ─────────────────────
        profile = await get_compiled_profile(event.tenant_id, event.channel)

        # ── Step 3: Evaluate Deterministic State Machine (Layer 2) ───────────
        det_response, requires_rag, query_override = await state_machine.evaluate_event(
            event=event,
            state=state,
            tenant_profile=profile,
        )

        # If deterministic match was found, apply channel renderer and return
        if det_response is not None:
            det_response.response_time_ms = int((time.time() - start_time) * 1000)

            # Apply channel-specific rendering
            renderer = get_channel_renderer(event.channel)
            det_response = renderer.render(det_response, state)

            logger.info(
                "Deterministic route matched for %s/%s [node=%s] in %dms (renderer=%s)",
                event.tenant_id,
                event.channel,
                det_response.active_node_id,
                det_response.response_time_ms,
                renderer.channel_name,
            )
            return det_response

        # ── Step 4: Hybrid RAG & Grounded Generation Pipeline (Layer 4) ───────
        if llm is None or embeddings is None or vectordb is None:
            _llm, _emb, _vdb = await _get_default_providers()
            llm = llm or _llm
            embeddings = embeddings or _emb
            vectordb = vectordb or _vdb

        actual_query = query_override or event.payload

        from app.services import rag_service
        rag_result = await rag_service.query(
            client_id=event.tenant_id,
            message=actual_query,
            session_id=state.session_id,
            llm=llm,
            embeddings=embeddings,
            vectordb=vectordb,
            channel=event.channel,
            context_variables=state.context_variables,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)
        actions = [BotAction(action_type=ActionType.TEXT, payload={"text": rag_result.get("response", "")})]

        matched_menu = rag_result.get("interactive_menu")
        if matched_menu:
            actions.append(BotAction(action_type=ActionType.INTERACTIVE_MENU, payload=matched_menu))

        matched_images = rag_result.get("context_images", [])
        for img in matched_images:
            actions.append(BotAction(action_type=ActionType.IMAGE_MEDIA, payload=img))

        response = EngineResponse(
            session_id=state.session_id,
            text=rag_result.get("response", ""),
            is_deterministic=False,
            active_node_id=state.current_node_id,
            actions=actions,
            sources=rag_result.get("sources", []),
            interactive_menu=matched_menu,
            context_images=matched_images,
            metadata=event.metadata,
            response_time_ms=elapsed_ms,
        )

        # Apply channel-specific rendering to RAG responses that include menus or media artifacts
        if matched_menu or matched_images:
            renderer = get_channel_renderer(event.channel)
            response = renderer.render(response, state)

        return response

    async def process_event_stream(
        self,
        event: UserEvent,
        llm: Optional[LLMProvider] = None,
        embeddings: Optional[EmbeddingProvider] = None,
        vectordb: Optional[VectorStoreProvider] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        start_time = time.time()

        # Step 1 & 2: Session state and tenant profile
        state = await state_store.get_state(
            tenant_id=event.tenant_id,
            channel=event.channel,
            user_id=event.user_id,
        )
        profile = await get_compiled_profile(event.tenant_id, event.channel)

        # Step 3: Evaluate State Machine
        det_response, requires_rag, query_override = await state_machine.evaluate_event(
            event=event,
            state=state,
            tenant_profile=profile,
        )

        if det_response is not None:
            # Apply channel-specific rendering
            renderer = get_channel_renderer(event.channel)
            det_response = renderer.render(det_response, state)

            yield {"type": "token", "text": det_response.text}
            yield {
                "type": "done",
                "session_id": state.session_id,
                "sources": [],
                "interactive_menu": det_response.interactive_menu,
                "context_images": det_response.context_images,
                "is_deterministic": True,
            }
            return

        # Step 4: Stream Generative RAG
        if llm is None or embeddings is None or vectordb is None:
            _llm, _emb, _vdb = await _get_default_providers()
            llm = llm or _llm
            embeddings = embeddings or _emb
            vectordb = vectordb or _vdb

        actual_query = query_override or event.payload

        from app.services import rag_service
        async for chunk in rag_service.query_stream(
            client_id=event.tenant_id,
            message=actual_query,
            session_id=state.session_id,
            llm=llm,
            embeddings=embeddings,
            vectordb=vectordb,
            channel=event.channel,
            context_variables=state.context_variables,
        ):
            yield chunk


hybrid_engine = HybridEngine()
