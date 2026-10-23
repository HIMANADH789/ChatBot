"""
Platform integration webhooks — channel-agnostic adapter architecture.

Route design:
  Meta (WhatsApp / Facebook): GLOBAL routes (one URL for all institutions).
    Institutions are identified by phone_number_id (WhatsApp) or page_id (Facebook).
    Meta routes all messages for one App to a single webhook URL.

  Telegram / Slack: per-institution routes using {client_id} in the URL.
    Simpler setup; each institution registers its own bot.

URL layout:
  GET  /api/webhook/whatsapp              — Meta verification handshake
  POST /api/webhook/whatsapp              — WhatsApp message events
  GET  /api/webhook/facebook              — Meta verification handshake
  POST /api/webhook/facebook              — Facebook Messenger events
  POST /api/integrations/{client_id}/telegram              — Telegram updates
  POST /api/integrations/{client_id}/telegram/register    — Register Telegram webhook URL
  POST /api/integrations/{client_id}/slack                 — Slack Events API

Security:
  - WhatsApp / Facebook: X-Hub-Signature-256 HMAC-SHA256
  - Slack: X-Slack-Signature HMAC-SHA256 with replay protection
  - Telegram: optional X-Telegram-Bot-Api-Secret-Token header check
"""
from __future__ import annotations

import json
import logging
import time

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.adapters import factory as adapter_factory
from app.adapters.facebook import FacebookAdapter, verify_meta_signature as fb_verify
from app.adapters.slack import SlackAdapter, verify_slack_signature
from app.adapters.telegram import TelegramAdapter
from app.adapters.whatsapp import WhatsAppAdapter, verify_meta_signature as wa_verify
from app.core.handler import handle_incoming, lookup_client_by_platform_id
from app.core.message import CHANNEL_FACEBOOK, CHANNEL_SLACK, CHANNEL_TELEGRAM, CHANNEL_WHATSAPP
from app.db.mongodb import get_db
from app.db.collections import CLIENTS

logger = logging.getLogger(__name__)

integrations_router = APIRouter(prefix="/integrations", tags=["integrations"])
router = integrations_router


def _get_adapter(channel: str):
    adapter = adapter_factory.get(channel)
    if adapter is None:
        raise RuntimeError(f"No adapter registered for channel '{channel}'")
    return adapter


# ── WhatsApp (Meta Cloud API) ─────────────────────────────────────────────────

