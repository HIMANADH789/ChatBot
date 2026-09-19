import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.auth import get_current_user
from app.db.mongodb import get_db
from app.db.collections import CLIENTS, USERS, PLATFORM_CONFIG
from app.models.client import ClientCreate, ALL_SETUPS, SETUP_META, setup_defaults, get_setup
from app.services import auth_service
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Response, Header, Query

router = APIRouter(prefix="/clients", tags=["clients"])

# ── Helpers ───────────────────────────────────────────────────────────────────

_SENSITIVE_KEYS = {"token", "access_token", "app_secret", "page_access_token", "bot_token", "signing_secret"}

def _mask_setup(cfg: dict) -> dict:
    """Replace secret values with mask for admin (read-only) view."""
    out = {}
    for k, v in cfg.items():
        if k in _SENSITIVE_KEYS and v:
            out[k] = "••••••••••••••••"
        else:
            out[k] = v
    return out


# ── Institution CRUD ──────────────────────────────────────────────────────────

@router.post("")
async def create_client(request: ClientCreate, user: dict = Depends(get_current_user)):
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Only super admins can create clients")
    db = get_db()
    if await db[CLIENTS].find_one({"client_id": request.client_id}):
        raise HTTPException(400, "Client ID already exists")
    settings_dict = request.settings.model_dump()
    # Auto-populate widget allowed_origins from domain if provided
    if request.domain:
        domain = request.domain.strip().rstrip("/")
        # Normalise: ensure it has a scheme so Origin headers match
        if not domain.startswith("http"):
            origins = [f"https://{domain}", f"http://{domain}"]
        else:
            origins = [domain]
        if "setups" not in settings_dict:
            from app.models.client import default_setups
            settings_dict["setups"] = default_setups()
        settings_dict["setups"]["widget"]["allowed_origins"] = origins

    import os
    try:
        script_path = os.path.join(os.path.dirname(__file__), "..", "assets", "default_widget.js")
        with open(script_path, "r", encoding="utf-8") as f:
            settings_dict["custom_widget_script"] = f.read()
    except Exception:
        pass

    client = {
        "client_id": request.client_id,
        "name": request.name,
        "domain": request.domain,
        "settings": settings_dict,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    await db[CLIENTS].insert_one(client)
    
    if request.admin_email and request.admin_password:
        try:
            await auth_service.register_user(
                email=request.admin_email,
                password=request.admin_password,
                client_id=request.client_id,
                role="admin"
            )
        except ValueError as e:
            # If user already exists, we might want to just skip or return a warning, 
            # but raising 400 is safer so the super admin knows it failed.
            raise HTTPException(400, f"Client created, but admin creation failed: {e}")

    return {"message": "Client created", "client_id": request.client_id}


@router.get("")
async def list_clients(user: dict = Depends(get_current_user)):
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Only super admins can list clients")
    db = get_db()
    cursor = db[CLIENTS].find({}, {"_id": 0})
    clients = await cursor.to_list(length=100)
    return {"clients": clients, "total": len(clients)}


@router.delete("/{client_id}")
async def delete_client(
    client_id: str,
    user: dict = Depends(get_current_user),
    x_master_key: Optional[str] = Header(None)
):
    """Delete an institution and its admins. Super admin only. Requires master key."""
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Only super admins can delete clients")

    if not x_master_key:
        raise HTTPException(400, "Master key required in X-Master-Key header")

    db = get_db()

    # Verify master key
    cursor = db[PLATFORM_CONFIG].find({"type": "master_key"}, {"hash": 1})
    all_keys = await cursor.to_list(length=100)
    if not all_keys:
        raise HTTPException(400, "No master keys configured.")

    valid = any(passlib_bcrypt.verify(x_master_key, k["hash"]) for k in all_keys)
    if not valid:
        raise HTTPException(401, "Incorrect master key")

    # Delete client
    client_res = await db[CLIENTS].delete_one({"client_id": client_id})
    if client_res.deleted_count == 0:
        raise HTTPException(404, "Institution not found")

    # Delete all users associated with this client
    users_res = await db[USERS].delete_many({"client_id": client_id})

    return {
        "message": "Institution deleted successfully",
        "users_deleted": users_res.deleted_count
    }


@router.get("/me/profile")
async def get_my_profile(user: dict = Depends(get_current_user)):
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": user["client_id"]}, {"_id": 0})
    return {"email": user["sub"], "client_id": user["client_id"], "role": user["role"], "client": client}


@router.get("/{client_id}/config")
async def get_client_config(client_id: str, user: dict = Depends(get_current_user)):
    if user.get("role") != "super_admin" and user.get("client_id") != client_id:
        raise HTTPException(403, "Access denied")
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Institution not found")
    return client


@router.get("/{client_id}")
async def get_client(client_id: str):
    """Public — only exposes non-sensitive display settings."""
    db = get_db()
    client = await db[CLIENTS].find_one(
        {"client_id": client_id},
        {"_id": 0, "settings.welcome_message": 1, "settings.theme_color": 1, "settings.menu_graph_nodes": 1, "settings.menu_graph_root_node_id": 1, "settings.chatbot_title": 1, "name": 1},
    )
    if not client:
        raise HTTPException(404, "Client not found")
    return client


@router.patch("/{client_id}/settings")
async def update_client_settings(client_id: str, settings: dict, user: dict = Depends(get_current_user)):
    """Update global (non-setup) settings: welcome_message, theme_color, system_prompt, max_history_turns."""
    db = get_db()
    if user.get("role") != "super_admin" and user.get("client_id") != client_id:
        raise HTTPException(403, "Only super admins or the institution's admin can edit settings")
    allowed = {
        "welcome_message", "system_prompt", "theme_color", "max_history_turns",
        "menu_graph_nodes", "menu_graph_root_node_id",
        "context_images", "descriptive_rules", "chatbot_title",
        "context_mode", "context_instructions", "context_capacity",
    }
    if user.get("role") == "super_admin":
        allowed.add("custom_widget_script")
    update_fields = {f"settings.{k}": v for k, v in settings.items() if k in allowed}
    if not update_fields:
        raise HTTPException(400, "No valid settings fields")
    # Also sync shared settings to existing channel setups so interfaces are never out of sync
    client_doc = await db[CLIENTS].find_one({"client_id": client_id})
    existing_setups = (client_doc or {}).get("settings", {}).get("setups", {})
    shared_sync_keys = {
        "context_mode", "context_instructions", "context_capacity",
        "menu_graph_nodes", "menu_graph_root_node_id",
        "context_images", "descriptive_rules",
    }
    for ch_name in existing_setups.keys():
        for k in shared_sync_keys:
            if k in settings:
                update_fields[f"settings.setups.{ch_name}.{k}"] = settings[k]

    await db[CLIENTS].update_one({"client_id": client_id}, {"$set": update_fields})

    # Invalidate and recompile profile snapshots across all channels
    from app.services.profile_compiler import invalidate_client_profile, compile_client_profile
    invalidate_client_profile(client_id)
    for ch in ALL_SETUPS:
        try:
            await compile_client_profile(client_id, ch)
        except Exception:
            pass

    return {"message": "Settings updated"}


@router.post("/{client_id}/validate-menu-graph")
async def validate_menu_graph_endpoint(
    client_id: str,
    payload: dict,
    user: dict = Depends(get_current_user),
):
    """Validate a menu graph configuration without saving."""
    if user.get("role") != "super_admin" and user.get("client_id") != client_id:
        raise HTTPException(403, "Access denied")

    from app.core.menu_graph import MenuGraph
    nodes = payload.get("nodes", [])
    root_node_id = payload.get("root_node_id", "")
    res = MenuGraph.validate_config(nodes, root_node_id=root_node_id)
    return res


@router.post("/{client_id}/publish-menu-graph")
async def publish_menu_graph_endpoint(
    client_id: str,
    payload: dict,
    user: dict = Depends(get_current_user),
):
    """
    Validate, save, and pre-compile the dynamic menu graph across all setups.
    """
    if user.get("role") != "super_admin" and user.get("client_id") != client_id:
        raise HTTPException(403, "Access denied")

    db = get_db()
    from app.core.menu_graph import MenuGraph
    from app.services.profile_compiler import invalidate_client_profile, compile_client_profile

    nodes = payload.get("nodes", [])
    root_node_id = payload.get("root_node_id", "MENU_ROOT")

    # Validate before saving
    validation = MenuGraph.validate_config(nodes, root_node_id=root_node_id)
    if not validation["valid"]:
        raise HTTPException(400, detail={"message": "Graph validation failed", "errors": validation["errors"], "warnings": validation["warnings"]})

    update_fields = {
        "settings.menu_graph_nodes": nodes,
        "settings.menu_graph_root_node_id": root_node_id,
        "updated_at": datetime.now(timezone.utc),
    }

    # Sync to existing setups
    client_doc = await db[CLIENTS].find_one({"client_id": client_id})
    if not client_doc:
        raise HTTPException(404, "Institution not found")

    existing_setups = (client_doc or {}).get("settings", {}).get("setups", {})
    for ch_name in existing_setups.keys():
        update_fields[f"settings.setups.{ch_name}.menu_graph_nodes"] = nodes
        update_fields[f"settings.setups.{ch_name}.menu_graph_root_node_id"] = root_node_id

    await db[CLIENTS].update_one({"client_id": client_id}, {"$set": update_fields})

    # Invalidate cached profile and compile across setups
    invalidate_client_profile(client_id)
    compiled_results = {}
    for ch in ALL_SETUPS:
        try:
            p = await compile_client_profile(client_id, ch)
            compiled_results[ch] = {
                "version_hash": p.get("version_hash"),
                "compiled_at": p.get("compiled_at"),
            }
        except Exception as e:
            compiled_results[ch] = {"error": str(e)}

    return {
        "message": "Menu graph published and pre-compiled successfully",
        "validation": validation,
        "compiled_setups": compiled_results,
    }

@router.get("/{client_id}/widget.js")
async def get_widget_script(client_id: str):
    """Serve the dynamic widget script for a specific client."""
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id}, {"_id": 0, "settings.custom_widget_script": 1})
    if not client:
        raise HTTPException(404, "Client not found")
    
    script_content = client.get("settings", {}).get("custom_widget_script", "")
    if not script_content:
        import os
        try:
            script_path = os.path.join(os.path.dirname(__file__), "..", "assets", "default_widget.js")
            with open(script_path, "r", encoding="utf-8") as f:
                script_content = f.read()
        except Exception:
            script_content = "console.error('Widget script not configured.');"

    return Response(content=script_content, media_type="application/javascript")


