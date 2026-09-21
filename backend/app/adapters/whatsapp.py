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
        """
        Send an image attachment via WhatsApp.

        For Google Drive URLs: downloads the image server-side, uploads it to
        WhatsApp's Media API (POST /{phone_number_id}/media), and sends using
        the returned media_id. This bypasses Google Drive's redirect/cookie/consent
        walls that block WhatsApp's link-based image fetching.

        For regular public URLs: sends directly using the link approach.
        """
        from app.utils.media_url import extract_google_drive_file_id

        phone_number_id = config.get("phone_number_id") or msg.metadata.get("phone_number_id")
        access_token = config.get("access_token", "")
        if not phone_number_id or not access_token or not image_url:
            return {"status": "skipped"}

        is_drive = extract_google_drive_file_id(image_url) is not None

        if is_drive:
            # ── Google Drive: Download → Upload to WhatsApp Media API → Send via media_id ──
            return await self._send_drive_image(
                msg, image_url, caption, phone_number_id, access_token
            )
        else:
            # ── Regular URL: Send directly via link ──
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": msg.user_id,
                "type": "image",
                "image": {"link": image_url.strip()},
            }
            if caption:
                payload["image"]["caption"] = caption[:1024]
            return await self._post_payload(phone_number_id, access_token, payload)

    async def _send_drive_image(
        self,
        msg: NormalizedMessage,
        drive_url: str,
        caption: Optional[str],
        phone_number_id: str,
        access_token: str,
    ) -> dict:
        """
        Download a Google Drive image and send it via WhatsApp Media Upload API.

        Flow:
          1. Build multiple direct-download URL variants for the file ID
          2. Try downloading the image bytes (with redirect following)
          3. Upload image bytes to WhatsApp Media API → get media_id
          4. Send message using media_id
        """
        from app.utils.media_url import extract_google_drive_file_id

        file_id = extract_google_drive_file_id(drive_url)
        if not file_id:
            return {"status": "skipped", "error": "Could not extract Google Drive file ID"}

        # Try multiple Google Drive direct-access URL variants
        download_urls = [
            f"https://drive.google.com/uc?export=download&id={file_id}",
            f"https://drive.google.com/thumbnail?id={file_id}&sz=w1600",
            f"https://lh3.googleusercontent.com/d/{file_id}",
        ]

        image_bytes = None
        content_type = "image/jpeg"  # default
        used_url = ""

        async with httpx.AsyncClient(timeout=30, follow_redirects=True, max_redirects=10) as http:
            for url in download_urls:
                try:
                    resp = await http.get(url)
                    ct = resp.headers.get("content-type", "")

                    # Verify we got actual image data (not an HTML consent page)
                    if resp.is_success and ct.startswith("image/"):
                        image_bytes = resp.content
                        content_type = ct.split(";")[0].strip()
                        used_url = url
                        logger.info(
                            "Google Drive image downloaded: %s (%d bytes, %s)",
                            url[:80], len(image_bytes), content_type,
                        )
                        break
                    else:
                        logger.debug(
                            "Google Drive URL returned non-image: %s (status=%d, content-type=%s)",
                            url[:80], resp.status_code, ct[:60],
                        )
                except Exception as e:
                    logger.debug("Google Drive download failed for %s: %s", url[:60], e)

        if not image_bytes:
            logger.warning(
                "All Google Drive download attempts failed for file_id=%s (original: %s)",
                file_id, drive_url[:80],
            )
            return {
                "status": "drive_download_failed",
                "error": f"Could not download image from Google Drive (file_id={file_id}). "
                         f"Ensure the file is shared as 'Anyone with the link can view'.",
            }

        # ── Upload to WhatsApp Media API ──────────────────────────────────────
        media_id = await self._upload_media(
            phone_number_id, access_token, image_bytes, content_type
        )

        if not media_id:
            return {
                "status": "media_upload_failed",
                "error": "Failed to upload image to WhatsApp Media API",
            }

        # ── Send message using media_id ───────────────────────────────────────
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": msg.user_id,
            "type": "image",
            "image": {"id": media_id},
        }
        if caption:
            payload["image"]["caption"] = caption[:1024]

        result = await self._post_payload(phone_number_id, access_token, payload)
        result["media_id"] = media_id
        result["drive_file_id"] = file_id
        result["download_url"] = used_url
        return result

    async def _upload_media(
        self,
        phone_number_id: str,
        access_token: str,
        image_bytes: bytes,
        content_type: str = "image/jpeg",
    ) -> Optional[str]:
        """
        Upload image bytes to WhatsApp Cloud API Media endpoint.

        POST /{phone_number_id}/media
        Content-Type: multipart/form-data

        Returns the media_id string, or None on failure.
        """
        # Determine file extension from content type
        ext_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }
        ext = ext_map.get(content_type, ".jpg")
        filename = f"image{ext}"

        try:
            async with httpx.AsyncClient(timeout=30) as http:
                resp = await http.post(
                    f"{GRAPH_API}/{phone_number_id}/media",
                    headers={"Authorization": f"Bearer {access_token}"},
                    data={
                        "messaging_product": "whatsapp",
                        "type": content_type,
                    },
                    files={
                        "file": (filename, image_bytes, content_type),
                    },
                )

                if resp.is_success:
                    media_id = resp.json().get("id")
                    logger.info(
                        "WhatsApp media uploaded: media_id=%s (%d bytes, %s)",
                        media_id, len(image_bytes), content_type,
                    )
                    return media_id
                else:
                    logger.error(
                        "WhatsApp media upload failed: %d — %s",
                        resp.status_code, resp.text[:300],
                    )
                    return None
        except Exception as exc:
            logger.exception("WhatsApp media upload error: %s", exc)
            return None

