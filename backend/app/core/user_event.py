"""
Layer 1: Multi-Channel & Tenant Gateway Data Contracts

Defines normalized UserEvent, BotAction, and EngineResponse objects.
Every platform's incoming payload is converted to UserEvent before entering
the Hybrid State-Machine & RAG pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(str, Enum):
    TEXT = "text"
    BUTTON_CLICK = "button_click"
    MENU_SELECTION = "menu_selection"
    MEDIA = "media"
    SYSTEM_EVENT = "system_event"


class ActionType(str, Enum):
    TEXT = "text"
    INTERACTIVE_MENU = "interactive_menu"
    IMAGE_MEDIA = "image_media"
    STATE_TRANSITION = "state_transition"
    FORM_PROMPT = "form_prompt"
    ERROR = "error"


@dataclass
class UserEvent:
    """
    Platform-agnostic representation of an incoming user interaction.

    - tenant_id: Unique client/tenant identifier (e.g., 'sv_institute')
    - channel: Channel name (e.g., 'whatsapp', 'widget', 'telegram', 'slack')
    - user_id: Unique sender identifier on the channel (e.g., phone number, chat_id)
    - session_id: Composite session key: {tenant_id}:{channel}:{user_id}
    - event_type: EventType (TEXT, BUTTON_CLICK, MENU_SELECTION, MEDIA)
    - payload: Text content, selected button ID/label, or media payload
    - metadata: Channel-specific attributes (e.g., contact_name, interactive_id, media_url)
    - timestamp: UTC timestamp of the event
    """
    tenant_id: str
    channel: str
    user_id: str
    payload: str
    event_type: EventType = EventType.TEXT
    metadata: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.session_id:
            safe_uid = str(self.user_id).replace("+", "").replace(":", "_").replace("@", "_")
            self.session_id = f"{self.tenant_id}:{self.channel}:{safe_uid}"


@dataclass
class BotAction:
    """
    An individual atomic action emitted by the backend.
    """
    action_type: ActionType
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineResponse:
    """
    Unified response envelope produced by the Hybrid State-Machine & RAG core.
    """
    session_id: str
    text: str
    is_deterministic: bool = False
    active_node_id: Optional[str] = None
    actions: List[BotAction] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    interactive_menu: Optional[Dict[str, Any]] = None
    context_images: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    response_time_ms: int = 0