# ── Setup management ──────────────────────────────────────────────────────────

@router.get("/{client_id}/setups")
async def list_setups(client_id: str, user: dict = Depends(get_current_user)):
    """
    Return all setups with their status and non-sensitive config.
    Super admin gets token_set flag (not value). Admin gets masked config.
    """
    if user.get("role") != "super_admin" and user.get("client_id") != client_id:
        raise HTTPException(403, "Access denied")

    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id}, {"_id": 0, "settings": 1})
    if not client:
        raise HTTPException(404, "Institution not found")

    settings = client.get("settings", {})
    is_super = user.get("role") == "super_admin"
    result = []

    for ch in ALL_SETUPS:
        cfg = get_setup(settings, ch)
        meta = SETUP_META[ch]
        entry = {
            "channel": ch,
            "label": meta["label"],
            "emoji": meta["emoji"],
            "enabled": cfg.get("enabled", False),
            "rate_limit_rpm": cfg.get("rate_limit_rpm", 20),
            "rate_limit_rpd": cfg.get("rate_limit_rpd", 200),
            "max_queries_per_session": cfg.get("max_queries_per_session", 50),
        }
        # Token status (widget / web_api)
        if ch in ("widget", "web_api"):
            entry["token_set"] = bool(cfg.get("token", ""))
        result.append(entry)

    return {"setups": result}


