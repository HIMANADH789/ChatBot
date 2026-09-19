"""
Layer 2: Session State Memory Store

High-speed in-memory datastore for tracking exact user progression per session
using the composite key: tenant_id:channel:user_id.

Maintains:
- current_node_id: Currently active workflow or menu node
- active_menu_id: Last active interactive menu shown to the user
- navigation_stack: Stack of visited node IDs for backward/forward navigation
- node_execution_counts: Per-node render count for frequency control ("only_once")
- context_variables: Key-value attributes extracted during the conversation (e.g. course, qualification, city)
- state_flags: Generic state markers
- last_interaction_at: Timestamp for inactivity/TTL tracking
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.mongodb import get_db

logger = logging.getLogger(__name__)

SESSION_STATES_COLLECTION = "session_states"
DEFAULT_SESSION_TTL_SECONDS = 5400  # 1.5 hours (90 minutes)


@dataclass
class UserSessionState:
    session_id: str
    tenant_id: str
    channel: str
    user_id: str
    current_node_id: Optional[str] = None
    active_menu_id: Optional[str] = None
    navigation_stack: List[str] = field(default_factory=list)
    node_execution_counts: Dict[str, int] = field(default_factory=dict)
    context_variables: Dict[str, Any] = field(default_factory=dict)
    state_flags: Dict[str, Any] = field(default_factory=dict)
    last_interaction_at: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UserSessionState:
        # Backward compat: read legacy 'history_trail' if 'navigation_stack' is absent
        nav_stack = data.get("navigation_stack") or data.get("history_trail") or []
        return cls(
            session_id=data.get("session_id", ""),
            tenant_id=data.get("tenant_id", ""),
            channel=data.get("channel", "widget"),
            user_id=data.get("user_id", ""),
            current_node_id=data.get("current_node_id"),
            active_menu_id=data.get("active_menu_id"),
            navigation_stack=list(nav_stack),
            node_execution_counts=data.get("node_execution_counts") or {},
            context_variables=data.get("context_variables") or {},
            state_flags=data.get("state_flags") or {},
            last_interaction_at=data.get("last_interaction_at", time.time()),
            created_at=data.get("created_at", time.time()),
        )

    def was_node_shown(self, node_id: str) -> bool:
        """Check if a node has been rendered at least once in this session."""
        return self.node_execution_counts.get(node_id, 0) > 0

    def get_node_show_count(self, node_id: str) -> int:
        """Return how many times a node has been rendered."""
        return self.node_execution_counts.get(node_id, 0)

    def increment_node_count(self, node_id: str) -> int:
        """Increment and return the execution count for a node."""
        current = self.node_execution_counts.get(node_id, 0) + 1
        self.node_execution_counts[node_id] = current
        return current


def _safe_get_db():
    try:
        return get_db()
    except Exception:
        return None


class StateStore:
    """
    Sub-millisecond in-memory session state repository with asynchronous
    persistence backing.
    """
    def __init__(self, ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS):
        self._memory_store: Dict[str, UserSessionState] = {}
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def build_session_key(tenant_id: str, channel: str, user_id: str) -> str:
        safe_uid = str(user_id).replace("+", "").replace(":", "_").replace("@", "_")
        return f"{tenant_id}:{channel}:{safe_uid}"

    async def get_state(
        self,
        tenant_id: str,
        channel: str,
        user_id: str,
        auto_create: bool = True,
    ) -> UserSessionState:
        session_key = self.build_session_key(tenant_id, channel, user_id)
        now = time.time()

        # 1. Check in-memory store
        if session_key in self._memory_store:
            state = self._memory_store[session_key]
            # Check TTL
            if now - state.last_interaction_at <= self._ttl_seconds:
                state.last_interaction_at = now
                return state
            else:
                # Expired in memory -> purge chat history from MongoDB too
                del self._memory_store[session_key]
                try:
                    from app.services.chat_service import clear_session_history
                    await clear_session_history(session_key)
                except Exception as exc:
                    logger.debug("Failed to purge chat history on TTL expiration: %s", exc)

        # 2. Check persistence layer (MongoDB)
        db = _safe_get_db()
        doc = None
        if db is not None:
            try:
                doc = await db[SESSION_STATES_COLLECTION].find_one({"session_id": session_key})
            except Exception as exc:
                logger.warning("Failed to fetch session state from MongoDB for %s: %s", session_key, exc)

        if doc:
            state = UserSessionState.from_dict(doc)
            if now - state.last_interaction_at <= self._ttl_seconds:
                state.last_interaction_at = now
                self._memory_store[session_key] = state
                return state
            else:
                # Expired in DB
                try:
                    from app.services.chat_service import clear_session_history
                    await clear_session_history(session_key)
                except Exception as exc:
                    logger.debug("Failed to purge chat history on DB TTL expiration: %s", exc)

        # 3. Create fresh state if needed
        if auto_create:
            new_state = UserSessionState(
                session_id=session_key,
                tenant_id=tenant_id,
                channel=channel,
                user_id=user_id,
                last_interaction_at=now,
                created_at=now,
            )
            self._memory_store[session_key] = new_state
            await self.save_state(new_state)
            return new_state

        return None  # type: ignore

    async def save_state(self, state: UserSessionState) -> None:
        state.last_interaction_at = time.time()
        self._memory_store[state.session_id] = state

        # Persist to database asynchronously
        db = _safe_get_db()
        if db is not None:
            try:
                await db[SESSION_STATES_COLLECTION].update_one(
                    {"session_id": state.session_id},
                    {"$set": state.to_dict()},
                    upsert=True,
                )
            except Exception as exc:
                logger.warning("Async state persistence failed for %s: %s", state.session_id, exc)

    async def transition_node(
        self,
        state: UserSessionState,
        next_node_id: Optional[str],
        active_menu_id: Optional[str] = None,
        context_updates: Optional[Dict[str, Any]] = None,
    ) -> UserSessionState:
        """
        Record a state transition: push current node onto the navigation stack,
        set new current node, and increment execution count.
        """
        if state.current_node_id and (
            not state.navigation_stack
            or state.navigation_stack[-1] != state.current_node_id
        ):
            state.navigation_stack.append(state.current_node_id)

        state.current_node_id = next_node_id
        if active_menu_id is not None:
            state.active_menu_id = active_menu_id

        # Increment execution count for frequency control
        if next_node_id:
            state.increment_node_count(next_node_id)

        if context_updates:
            state.context_variables.update(context_updates)

        await self.save_state(state)
        return state

    async def go_back(self, state: UserSessionState) -> Optional[str]:
        """
        Pop the navigation stack and return the previous node_id.
        Updates current_node_id and active_menu_id to the popped value.
        Returns None if the stack is empty (caller should render root menu).
        """
        if not state.navigation_stack:
            return None

        prev_node_id = state.navigation_stack.pop()
        state.current_node_id = prev_node_id
        state.active_menu_id = prev_node_id
        await self.save_state(state)
        return prev_node_id

    async def reset_state(self, state: UserSessionState, clear_context: bool = False) -> UserSessionState:
        """Reset state breadcrumbs back to root/initial state."""
        state.current_node_id = None
        state.active_menu_id = None
        state.navigation_stack = []
        if clear_context:
            state.context_variables = {}
            state.node_execution_counts = {}
            state.state_flags = {}
        await self.save_state(state)
        return state


# Global singleton instance
state_store = StateStore()