@integrations_router.get("/{client_id}/whatsapp", response_class=PlainTextResponse)
async def whatsapp_verify(
    client_id: str,
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification — returns hub.challenge on success."""
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id})
    if not client:
        raise HTTPException(404, "Institution not found")
        
    expected = client.get("settings", {}).get("whatsapp_config", {}).get("verify_token", "")
    if not expected:
        expected = "SynapDeskSecretToken123"
    
    if hub_mode == "subscribe" and hub_verify_token == expected and hub_challenge:
        return hub_challenge
    raise HTTPException(403, "WhatsApp webhook verification failed. Check verify_token.")


_PROCESSED_MESSAGE_IDS: dict[str, float] = {}

def _check_and_mark_message_processed(message_id: str) -> bool:
    """
    Deduplication guard for platform webhooks (e.g. Meta WhatsApp Cloud API retries/duplicates).
    Returns True if this message_id was already received and processed within the last 24h.
    """
    if not message_id:
        return False
    now = time.time()
    cutoff = now - 86400  # 24 hour deduplication window
    expired = [k for k, ts in list(_PROCESSED_MESSAGE_IDS.items()) if ts < cutoff]
    for k in expired:
        _PROCESSED_MESSAGE_IDS.pop(k, None)

    if message_id in _PROCESSED_MESSAGE_IDS:
        return True
    _PROCESSED_MESSAGE_IDS[message_id] = now
    return False


@integrations_router.post("/{client_id}/whatsapp")
async def whatsapp_webhook(client_id: str, request: Request, background_tasks: BackgroundTasks):
    """
    Receive WhatsApp messages and event webhooks from Meta Cloud API.
    Multi-tenant: per-client webhook URL.
    """
    from datetime import datetime, timezone

    body_bytes = await request.body()
    log_entry = {
        "client_id": client_id,
        "channel": "whatsapp",
        "timestamp": datetime.now(timezone.utc),
        "raw_payload": None,
        "status": None,
        "sender_id": None,
        "sender_name": None,
        "message_in": None,
        "error": None,
    }

    try:
        raw = json.loads(body_bytes)
    except json.JSONDecodeError:
        log_entry["status"] = "invalid_json"
        log_entry["error"] = "Could not parse JSON body"
        db = get_db()
        await db["webhook_logs"].insert_one(log_entry)
        raise HTTPException(400, "Invalid JSON")

    log_entry["raw_payload"] = raw

    # Verify signature using institution's app_secret
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id})
    if not client:
        logger.debug("WhatsApp: no institution found for client_id=%s", client_id)
        log_entry["status"] = "client_not_found"
        await db["webhook_logs"].insert_one(log_entry)
        return {"status": "ignored"}
        
    app_secret = client.get("settings", {}).get("whatsapp_config", {}).get("app_secret", "")
    sig = request.headers.get("X-Hub-Signature-256", "")
    if app_secret and sig and not wa_verify(app_secret, body_bytes, sig):
        log_entry["status"] = "signature_failed"
        await db["webhook_logs"].insert_one(log_entry)
        raise HTTPException(403, "Invalid WhatsApp signature")

    adapter = _get_adapter(CHANNEL_WHATSAPP)
    msg = await adapter.parse_incoming(raw, client_id)

    if msg is None:
        # Check if it's a delivery status update / receipt
        status_info = None
        for entry in raw.get("entry", []):
            for change in entry.get("changes", []):
                statuses = change.get("value", {}).get("statuses", [])
                if statuses:
                    status_info = statuses[0]
                    break

        if status_info:
            log_entry["status"] = f"receipt_{status_info.get('status', 'update')}"
            log_entry["sender_id"] = status_info.get("recipient_id")
            log_entry["metadata"] = {
                "message_id": status_info.get("id"),
                "delivery_status": status_info.get("status"),
                "timestamp": status_info.get("timestamp"),
            }
        else:
            log_entry["status"] = "unhandled_event"
            log_entry["error"] = "Webhook received non-message event (e.g., system alert or unsupported payload)"

        await db["webhook_logs"].insert_one(log_entry)
        return {"status": "ignored"}

    # Atomic message deduplication: discard duplicate deliveries from Meta within 24h
    incoming_msg_id = msg.metadata.get("message_id", "")
    if incoming_msg_id and _check_and_mark_message_processed(incoming_msg_id):
        logger.warning("Duplicate webhook message ignored: message_id=%s for client=%s", incoming_msg_id, client_id)
        log_entry["status"] = "duplicate_ignored"
        log_entry["sender_id"] = msg.user_id
        log_entry["sender_name"] = msg.metadata.get("contact_name")
        log_entry["message_in"] = msg.message
        log_entry["metadata"] = msg.metadata
        await db["webhook_logs"].insert_one(log_entry)
        return {"status": "duplicate_ignored"}

    log_entry["status"] = "message_received"
    log_entry["sender_id"] = msg.user_id
    log_entry["sender_name"] = msg.metadata.get("contact_name")
    log_entry["message_in"] = msg.message
    log_entry["metadata"] = msg.metadata
    await db["webhook_logs"].insert_one(log_entry)

    # Fire-and-forget: RAG can take a few moments, Meta expects 200 within 20s
    background_tasks.add_task(handle_incoming, msg, adapter)
    return {"status": "ok"}


@integrations_router.get("/{client_id}/whatsapp/debug")
async def whatsapp_debug(client_id: str):
    """
    Diagnostic endpoint — hit from browser to check the full WhatsApp pipeline.
    URL: https://synapdesk.onrender.com/api/integrations/sv_professionals/whatsapp/debug
    """
    checks = {}

    # 1. Check if client exists in DB
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id})
    if not client:
        checks["client_found"] = False
        return {"status": "FAIL", "checks": checks, "error": f"Client '{client_id}' not found in database"}
    checks["client_found"] = True

    # 2. Check whatsapp_config exists
    wa_config = client.get("settings", {}).get("whatsapp_config", {})
    checks["whatsapp_config_exists"] = bool(wa_config)

    # Also check setups.whatsapp
    setups_wa = client.get("settings", {}).get("setups", {}).get("whatsapp", {})
    checks["setups_whatsapp_exists"] = bool(setups_wa)

    # 3. Check required fields
    phone_number_id = wa_config.get("phone_number_id", "")
    access_token = wa_config.get("access_token", "")
    checks["phone_number_id"] = phone_number_id[:10] + "..." if phone_number_id else "MISSING"
    checks["access_token"] = access_token[:15] + "..." if access_token else "MISSING"
    checks["verify_token"] = wa_config.get("verify_token", "MISSING")

    # 4. Check adapter is registered
    try:
        adapter = _get_adapter(CHANNEL_WHATSAPP)
        checks["adapter_registered"] = True
    except RuntimeError:
        checks["adapter_registered"] = False

    # 5. Check LLM provider
    try:
        from app.config import settings as app_settings
        checks["llm_provider"] = app_settings.LLM_PROVIDER
        checks["groq_model"] = app_settings.GROQ_MODEL if app_settings.LLM_PROVIDER == "groq" else "N/A"
        checks["gemini_api_key_set"] = bool(app_settings.GEMINI_API_KEY)
        checks["groq_api_key_set"] = bool(app_settings.GROQ_API_KEY)
    except Exception as e:
        checks["settings_error"] = str(e)

    # 6. Test sending a WhatsApp message (to the WABA phone itself, as a ping)
    if phone_number_id and access_token:
        try:
            test_payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": "919999999999",  # dummy — will fail but shows if API auth works
                "type": "text",
                "text": {"preview_url": False, "body": "SynapDesk connectivity test"},
            }
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.post(
                    f"https://graph.facebook.com/v20.0/{phone_number_id}/messages",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=test_payload,
                )
                checks["meta_api_status"] = resp.status_code
                checks["meta_api_response"] = resp.json()
        except Exception as e:
            checks["meta_api_error"] = str(e)
    else:
        checks["meta_api_test"] = "SKIPPED — missing phone_number_id or access_token"

    all_ok = (
        checks.get("client_found")
        and checks.get("whatsapp_config_exists")
        and checks.get("adapter_registered")
        and phone_number_id
        and access_token
    )

    return {"status": "OK" if all_ok else "ISSUES_FOUND", "checks": checks}


@integrations_router.get("/{client_id}/whatsapp/logs")
async def whatsapp_logs(client_id: str):
    """
    View recent webhook logs — hit from browser to see what Meta is sending us.
    URL: https://synapdesk.onrender.com/api/integrations/sv_professionals/whatsapp/logs
    """
    db = get_db()
    logs = await db["webhook_logs"].find(
        {"client_id": client_id, "channel": "whatsapp"}
    ).sort("timestamp", -1).to_list(length=20)

    # Convert ObjectId to string for JSON serialization
    for log in logs:
        log["_id"] = str(log["_id"])
        if log.get("timestamp"):
            log["timestamp"] = str(log["timestamp"])

    return {
        "total_logs": len(logs),
        "logs": logs,
        "note": "If total_logs is 0, Meta is NOT sending webhooks to this URL at all."
    }



# ── Facebook Messenger (Meta) ─────────────────────────────────────────────────

@integrations_router.get("/{client_id}/facebook", response_class=PlainTextResponse)
async def facebook_verify(
    client_id: str,
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification for Facebook Messenger."""
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id})
    if not client:
        raise HTTPException(404, "Institution not found")
        
    expected = client.get("settings", {}).get("facebook_config", {}).get("verify_token", "")
    if not expected:
        expected = "SynapDeskSecretToken123"
        
    if hub_mode == "subscribe" and hub_verify_token == expected and hub_challenge:
        return hub_challenge
    raise HTTPException(403, "Facebook webhook verification failed. Check verify_token.")


