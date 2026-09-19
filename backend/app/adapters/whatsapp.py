"""
WhatsApp adapter — Meta WhatsApp Cloud API (official, no Twilio).

Incoming: POST JSON from Meta (after GET verification handshake).
Outgoing: POST https://graph.facebook.com/v20.0/{phone_number_id}/messages

Config keys expected in institution settings.whatsapp_config:
  phone_number_id  — the Meta-assigned Phone Number ID for this institution's number
  access_token     — System User Token (permanent) from Meta Business Manager
  app_secret       — App Secret for X-Hub-Signature-256 verification
  verify_token     — A string you choose; must match what's set in Meta App Dashboard

Multi-tenant routing:
  Meta sends ALL messages for an App to ONE webhook URL.
  We identify the institution by matching phone_number_id against the DB.
"""
from __future__ import annotations
import hashlib
import hmac
import logging
from typing import Optional

import httpx

from app.adapters.base import ChannelAdapter
from app.core.message import NormalizedMessage, CHANNEL_WHATSAPP

logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v20.0"


def verify_meta_signature(app_secret: str, body_bytes: bytes, signature_header: str) -> bool:
    """
    Verify X-Hub-Signature-256 sent by Meta on every webhook POST.
    Protects against spoofed requests.
    """
    if not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode(), body_bytes, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


