"""
Unified message handler — the single entry point for every incoming message
regardless of which channel it comes from.

Flow:
  NormalizedMessage
      → RAG pipeline (rag_service.query)
      → adapter.send_response()
      → returns response text (so callers can log / test)
"""
from __future__ import annotations
import logging
from typing import Optional

from app.core.message import NormalizedMessage
from app.adapters.base import ChannelAdapter
from app.db.mongodb import get_db
from app.db.collections import CLIENTS

logger = logging.getLogger(__name__)


# Add logging to debug provider initialization
logger = logging.getLogger("ProviderInitialization")


async def _build_providers():
    """Instantiate LLM/embedding/vectordb providers from registry (matching web chat)."""
    from app.providers.registry import (
        get_llm_provider,
        get_embedding_provider,
        get_vectordb_provider,
    )
    llm = get_llm_provider()
    embeddings = get_embedding_provider()
    vectordb = get_vectordb_provider()
    return llm, embeddings, vectordb


async def get_client_platform_config(client_id: str, platform: str) -> dict:
    """Fetch the platform-specific settings dict for a client."""
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id})
    if not client:
        return {}
    return client.get("settings", {}).get(f"{platform}_config", {})


async def handle_incoming(
    msg: NormalizedMessage,
    adapter: ChannelAdapter,
) -> str:
    """
    Process one normalized message end-to-end via the Hybrid State-Machine & RAG Core:
      1. Normalize NormalizedMessage into standardized UserEvent
      2. Run HybridEngine (Deterministic State Engine or Hybrid RAG)
      3. Send reply & media via the appropriate channel adapter
      4. Log complete end-to-end metadata and JSON payloads for monitoring
      5. Return the response text
    """
    import time
    import traceback
    from datetime import datetime, timezone
    from app.core.user_event import UserEvent, EventType, ActionType
    from app.core.hybrid_engine import hybrid_engine
    db = get_db()

    start_time = time.time()
    response_text = ""
    status = "processing"
    error_msg = None
    tb_str = None
    send_info = {}

    try:
        from app.models.client import get_setup

        # Fetch client settings and setup
        client = await db[CLIENTS].find_one({"client_id": msg.client_id})
        cs = (client or {}).get("settings", {})
        setup_cfg = get_setup(cs, msg.channel)
        config = await get_client_platform_config(msg.client_id, msg.channel)
        if not config or not config.get("access_token"):
            config = setup_cfg

        interactive_id = msg.metadata.get("interactive_id", "")
        event_type = EventType.BUTTON_CLICK if interactive_id else EventType.TEXT

        user_event = UserEvent(
            tenant_id=msg.client_id,
            channel=msg.channel,
            user_id=msg.user_id,
            session_id=msg.session_id,
            payload=msg.message,
            event_type=event_type,
            metadata=msg.metadata,
        )

        llm, embeddings, vectordb = await _build_providers()
        engine_res = await hybrid_engine.process_event(
            event=user_event,
            llm=llm,
            embeddings=embeddings,
            vectordb=vectordb,
        )

        response_text = engine_res.text

        # Dispatch each BotAction in order (channel renderer has already
        # formatted them into the correct channel-specific payloads)
        text_sent = False
        for action in engine_res.actions:
            try:
                if action.action_type == ActionType.IMAGE_MEDIA and hasattr(adapter, "send_image_message"):
                    img_url = action.payload.get("image_url") or action.payload.get("image_path", "")
                    caption = action.payload.get("caption") or action.payload.get("title", "")
                    if img_url:
                        await adapter.send_image_message(msg, img_url, caption, config)

                elif action.action_type == ActionType.INTERACTIVE_MENU and hasattr(adapter, "send_interactive_menu"):
                    menu_opts = action.payload.get("options", [])
                    body_text = action.payload.get("body_text", "Please select an option:")
                    header_text = action.payload.get("header_text", "")
                    res = await adapter.send_interactive_menu(
                        msg,
                        body_text=body_text,
                        options=menu_opts,
                        config=config,
                        header_text=header_text,
                    )
                    send_info = res if isinstance(res, dict) else {}
                    status = send_info.get("status", "menu_sent")

                elif action.action_type == ActionType.TEXT and not text_sent:
                    text_content = action.payload.get("text", response_text)
                    if text_content:
                        res = await adapter.send_response(msg, text_content, config)
                        if isinstance(res, dict):
                            send_info = res
                            status = res.get("status", "response_sent")
                        else:
                            status = "response_sent"
                        text_sent = True
            except Exception as action_exc:
                logger.warning("Failed to dispatch action %s: %s", action.action_type, action_exc)

        # Fallback: if no text action was dispatched and this isn't a pure menu response, send text
        if not text_sent and not engine_res.is_deterministic:
            res = await adapter.send_response(msg, response_text, config)
            if isinstance(res, dict):
                send_info = res
                status = res.get("status", "response_sent")
            else:
                status = "response_sent"

    except Exception as exc:
        tb_str = traceback.format_exc()
        error_msg = str(exc)
        status = "error"
        logger.exception("Unified hybrid message handler failed for %s / %s: %s", msg.client_id, msg.channel, exc)
        response_text = "Sorry, I'm having trouble right now. Please try again in a moment."
        try:
            config = await get_client_platform_config(msg.client_id, msg.channel)
            await adapter.send_response(msg, response_text, config)
        except Exception:
            pass

    elapsed_ms = int((time.time() - start_time) * 1000)

    try:
        await db["webhook_logs"].insert_one({
            "client_id": msg.client_id,
            "channel": msg.channel,
            "timestamp": datetime.now(timezone.utc),
            "sender_id": msg.user_id,
            "sender_name": msg.metadata.get("contact_name", ""),
            "message_in": msg.message,
            "response_out": response_text,
            "response_time_ms": elapsed_ms,
            "status": status,
            "outgoing_payload": send_info.get("payload"),
            "meta_status": send_info.get("meta_status"),
            "meta_response": send_info.get("meta_response"),
            "metadata": msg.metadata,
            "error": error_msg,
            "traceback": tb_str,
        })
    except Exception as log_exc:
        logger.warning("Failed to record webhook log: %s", log_exc)

    return response_text


async def lookup_client_by_platform_id(platform: str, id_field: str, id_value: str) -> Optional[str]:
    """
    Find a client_id by a platform-specific identifier.

    e.g. lookup_client_by_platform_id("whatsapp", "phone_number_id", "12345678")
    Returns the client_id string or None if not found.
    """
    db = get_db()
    client = await db[CLIENTS].find_one(
        {f"settings.{platform}_config.{id_field}": id_value},
        {"client_id": 1},
    )
    return client["client_id"] if client else None
