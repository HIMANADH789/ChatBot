"""
Layer 2: Deterministic State Machine & Workflow Router

Evaluates normalized UserEvents against the tenant's MenuGraph and active session state.
If an event triggers a deterministic path (serial number input, button click, navigation
command), the State Machine transitions state and produces an EngineResponse immediately
with ZERO LLM latency.

Input Evaluation Pipeline:
  1. "0" / "back" / "go back"   → Pop navigation_stack, render previous node
  2. "menu" / "start" / "home"  → Reset to root node
  3. Serial number match ("1", "2", "3") → Match against active node's options
  4. Interactive ID match (WhatsApp callback) → Match option_number or button_text
  5. Text match → Exact match against button_text of current node's options
  6. No match → Fallthrough to RAG
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.core.user_event import UserEvent, EventType, EngineResponse, BotAction, ActionType
from app.core.menu_graph import (
    MenuGraph,
    MenuGraphNode,
    NodeOption,
    TARGET_NAVIGATE_MENU,
    TARGET_TRIGGER_RAG,
    TARGET_DIRECT_ANSWER,
    FREQ_ONLY_ONCE,
)
from app.services.state_store import UserSessionState, state_store
from app.services.context_media_service import is_leaf_node

logger = logging.getLogger(__name__)

NAVIGATION_MAIN_MENU_TRIGGERS = {"main menu", "menu", "start", "restart", "reset", "home"}
NAVIGATION_BACK_TRIGGERS = {"back", "go back", "previous", "0"}


class StateMachineRouter:
    """
    Deterministic workflow evaluator using the MenuGraph node model.
    """

    # ── MenuGraph-Based Evaluation ──────────────────────────────────────────

    def _resolve_option(
        self,
        graph: MenuGraph,
        state: UserSessionState,
        event: UserEvent,
    ) -> Optional[NodeOption]:
        """
        Try to resolve user input to a NodeOption on the active node.
        Priority: serial number → interactive ID → text match.
        """
        active_node_id = state.active_menu_id or state.current_node_id
        if not active_node_id:
            # At root level — try to match against root node's options
            root = graph.get_root_node()
            if root:
                active_node_id = root.node_id
            else:
                return None

        payload = (event.payload or "").strip()
        interactive_id = event.metadata.get("interactive_id", "")

        # Priority 1: Serial number match (e.g., user types "1", "2", "3")
        if payload and payload.isdigit():
            opt = graph.get_option_by_number(active_node_id, payload)
            if opt:
                return opt

        # Priority 2: Interactive ID (WhatsApp button/list callback)
        if interactive_id:
            opt = graph.get_option_by_interactive_id(active_node_id, interactive_id)
            if opt:
                return opt

        # Priority 3: Exact text match
        if payload:
            opt = graph.get_option_by_text(active_node_id, payload)
            if opt:
                return opt

        return None

    def _build_menu_response(
        self,
        node: MenuGraphNode,
        state: UserSessionState,
        body_prefix: str = "",
    ) -> EngineResponse:
        """
        Build a deterministic EngineResponse rendering a menu node's options.
        """
        # Build option data for the response payload
        options_data = []
        for opt in node.options:
            options_data.append({
                "id": opt.option_number,
                "option_number": opt.option_number,
                "label": opt.button_text,
                "button_text": opt.button_text,
                "target_type": opt.target_type,
            })

        # Add "Go Back" option if navigation stack is non-empty
        if state.navigation_stack:
            options_data.append({
                "id": "0",
                "option_number": "0",
                "label": "↩ Go Back",
                "button_text": "↩ Go Back",
                "target_type": "GO_BACK",
            })

        body_text = body_prefix or f"*{node.title}*\nPlease select an option:"
        header_text = node.title

        # Determine if whatsapp_media should be included
        # (frequency control is applied later by the channel renderer)
        whatsapp_media = node.whatsapp_media if node.has_whatsapp_media else {}

        action = BotAction(
            action_type=ActionType.INTERACTIVE_MENU,
            payload={
                "body_text": body_text,
                "options": options_data,
                "header_text": header_text,
                "node_id": node.node_id,
                "menu_number": node.menu_number,
                "whatsapp_media": whatsapp_media,
                "frequency": node.frequency,
            },
        )

        return EngineResponse(
            session_id=state.session_id,
            text=f"[Menu: {node.title}]",
            is_deterministic=True,
            active_node_id=node.node_id,
            actions=[action],
            interactive_menu={
                "body_text": body_text,
                "options": options_data,
                "header_text": header_text,
                "label": node.title,
                "node_id": node.node_id,
                "whatsapp_media": whatsapp_media,
                "frequency": node.frequency,
            },
        )

    async def _evaluate_graph(
        self,
        event: UserEvent,
        state: UserSessionState,
        graph: MenuGraph,
    ) -> Tuple[Optional[EngineResponse], bool, Optional[str]]:
        """
        Evaluate UserEvent against the MenuGraph.

        Returns:
            (deterministic_response, requires_rag, rag_query_override)
        """
        payload = (event.payload or "").strip()
        norm_payload = payload.lower()

        # ── 1. Global Navigation: Main Menu / Restart ───────────────────────
        if norm_payload in NAVIGATION_MAIN_MENU_TRIGGERS:
            await state_store.reset_state(state)
            root = graph.get_root_node()
            if root:
                state.current_node_id = root.node_id
                state.active_menu_id = root.node_id
                state.increment_node_count(root.node_id)
                await state_store.save_state(state)
                resp = self._build_menu_response(root, state, body_prefix="Main Menu — Please select an option:")
                return (resp, False, None)

        # ── 2. Global Navigation: Go Back ───────────────────────────────────
        if norm_payload in NAVIGATION_BACK_TRIGGERS:
            prev_node_id = await state_store.go_back(state)
            if prev_node_id:
                prev_node = graph.get_node(prev_node_id)
                if prev_node and not prev_node.is_leaf:
                    resp = self._build_menu_response(
                        prev_node,
                        state,
                        body_prefix=f"Returning to *{prev_node.title}*:\nPlease select an option:",
                    )
                    return (resp, False, None)
                elif prev_node and prev_node.direct_answer:
                    return (
                        EngineResponse(
                            session_id=state.session_id,
                            text=prev_node.direct_answer,
                            is_deterministic=True,
                            active_node_id=prev_node_id,
                            actions=[BotAction(action_type=ActionType.TEXT, payload={"text": prev_node.direct_answer})],
                        ),
                        False,
                        None,
                    )

            # Fallback: show root menu
            await state_store.reset_state(state)
            root = graph.get_root_node()
            if root:
                state.current_node_id = root.node_id
                state.active_menu_id = root.node_id
                state.increment_node_count(root.node_id)
                await state_store.save_state(state)
                resp = self._build_menu_response(root, state, body_prefix="Main Menu — Please select an option:")
                return (resp, False, None)

        # ── 3. Resolve Option (serial number / interactive ID / text match) ─
        matched_option = self._resolve_option(graph, state, event)

        if matched_option:
            # Case A: NAVIGATE_MENU → Transition to target node, render its menu
            if matched_option.target_type == TARGET_NAVIGATE_MENU:
                target_node = graph.get_node(matched_option.target_id)
                if target_node:
                    context_updates = {"last_selected_option": matched_option.button_text}
                    await state_store.transition_node(
                        state,
                        next_node_id=target_node.node_id,
                        active_menu_id=target_node.node_id,
                        context_updates=context_updates,
                    )

                    # If target is a leaf with direct_answer → zero-LLM response
                    if target_node.is_leaf and target_node.direct_answer:
                        return (
                            EngineResponse(
                                session_id=state.session_id,
                                text=target_node.direct_answer,
                                is_deterministic=True,
                                active_node_id=target_node.node_id,
                                actions=[BotAction(
                                    action_type=ActionType.TEXT,
                                    payload={"text": target_node.direct_answer},
                                )],
                            ),
                            False,
                            None,
                        )

                    # If target has options → render menu
                    if not target_node.is_leaf:
                        resp = self._build_menu_response(
                            target_node,
                            state,
                            body_prefix=f"You selected: *{matched_option.button_text}*\n{target_node.title}\nPlease select an option:",
                        )
                        return (resp, False, None)

                    # Leaf with no direct_answer and no options → RAG with button text as query
                    return (None, True, matched_option.button_text)

            # Case B: DIRECT_ANSWER → Return immediate direct text answer
            elif matched_option.target_type == TARGET_DIRECT_ANSWER or matched_option.direct_answer:
                answer = matched_option.direct_answer or matched_option.button_text
                return (
                    EngineResponse(
                        session_id=state.session_id,
                        text=answer,
                        is_deterministic=True,
                        active_node_id=state.current_node_id,
                        actions=[BotAction(action_type=ActionType.TEXT, payload={"text": answer})],
                    ),
                    False,
                    None,
                )

            # Case C: TRIGGER_RAG → Delegate to RAG pipeline with augmented query
            elif matched_option.target_type == TARGET_TRIGGER_RAG:
                rag_query = matched_option.rag_prompt or matched_option.button_text
                context_updates = {"last_selected_option": matched_option.button_text}
                await state_store.transition_node(
                    state,
                    next_node_id=matched_option.target_id or state.current_node_id,
                    active_menu_id=state.active_menu_id,
                    context_updates=context_updates,
                )
                return (None, True, rag_query)

        # ── 4. No match → Fallthrough to RAG ────────────────────────────────
        return (None, True, payload)



    # ── Public API ──────────────────────────────────────────────────────────

    async def evaluate_event(
        self,
        event: UserEvent,
        state: UserSessionState,
        tenant_profile: Dict[str, Any],
    ) -> Tuple[Optional[EngineResponse], bool, Optional[str]]:
        """
        Evaluates the UserEvent against tenant's workflow/menu state machine.

        Returns:
            (deterministic_response, requires_rag, rag_query_override)

        If deterministic_response is returned, LLM is bypassed.
        If requires_rag is True, execution proceeds to Layer 3 / Layer 4.
        """
        # Evaluate against compiled MenuGraph instance
        menu_graph_data = tenant_profile.get("menu_graph")
        if menu_graph_data and isinstance(menu_graph_data, MenuGraph):
            return await self._evaluate_graph(event, state, menu_graph_data)

        # Check for serialized menu_graph_nodes list in profile
        graph_nodes = tenant_profile.get("menu_graph_nodes", [])
        root_id = tenant_profile.get("menu_graph_root_node_id", "")
        graph = MenuGraph.from_config(graph_nodes, root_node_id=root_id) if graph_nodes else MenuGraph()
        return await self._evaluate_graph(event, state, graph)


# Global singleton instance
state_machine = StateMachineRouter()