@router.get("/{client_id}/setups/{channel}")
async def get_setup_config(client_id: str, channel: str, user: dict = Depends(get_current_user)):
    """
    Return full setup config.
    Super admin: sees token_set flag + all config (secrets masked by default unless rotate is called).
    Admin: masked secrets, read-only.
    """
    if channel not in ALL_SETUPS:
        raise HTTPException(400, f"Unknown channel '{channel}'")
    if user.get("role") != "super_admin" and user.get("client_id") != client_id:
        raise HTTPException(403, "Access denied")

    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id}, {"_id": 0, "settings": 1})
    if not client:
        raise HTTPException(404, "Institution not found")

    cfg = get_setup(client.get("settings", {}), channel)
    is_super = user.get("role") == "super_admin"

    # Mask secrets for admins; super admins see masked too (secrets only shown at rotate time)
    masked = _mask_setup(cfg)

    # Add convenience flags — only web_api uses token (widget uses origin lock)
    if channel == "web_api":
        masked["token_set"] = bool(cfg.get("token", ""))

    meta = SETUP_META[channel]
    return {
        "channel": channel,
        "label": meta["label"],
        "emoji": meta["emoji"],
        "config": masked,
        "editable": is_super,
    }


@router.patch("/{client_id}/setups/{channel}")
async def update_setup_config(client_id: str, channel: str, body: dict, user: dict = Depends(get_current_user)):
    """Update setup config fields. Super admin sets limits, admins set credentials."""
    is_super = user.get("role") == "super_admin"
    if not is_super and user.get("client_id") != client_id:
        raise HTTPException(403, "Access denied")
    if channel not in ALL_SETUPS:
        raise HTTPException(400, f"Unknown channel '{channel}'")

    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id}, {"_id": 0, "settings": 1})
    if not client:
        raise HTTPException(404, "Institution not found")

    settings = client.get("settings", {})
    # Ensure setups dict exists in the document
    if "setups" not in settings:
        # Initialise from defaults (migrating legacy doc)
        from app.models.client import default_setups
        settings["setups"] = default_setups()

    current = get_setup(settings, channel)

    # Admins can edit credentials/origins and context settings, Super Admins can edit limits too
    safe_keys = {
        "allowed_origins",
        "phone_number_id", "access_token", "app_secret", "verify_token",
        "page_id", "page_access_token",
        "bot_token", "secret_token", "signing_secret",
        "context_mode", "context_instructions", "context_capacity",
        "menu_graph_nodes", "menu_graph_root_node_id", "context_images", "descriptive_rules",
    }
    if is_super:
        safe_keys.update({"rate_limit_rpm", "rate_limit_rpd", "max_queries_per_session"})

    # Merge changes into current config (ignore unknown keys)
    for k, v in body.items():
        if k in safe_keys:
            # Prevent accidental overwrite if the frontend sends the mask back
            if v != "••••••••••••••••":
                current[k] = v

    update_path = f"settings.setups.{channel}"
    update_dict = {
        update_path: current,
        "updated_at": datetime.now(timezone.utc),
    }
    # Bidirectional sync: sync context, menu, and rules to root settings so Admin portal stays consistent
    shared_sync_keys = {"context_mode", "context_instructions", "context_capacity", "menu_graph_nodes", "menu_graph_root_node_id", "context_images", "descriptive_rules"}
    for k in shared_sync_keys:
        if k in current and current[k] is not None:
            update_dict[f"settings.{k}"] = current[k]

    await db[CLIENTS].update_one(
        {"client_id": client_id},
        {"$set": update_dict},
        upsert=True,
    )

    # Invalidate and recompile runtime profile snapshots across all channels
    from app.services.profile_compiler import invalidate_client_profile, compile_client_profile
    invalidate_client_profile(client_id)
    for ch in ALL_SETUPS:
        try:
            await compile_client_profile(client_id, ch)
        except Exception as e:
            logger.debug("Async profile recompile on setup update (%s): %s", ch, e)

    return {"message": f"{channel} config updated"}


