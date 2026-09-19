"""
Channel-Specific State Renderers

Transforms channel-agnostic EngineResponse / BotAction payloads into
channel-specific output. The State Engine decides WHAT to show; these
renderers decide HOW to show it.

WhatsAppChannelRenderer:
  - Sends whatsapp_media image BEFORE the menu (frequency-gated)
  - Renders ≤3 options as Interactive Buttons, >3 as Interactive Lists
  - Appends "↩ Go Back" when navigation_stack is non-empty
  - Truncates button_text to 20 chars (buttons) / 24 chars (list rows)

WebChannelRenderer:
  - No image attachments (web widget handles images via frontend)
  - Returns clean JSON options array for the widget to render as chips/buttons
  - No WhatsApp-style *bold* formatting

DefaultChannelRenderer:
  - Generic text-based numbered list for Telegram, Slack, Facebook, etc.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)
from typing import Any, Dict, List, Optional

from app.core.user_event import EngineResponse, BotAction, ActionType
from app.core.menu_graph import FREQ_ONLY_ONCE
from app.services.state_store import UserSessionState

def _extract_menu_options(menu: dict) -> list[dict]:
    """Unified options extractor bridging MenuGraph options and MenuTree children."""
    if not menu:
        return []
    options = menu.get("options", [])
    if options:
        return options
    children = menu.get("children", [])
    if children:
        return [
            {
                "id": str(c.get("id") or i + 1),
                "option_number": str(i + 1),
                "button_text": c.get("label") or c.get("title") or f"Option {i+1}",
                "label": c.get("label") or c.get("title") or f"Option {i+1}",
                "target_type": "TRIGGER_RAG" if c.get("action_question") else "NAVIGATE_MENU",
            }
            for i, c in enumerate(children)
        ]
    return []


class BaseChannelRenderer(ABC):
    """
    Abstract renderer that transforms an EngineResponse's interactive_menu
    and context_images into channel-specific BotAction payloads.
    """
    channel_name: str = ""

    @abstractmethod
    def render_menu_actions(
        self,
        response: EngineResponse,
        state: UserSessionState,
    ) -> List[BotAction]:
        """
        Transform the interactive_menu data in the EngineResponse into
        channel-specific BotAction list.
        """

    def render(
        self,
        response: EngineResponse,
        state: UserSessionState,
    ) -> EngineResponse:
        """
        Process the EngineResponse through this renderer.
        Replaces the actions list with channel-specific actions.
        """
        if not response.interactive_menu:
            return response

        rendered_actions = self.render_menu_actions(response, state)
        if rendered_actions:
            response.actions = rendered_actions

        return response


class WhatsAppChannelRenderer(BaseChannelRenderer):
    """
    WhatsApp-specific renderer:
    - Image attachments sent before menu (frequency-gated)
    - Interactive Buttons (≤3 options) or Interactive List (>3 options)
    - 20-char button text limit, 24-char list row limit
    """
    channel_name = "whatsapp"

    def render_menu_actions(
        self,
        response: EngineResponse,
        state: UserSessionState,
    ) -> List[BotAction]:
        menu = response.interactive_menu
        if not menu:
            return response.actions

        actions: List[BotAction] = []
        options = _extract_menu_options(menu)
        whatsapp_media = menu.get("whatsapp_media", {})
        node_id = menu.get("node_id", "") or menu.get("id", "")
        frequency = menu.get("frequency", "always")

        # ── 1. Frequency-Gated Image Dispatch ───────────────────────────────
        image_url = whatsapp_media.get("image_url", "")
        if image_url:
            should_send_image = True
            if frequency == FREQ_ONLY_ONCE and node_id and state.was_node_shown(node_id):
                # Node was already shown; skip the image
                should_send_image = False
                logger.debug(
                    "Skipping WhatsApp image for node %s (only_once, count=%d)",
                    node_id,
                    state.get_node_show_count(node_id),
                )

            if should_send_image:
                caption = whatsapp_media.get("caption", "")
                actions.append(BotAction(
                    action_type=ActionType.IMAGE_MEDIA,
                    payload={
                        "image_url": image_url,
                        "image_path": image_url,
                        "caption": caption,
                        "title": caption,
                    },
                ))

        # ── 2. Build Interactive Menu ───────────────────────────────────────
        # Format options for the WhatsApp adapter
        wa_options = []
        for opt in options:
            wa_options.append({
                "id": str(opt.get("option_number") or opt.get("id", "")),
                "label": str(opt.get("button_text") or opt.get("label", "")),
                "title": str(opt.get("button_text") or opt.get("label", "")),
                "description": "",
            })

        body_text = menu.get("body_text") or menu.get("description") or "Please select an option:"
        header_text = menu.get("header_text") or menu.get("title") or menu.get("label") or ""

        # Build the interactive menu action with WhatsApp-specific truncation
        if len(wa_options) <= 3:
            # Button reply — truncate to 20 chars
            for opt in wa_options:
                opt["label"] = opt["label"][:20]
                opt["title"] = opt["title"][:20]
        else:
            # List reply — truncate to 24 chars
            for opt in wa_options:
                opt["label"] = opt["label"][:24]
                opt["title"] = opt["title"][:24]

        actions.append(BotAction(
            action_type=ActionType.INTERACTIVE_MENU,
            payload={
                "body_text": body_text[:1024],
                "options": wa_options,
                "header_text": header_text[:60] if header_text else "",
            },
        ))

        return actions


class WebChannelRenderer(BaseChannelRenderer):
    """
    Web widget renderer:
    - No image attachments (frontend handles visuals)
    - Clean JSON options array for rendering as chips/buttons
    - No WhatsApp-style formatting
    """
    channel_name = "widget"

    def render_menu_actions(
        self,
        response: EngineResponse,
        state: UserSessionState,
    ) -> List[BotAction]:
        menu = response.interactive_menu
        if not menu:
            return response.actions

        actions: List[BotAction] = []
        options = _extract_menu_options(menu)

        # Build clean JSON options for the web widget
        web_options = []
        for opt in options:
            web_options.append({
                "option_number": str(opt.get("option_number") or opt.get("id", "")),
                "button_text": str(opt.get("button_text") or opt.get("label", "")),
                "target_type": opt.get("target_type", ""),
            })

        # Clean body text (strip WhatsApp-style markdown)
        body_text = menu.get("body_text") or menu.get("description") or "Please select an option:"
        clean_body = body_text.replace("*", "")

        actions.append(BotAction(
            action_type=ActionType.INTERACTIVE_MENU,
            payload={
                "body_text": clean_body,
                "options": web_options,
                "header_text": menu.get("header_text") or menu.get("title") or menu.get("label") or "",
                "node_id": menu.get("node_id") or menu.get("id") or "",
            },
        ))

        # Also include a text action so the widget can display the menu text
        actions.append(BotAction(
            action_type=ActionType.TEXT,
            payload={"text": clean_body},
        ))

        return actions


class DefaultChannelRenderer(BaseChannelRenderer):
    """
    Generic text-based numbered list for Telegram, Slack, Facebook, etc.
    Produces a plain-text numbered list renderable on any channel.
    """
    channel_name = "default"

    def render_menu_actions(
        self,
        response: EngineResponse,
        state: UserSessionState,
    ) -> List[BotAction]:
        menu = response.interactive_menu
        if not menu:
            return response.actions

        options = _extract_menu_options(menu)
        header = menu.get("header_text") or menu.get("title") or menu.get("label") or "Menu"
        body = menu.get("body_text") or menu.get("description") or "Please select an option:"

        # Build numbered text list
        lines = [body.replace("*", ""), ""]
        for opt in options:
            num = opt.get("option_number") or opt.get("id", "")
            label = opt.get("button_text") or opt.get("label", "")
            lines.append(f"{num}. {label}")

        lines.append("")
        lines.append("Reply with the option number to select.")

        text_content = "\n".join(lines)

        return [
            BotAction(
                action_type=ActionType.TEXT,
                payload={"text": text_content},
            ),
        ]


# ── Renderer Registry ──────────────────────────────────────────────────────────

_RENDERER_REGISTRY: Dict[str, BaseChannelRenderer] = {}


def _init_default_renderers() -> None:
    """Register built-in channel renderers."""
    global _RENDERER_REGISTRY
    _RENDERER_REGISTRY = {
        "whatsapp": WhatsAppChannelRenderer(),
        "widget": WebChannelRenderer(),
        "web": WebChannelRenderer(),
        "web_api": WebChannelRenderer(),
        "default": DefaultChannelRenderer(),
        "telegram": DefaultChannelRenderer(),
        "facebook": DefaultChannelRenderer(),
        "slack": DefaultChannelRenderer(),
    }


_init_default_renderers()


def get_channel_renderer(channel: str) -> BaseChannelRenderer:
    """
    Get the appropriate renderer for a channel.
    Falls back to DefaultChannelRenderer if not found.
    """
    return _RENDERER_REGISTRY.get(channel, _RENDERER_REGISTRY["default"])


def register_renderer(channel: str, renderer: BaseChannelRenderer) -> None:
    """Register a custom renderer for a channel."""
    _RENDERER_REGISTRY[channel] = renderer