@integrations_router.post("/{client_id}/facebook")
async def facebook_webhook(client_id: str, request: Request, background_tasks: BackgroundTasks):
    """
    Receive Facebook Messenger messages from Meta.
    Multi-tenant: per-client webhook URL.
    """
    body_bytes = await request.body()
    try:
        raw = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    # Verify signature
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id})
    if not client:
        logger.debug("Facebook: no institution found for client_id=%s", client_id)
        return {"status": "ignored"}
        
    app_secret = client.get("settings", {}).get("facebook_config", {}).get("app_secret", "")
    sig = request.headers.get("X-Hub-Signature-256", "")
    if app_secret and sig and not fb_verify(app_secret, body_bytes, sig):
        raise HTTPException(403, "Invalid Facebook signature")

    adapter = _get_adapter(CHANNEL_FACEBOOK)
    msg = await adapter.parse_incoming(raw, client_id)
    if msg is None:
        return {"status": "ignored"}

    background_tasks.add_task(handle_incoming, msg, adapter)
    return {"status": "ok"}


# ── Telegram ──────────────────────────────────────────────────────────────────

@integrations_router.post("/{client_id}/telegram")
async def telegram_webhook(client_id: str, request: Request, background_tasks: BackgroundTasks):
    """
    Telegram Bot API webhook (POST JSON updates).
    Optional: validate X-Telegram-Bot-Api-Secret-Token if secret_token is configured.
    """
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id})
    if not client:
        raise HTTPException(404, "Institution not found")

    tg_config = client.get("settings", {}).get("telegram_config", {})
    secret_token = tg_config.get("secret_token", "")
    if secret_token:
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if provided != secret_token:
            raise HTTPException(403, "Invalid Telegram secret token")

    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    adapter = _get_adapter(CHANNEL_TELEGRAM)
    msg = await adapter.parse_incoming(raw, client_id)
    if msg is None:
        return {"ok": True}

    background_tasks.add_task(handle_incoming, msg, adapter)
    return {"ok": True}