class WhatsAppAdapter(ChannelAdapter):
    channel_name = CHANNEL_WHATSAPP

    async def parse_incoming(
        self,
        raw_data: dict,
        client_id: str,
    ) -> Optional[NormalizedMessage]:
        """
        Parse Meta WhatsApp Cloud API payload.
        Supports text messages, interactive button replies, list replies, and quick replies.
        """
        if raw_data.get("object") != "whatsapp_business_account":
            return None

        for entry in raw_data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                if not messages:
                    continue  # status update / delivery receipt

                msg = messages[0]
                msg_type = msg.get("type", "")
                text = ""

                interactive_id = ""
                if msg_type == "text":
                    text = msg.get("text", {}).get("body", "").strip()
                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    # Button reply
                    btn_reply = interactive.get("button_reply", {})
                    if btn_reply:
                        text = btn_reply.get("title", "")
                        interactive_id = btn_reply.get("id", "")
                    if not text:
                        # List selection reply
                        list_reply = interactive.get("list_reply", {})
                        if list_reply:
                            text = list_reply.get("title", "")
                            interactive_id = list_reply.get("id", "")
                elif msg_type == "button":
                    text = msg.get("button", {}).get("text", "").strip()
                    interactive_id = msg.get("button", {}).get("payload", "")

                sender = msg.get("from", "")
                phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
                
                contacts = value.get("contacts", [])
                contact_name = contacts[0].get("profile", {}).get("name", "") if contacts else ""

                if not text or not sender:
                    continue

                return NormalizedMessage(
                    user_id=sender,
                    message=text,
                    channel=CHANNEL_WHATSAPP,
                    client_id=client_id,
                    metadata={
                        "phone_number_id": phone_number_id,
                        "message_id": msg.get("id", ""),
                        "contact_name": contact_name,
                        "interactive_id": interactive_id,
                    },
                )

        return None  # nothing to process

    async def _post_payload(self, phone_number_id: str, access_token: str, payload: dict) -> dict:
        result = {
            "status": "pending",
            "payload": payload,
            "meta_status": None,
            "meta_response": None,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                resp = await http.post(
                    f"{GRAPH_API}/{phone_number_id}/messages",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                result["meta_status"] = resp.status_code
                try:
                    result["meta_response"] = resp.json()
                except Exception:
                    result["meta_response"] = resp.text

                if resp.is_success:
                    result["status"] = "delivered"
                else:
                    result["status"] = "meta_api_error"
                    logger.error("WhatsApp API error %s: %s", resp.status_code, resp.text)
        except Exception as exc:
            result["status"] = "network_error"
            result["error"] = str(exc)
            logger.exception("Failed to send WhatsApp payload: %s", exc)

        return result

    async def send_response(
        self,
        msg: NormalizedMessage,
        response_text: str,
        config: dict,
    ) -> dict:
        """
        Send reply via Meta WhatsApp Cloud API.
        Endpoint: POST /v20.0/{phone_number_id}/messages
        Returns dict with status, outgoing payload, and Meta API response.

        Applies WhatsApp-native rich text formatting (bold headings, contextual
        emojis, clean bullet points) before dispatch for mobile readability.
        """
        from app.utils.whatsapp_formatter import format_for_whatsapp

        phone_number_id = config.get("phone_number_id") or msg.metadata.get("phone_number_id")
        access_token = config.get("access_token", "")

        # Guarantee non-empty text body (Meta Cloud API rejects empty string with 400 Bad Request)
        clean_text = (response_text or "").strip()
        if not clean_text:
            clean_text = "Hello! How can I assist you today?"

        # Apply WhatsApp-native rich text formatting
        clean_text = format_for_whatsapp(clean_text)

        if not phone_number_id or not access_token:
            logger.error("WhatsApp send failed: missing phone_number_id or access_token for %s", msg.client_id)
            return {
                "status": "config_error",
                "error": "Missing phone_number_id or access_token in institution settings",
                "payload": None,
                "meta_response": None,
            }

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": msg.user_id,
            "type": "text",
            "text": {"preview_url": False, "body": clean_text},
        }

        return await self._post_payload(phone_number_id, access_token, payload)

    async def send_interactive_menu(
        self,
        msg: NormalizedMessage,
        body_text: str,
        options: list[dict],
        config: dict,
        header_text: Optional[str] = None,
    ) -> dict:
        """
        Send interactive WhatsApp menu:
        - If 1 to 3 options: send button reply message.
        - If 4 to 10 options: send list reply message.
        """
        phone_number_id = config.get("phone_number_id") or msg.metadata.get("phone_number_id")
        access_token = config.get("access_token", "")
        if not phone_number_id or not access_token or not options:
            return {"status": "skipped"}

        # Limit to 10 max per WhatsApp Cloud API restrictions
        options = options[:10]

        if len(options) <= 3:
            # Button reply
            buttons = []
            for i, opt in enumerate(options):
                opt_id = str(opt.get("id") or f"opt_{i}")
                opt_title = str(opt.get("label") or opt.get("title") or f"Option {i+1}")[:20]  # 20-char button title limit
                buttons.append({
                    "type": "reply",
                    "reply": {"id": opt_id, "title": opt_title},
                })
            action_payload = {"buttons": buttons}
            interactive_type = "button"
        else:
            # List message
            rows = []
            for i, opt in enumerate(options):
                opt_id = str(opt.get("id") or f"opt_{i}")
                opt_title = str(opt.get("label") or opt.get("title") or f"Option {i+1}")[:24]  # 24-char title limit
                opt_desc = str(opt.get("description") or "")[:72]
                row = {"id": opt_id, "title": opt_title}
                if opt_desc:
                    row["description"] = opt_desc
                rows.append(row)
            action_payload = {
                "button": "View Options",
                "sections": [{"title": "Select an Option", "rows": rows}],
            }
            interactive_type = "list"

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": msg.user_id,
            "type": "interactive",
            "interactive": {
                "type": interactive_type,
                "body": {"text": (body_text or "Please select an option below:").strip()[:1024]},
                "action": action_payload,
            },
        }
        if header_text:
            payload["interactive"]["header"] = {"type": "text", "text": header_text[:60]}

        return await self._post_payload(phone_number_id, access_token, payload)

    async def send_image_message(
        self,
        msg: NormalizedMessage,
        image_url: str,
        caption: Optional[str],
        config: dict,
    ) -> dict:
        """Send an image attachment via WhatsApp, converting public Google Drive URLs to direct renderable links."""
        from app.utils.media_url import transform_google_drive_url, extract_google_drive_file_id

        phone_number_id = config.get("phone_number_id") or msg.metadata.get("phone_number_id")
        access_token = config.get("access_token", "")
        if not phone_number_id or not access_token or not image_url:
            return {"status": "skipped"}

        # Transform Google Drive URLs to directly renderable format
        direct_url = transform_google_drive_url(image_url)
        is_drive = extract_google_drive_file_id(image_url) is not None
        if is_drive:
            logger.info("Google Drive image URL transformed: %s -> %s", image_url[:80], direct_url[:80])

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": msg.user_id,
            "type": "image",
            "image": {
                "link": direct_url,
            },
        }
        if caption:
            payload["image"]["caption"] = caption[:1024]

        result = await self._post_payload(phone_number_id, access_token, payload)

        # Fallback: if the primary thumbnail URL failed and this was a Drive link,
        # retry with direct download URL
        if is_drive and result.get("status") != "delivered":
            from app.utils.media_url import get_direct_download_url
            fallback_url = get_direct_download_url(image_url)
            logger.info("Retrying Google Drive image with fallback URL: %s", fallback_url[:80])
            payload["image"]["link"] = fallback_url
            result = await self._post_payload(phone_number_id, access_token, payload)

        return result