@router.post("/{client_id}/setups/{channel}/toggle")
async def toggle_setup(client_id: str, channel: str, body: dict, user: dict = Depends(get_current_user)):
    """Enable or disable a setup. Super admin only. Body: {enabled: bool}"""
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Only super admins can activate/deactivate setups")
    if channel not in ALL_SETUPS:
        raise HTTPException(400, f"Unknown channel '{channel}'")

    enabled = bool(body.get("enabled", False))

    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id}, {"_id": 0, "settings": 1})
    if not client:
        raise HTTPException(404, "Institution not found")

    settings = client.get("settings", {})
    if "setups" not in settings:
        from app.models.client import default_setups
        settings["setups"] = default_setups()

    cfg = get_setup(settings, channel)

    # If activating for first time, ensure defaults are seeded
    if enabled and not cfg.get("enabled"):
        defaults = setup_defaults(channel)
        for k, v in defaults.items():
            if k not in cfg:
                cfg[k] = v

    cfg["enabled"] = enabled
    await db[CLIENTS].update_one(
        {"client_id": client_id},
        {"$set": {f"settings.setups.{channel}": cfg, "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    action = "activated" if enabled else "deactivated"
    return {"message": f"{channel} {action}", "enabled": enabled}


@router.post("/{client_id}/setups/{channel}/rotate-token")
async def rotate_setup_token(client_id: str, channel: str, user: dict = Depends(get_current_user)):
    """Generate a new API key token for web_api. Super admin only. Token shown once."""
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Only super admins can rotate tokens")
    if channel != "web_api":
        raise HTTPException(400, "Only web_api uses token-based security. Widget uses Origin enforcement.")

    new_token = secrets.token_urlsafe(32)
    db = get_db()
    await db[CLIENTS].update_one(
        {"client_id": client_id},
        {"$set": {
            f"settings.setups.{channel}.token": new_token,
            "updated_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    return {"token": new_token, "channel": channel}


@router.delete("/{client_id}/setups/{channel}/token")
async def disable_setup_token(client_id: str, channel: str, user: dict = Depends(get_current_user)):
    """Clear the API key token for web_api. Super admin only."""
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Only super admins can modify tokens")
    if channel != "web_api":
        raise HTTPException(400, "Only web_api uses token-based security.")

    db = get_db()
    await db[CLIENTS].update_one(
        {"client_id": client_id},
        {"$set": {f"settings.setups.{channel}.token": "", "updated_at": datetime.now(timezone.utc)}},
    )
    return {"message": f"{channel} token disabled"}


@router.post("/{client_id}/setups/telegram/register-webhook")
async def register_telegram_webhook_from_setup(client_id: str, body: dict, user: dict = Depends(get_current_user)):
    """Register Telegram webhook from the setup config page."""
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin only")
    import httpx
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id}, {"_id": 0, "settings": 1})
    if not client:
        raise HTTPException(404, "Institution not found")
    cfg = get_setup(client.get("settings", {}), "telegram")
    bot_token = cfg.get("bot_token", "")
    if not bot_token:
        raise HTTPException(400, "Configure telegram bot_token first")
    webhook_url = body.get("webhook_url", "").rstrip("/")
    if not webhook_url:
        raise HTTPException(400, "webhook_url required")
    target = f"{webhook_url}/api/integrations/{client_id}/telegram"
    payload: dict = {"url": target}
    if cfg.get("secret_token"):
        payload["secret_token"] = cfg["secret_token"]
    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.post(f"https://api.telegram.org/bot{bot_token}/setWebhook", json=payload)
        data = resp.json()
    if not data.get("ok"):
        raise HTTPException(400, f"Telegram error: {data.get('description', 'Unknown')}")
    return {"message": "Webhook registered", "url": target}


# ── Legacy endpoints (kept for backward compat) ───────────────────────────────

@router.post("/{client_id}/rotate-widget-token")
async def rotate_widget_token(client_id: str, user: dict = Depends(get_current_user)):
    """Deprecated: use /setups/widget/rotate-token instead."""
    return await rotate_setup_token(client_id, "widget", user)


@router.delete("/{client_id}/widget-token")
async def disable_widget_token(client_id: str, user: dict = Depends(get_current_user)):
    """Deprecated: use DELETE /setups/widget/token instead."""
    return await disable_setup_token(client_id, "widget", user)


# ── Compiled Profile Snapshot Endpoints ───────────────────────────────────────

@router.get("/{client_id}/compiled-profile")
async def get_client_compiled_profile(
    client_id: str,
    channel: str = Query("widget"),
    user: dict = Depends(get_current_user),
):
    """Retrieve the pre-compiled runtime profile snapshot."""
    if user.get("role") != "super_admin" and user.get("client_id") != client_id:
        raise HTTPException(403, "Access denied")
    from app.services.profile_compiler import get_compiled_profile
    return await get_compiled_profile(client_id, channel)


@router.post("/{client_id}/recompile-profile")
async def recompile_client_profile_endpoint(
    client_id: str,
    channel: str = Query("widget"),
    user: dict = Depends(get_current_user),
):
    """Manually recompile and refresh the client profile runtime image."""
    if user.get("role") != "super_admin" and user.get("client_id") != client_id:
        raise HTTPException(403, "Access denied")
    from app.services.profile_compiler import invalidate_client_profile, compile_client_profile
    invalidate_client_profile(client_id, channel)
    profile = await compile_client_profile(client_id, channel)
    return {"message": "Profile recompiled successfully", "profile": profile}