@integrations_router.post("/{client_id}/telegram/register")
async def register_telegram_webhook(client_id: str, request: Request):
    """
    Register this server as the Telegram webhook for an institution's bot.
    Body: {"webhook_url": "https://your-domain.com"}
    The bot will receive updates at {webhook_url}/api/integrations/{client_id}/telegram
    """
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id})
    if not client:
        raise HTTPException(404, "Institution not found")

    tg_config = client.get("settings", {}).get("telegram_config", {})
    bot_token = tg_config.get("bot_token", "")
    if not bot_token:
        raise HTTPException(400, "Configure telegram_config.bot_token first")

    body = await request.json()
    webhook_url = body.get("webhook_url", "").rstrip("/")
    if not webhook_url:
        raise HTTPException(400, "webhook_url required in body")

    target = f"{webhook_url}/api/integrations/{client_id}/telegram"
    payload: dict = {"url": target}

    # Optionally attach secret_token so Telegram sends it in every request
    secret_token = tg_config.get("secret_token", "")
    if secret_token:
        payload["secret_token"] = secret_token

    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            json=payload,
        )
        data = resp.json()

    if not data.get("ok"):
        raise HTTPException(400, f"Telegram error: {data.get('description', 'Unknown')}")

    return {"message": "Webhook registered", "url": target, "telegram_response": data}


# ── Slack ─────────────────────────────────────────────────────────────────────

@integrations_router.post("/{client_id}/slack")
async def slack_webhook(client_id: str, request: Request, background_tasks: BackgroundTasks):
    """
    Slack Events API webhook.

    CRITICAL: Slack requires a response within 3 seconds.
    We return 200 immediately for real events and use BackgroundTasks for processing.
    URL verification challenge is answered inline (no RAG needed).
    """
    body_bytes = await request.body()

    # Signature verification before parsing body
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id})
    if not client:
        raise HTTPException(404, "Institution not found")

    slack_config = client.get("settings", {}).get("slack_config", {})
    signing_secret = slack_config.get("signing_secret", "")

    if signing_secret:
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")
        if not verify_slack_signature(signing_secret, body_bytes, timestamp, signature):
            raise HTTPException(403, "Invalid Slack signature")

    try:
        raw = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    # URL verification — must respond inline, cannot defer
    if raw.get("type") == "url_verification":
        return JSONResponse({"challenge": raw.get("challenge")})

    adapter = _get_adapter(CHANNEL_SLACK)
    msg = await adapter.parse_incoming(raw, client_id)
    if msg is None:
        return {"status": "ignored"}

    # Use BackgroundTasks — Slack's 3-second window requires immediate 200
    background_tasks.add_task(handle_incoming, msg, adapter)
    return {"status": "ok"}
