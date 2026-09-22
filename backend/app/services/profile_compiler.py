"""
Profile Compilation Engine:
Pre-compiles client settings, system prompts, descriptive tags, menu trees,
media assets, and client trigger rules into an immutable runtime snapshot
(Client Profile Image) for zero-overhead execution during user sessions.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Any, Dict

from app.db.mongodb import get_db
from app.db.collections import CLIENTS
from app.models.client import get_setup

logger = logging.getLogger(__name__)

# In-memory fast cache: (client_id, channel) -> compiled_profile_dict
_PROFILE_CACHE: Dict[tuple[str, str], dict] = {}


def _flatten_menu_tree(nodes: list[dict], out_index: dict) -> None:
    """Recursively index every node in the menu tree by id and lowercase label for O(1) retrieval."""
    if not nodes:
        return
    for node in nodes:
        node_id = str(node.get("id", "")).strip()
        node_label = str(node.get("label", "")).strip().lower()
        if node_id:
            out_index[node_id] = node
        if node_label:
            out_index[node_label] = node
        children = node.get("children", [])
        if children:
            _flatten_menu_tree(children, out_index)


def _build_compiled_system_prompt(
    base_prompt: str,
    menu_tree: list[dict],
    context_images: list[dict],
    descriptive_rules: list[dict],
    context_mode: str,
    context_instructions: str,
) -> str:
    """
    Compile a unified, high-performance system prompt incorporating:
    - Base assistant persona
    - Inbuilt descriptive tags registry (menus & media awareness)
    - Client descriptive trigger policies
    - Context carrying directives
    """
    sections = [base_prompt.strip()]

    # 1. Inbuilt Descriptive Tags Context
    descriptors = []
    if menu_tree:
        descriptors.append("Interactive Menu Topics available for this institution:")
        for node in menu_tree:
            lbl = node.get("label", "")
            tag = node.get("descriptor_tag", "")
            if tag:
                descriptors.append(f"  • Option '{lbl}': Trigger when '{tag}'")
            else:
                descriptors.append(f"  • Option '{lbl}'")

    if context_images:
        descriptors.append("Contextual Media / Images available to attach:")
        for img in context_images:
            title = img.get("title", "")
            tag = img.get("descriptor_tag", "")
            path = img.get("image_path", "")
            descriptors.append(f"  • Image '{title}' ({path}): Trigger when '{tag}'")

    if descriptors:
        sections.append("\nINBUILT DESCRIPTIVE TAGS & AVAILABLE ASSETS:\n" + "\n".join(descriptors))

    # 2. Client-Configured Descriptive Trigger Policies
    if descriptive_rules:
        rules_text = ["CLIENT-DEFINED DESCRIPTIVE TRIGGER POLICIES:"]
        for r in descriptive_rules:
            title = r.get("title", "Policy")
            directive = r.get("prompt_directive", "").strip()
            ttype = r.get("trigger_type", "on_intent")
            if directive:
                rules_text.append(f"  • [{title} - Type: {ttype}]: {directive}")
        sections.append("\n" + "\n".join(rules_text))

    # 3. Context Memory & Adaptive Guidelines (Layer 2 & Layer 3 State Machine Architecture)
    effective_mode = context_mode or "none"

    if effective_mode in ("adaptive", "full"):
        sections.append(
            f"\n### CONTEXT MEMORY & CONVERSATIONAL CONTINUITY (MANDATORY STATE MACHINE RULES):\n"
            f"- Tracking Mode: {effective_mode.upper()}\n"
            f"- Information to actively collect, remember, and carry across all conversation turns: {context_instructions or 'name, qualification, interested_course, experience_level'}.\n"
            f"- Mandatory Architectural Rules:\n"
            f"  1. When the Active User Session Profile Context specifies an active interested course (e.g. Finance & Accounting) or educational background (e.g. B.Com), ALL follow-up inquiries regarding fee structures, syllabus, eligibility, course duration, or placements MUST be answered specifically for that active target course/domain.\n"
            f"  2. NEVER provide generic fee lists or list all courses indiscriminately unless the user explicitly requests to compare all available programs.\n"
            f"  3. When the user introduces themselves or mentions their background (e.g. B.Com graduate), warmly acknowledge it, address them by name if provided, and tailor all advice specifically to their background.\n"
            f"  4. If the user shifts interest to another course (e.g., from Finance to HR), immediately update the focus of your response to the newly selected course."
        )

    return "\n\n".join(sections)


async def compile_client_profile(client_id: str, channel: str = "widget") -> dict:
    """
    Pre-compile a comprehensive runtime profile image for a client on a specific channel.
    Caches the result in memory and persists to MongoDB.
    """
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id})
    if not client:
        raise ValueError(f"Institution '{client_id}' not found")

    settings = client.get("settings", {})
    setup_cfg = get_setup(settings, channel)

    # Base values
    base_prompt = (
        setup_cfg.get("system_prompt")
        or settings.get("system_prompt")
        or "You are a helpful, knowledgeable, and polite AI assistant for the institution."
    )

    # Normalize menu tree
    from app.services.context_media_service import normalize_menu_tree
    menu_tree = normalize_menu_tree(settings, setup_cfg)

    # Context images
    context_images = setup_cfg.get("context_images") or settings.get("context_images") or []

    # Descriptive rules
    descriptive_rules = setup_cfg.get("descriptive_rules") or settings.get("descriptive_rules") or []

    # Context RAG settings
    context_mode = setup_cfg.get("context_mode") or settings.get("context_mode", "none")
    context_instructions = setup_cfg.get("context_instructions") or settings.get("context_instructions", "")
    raw_cap = setup_cfg.get("context_capacity") if setup_cfg.get("context_capacity") is not None else settings.get("context_capacity")
    context_capacity = int(raw_cap) if raw_cap is not None else 4

    # Build compiled system prompt
    compiled_prompt = _build_compiled_system_prompt(
        base_prompt=base_prompt,
        menu_tree=menu_tree,
        context_images=context_images,
        descriptive_rules=descriptive_rules,
        context_mode=context_mode,
        context_instructions=context_instructions,
    )

    # Build O(1) flattened menu index
    menu_index: dict[str, dict] = {}
    _flatten_menu_tree(menu_tree, menu_index)

    # Build MenuGraph (new node model) — from explicit config or legacy bridge
    from app.core.menu_graph import MenuGraph
    menu_graph_nodes_raw = (
        setup_cfg.get("menu_graph_nodes")
        or settings.get("menu_graph_nodes")
        or []
    )
    menu_graph_root_id = (
        setup_cfg.get("menu_graph_root_node_id")
        or settings.get("menu_graph_root_node_id")
        or ""
    )

    menu_graph = MenuGraph.from_config(menu_graph_nodes_raw, root_node_id=menu_graph_root_id) if menu_graph_nodes_raw else MenuGraph()

    # Generate version hash
    hash_payload = json.dumps({
        "prompt": compiled_prompt,
        "menu_count": len(menu_tree),
        "graph_node_count": menu_graph.node_count,
        "image_count": len(context_images),
        "rule_count": len(descriptive_rules),
        "mode": context_mode,
    }, sort_keys=True)
    version_hash = hashlib.sha256(hash_payload.encode()).hexdigest()[:12]

    compiled_profile = {
        "client_id": client_id,
        "channel": channel,
        "version_hash": version_hash,
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "compiled_system_prompt": compiled_prompt,
        "welcome_message": settings.get("welcome_message", "Hello! How can I help you today?"),
        "theme_color": settings.get("theme_color", "#1E40AF"),
        "chatbot_title": settings.get("chatbot_title", "AI Front Desk"),
        "menu_tree": menu_tree,
        "menu_index": menu_index,
        "menu_graph": menu_graph,
        "menu_graph_nodes": menu_graph_nodes_raw,
        "menu_graph_root_node_id": menu_graph_root_id or menu_graph.root_node_id,
        "context_images": context_images,
        "descriptive_rules": descriptive_rules,
        "context_config": {
            "mode": context_mode,
            "instructions": context_instructions,
            "capacity": context_capacity,
        },
    }

    # Store in memory cache
    _PROFILE_CACHE[(client_id, channel)] = compiled_profile

    # Persist in DB under settings.compiled_profiles.{channel} (serializable copy)
    try:
        db_profile = dict(compiled_profile)
        db_profile["menu_graph"] = menu_graph.to_dict()
        await db[CLIENTS].update_one(
            {"client_id": client_id},
            {"$set": {
                f"settings.compiled_profiles.{channel}": db_profile,
                "settings.last_compiled_at": datetime.now(timezone.utc),
            }}
        )
    except Exception as e:
        logger.warning("Failed to persist compiled profile in DB: %s", e)

    logger.info("Compiled runtime profile for client '%s' on channel '%s' (v:%s)", client_id, channel, version_hash)
    return compiled_profile


async def get_compiled_profile(client_id: str, channel: str = "widget") -> dict:
    """
    Retrieve pre-compiled client profile snapshot in O(1) from memory cache or DB.
    Compiles automatically on-demand if missing.
    """
    key = (client_id, channel)
    if key in _PROFILE_CACHE:
        return _PROFILE_CACHE[key]

    # Check MongoDB
    db = get_db()
    client = await db[CLIENTS].find_one({"client_id": client_id}, {"settings": 1})
    if client:
        stored = client.get("settings", {}).get("compiled_profiles", {}).get(channel)
        if stored and isinstance(stored, dict) and stored.get("version_hash"):
            from app.core.menu_graph import MenuGraph
            if not isinstance(stored.get("menu_graph"), MenuGraph):
                nodes_raw = stored.get("menu_graph_nodes") or []
                root_id = stored.get("menu_graph_root_node_id") or ""
                if nodes_raw:
                    stored["menu_graph"] = MenuGraph.from_config(nodes_raw, root_node_id=root_id)
                else:
                    stored["menu_graph"] = MenuGraph()
            _PROFILE_CACHE[key] = stored
            return stored

    # If missing in DB, compile and cache now
    return await compile_client_profile(client_id, channel)


def invalidate_client_profile(client_id: str, channel: Optional[str] = None) -> None:
    """Clear in-memory cache for a client so the next request gets a fresh compiled profile."""
    if channel:
        _PROFILE_CACHE.pop((client_id, channel), None)
    else:
        for k in list(_PROFILE_CACHE.keys()):
            if k[0] == client_id:
                _PROFILE_CACHE.pop(k, None)
    logger.debug("Invalidated compiled profile cache for client '%s'", client_id)
