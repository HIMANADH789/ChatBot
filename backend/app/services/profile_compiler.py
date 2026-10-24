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
    context_maps: list[dict],
    descriptive_rules: list[dict],
    context_mode: str,
    context_instructions: str,
    inclusion_texts: Optional[list[dict]] = None,
) -> str:
    """
    Compile a unified system prompt that:
    1. Sets the assistant persona (base_prompt from client config)
    2. Lists ALL available artifacts (menus, images, maps, inclusion texts) as a catalog
       with IDs and descriptions so the LLM can decide when to attach them
    3. Instructs the LLM to return structured JSON: {message, send_artifacts, context_updates}
    4. Includes context memory rules
    """
    sections = [base_prompt.strip()]

    # ── Artifact Catalog ──────────────────────────────────────────────────
    catalog_lines = []

    if menu_tree:
        catalog_lines.append("## MENUS (Interactive option lists)")
        for node in menu_tree:
            node_id = node.get("id") or node.get("node_id") or ""
            lbl = node.get("label") or node.get("title") or ""
            tag = node.get("descriptor_tag") or ""
            opts = node.get("options") or node.get("children") or []
            opt_labels = [o.get("button_text") or o.get("label", "") for o in opts]
            opt_str = ", ".join(opt_labels[:6]) if opt_labels else "No options"
            desc = f'When: "{tag}"' if tag else "When relevant to user query"
            catalog_lines.append(f'- ID: "{node_id}" | Title: "{lbl}" | Options: [{opt_str}] | {desc}')

    if context_images:
        catalog_lines.append("## IMAGES (Visual media attachments)")
        for img in context_images:
            title = img.get("title", "")
            tag = img.get("descriptor_tag", "")
            img_id = img.get("id") or title or img.get("image_path")
            desc = f'When: "{tag}"' if tag else "When relevant"
            catalog_lines.append(f'- ID: "{img_id}" | Title: "{title}" | {desc}')

    if context_maps:
        catalog_lines.append("## MAPS (Location/address attachments)")
        for m in context_maps:
            title = m.get("title", "")
            tag = m.get("descriptor_tag", "")
            map_id = m.get("id") or title
            addr = m.get("address", "")
            desc = f'When: "{tag}"' if tag else "When user asks about location/address"
            catalog_lines.append(f'- ID: "{map_id}" | Title: "{title}" | Address: "{addr}" | {desc}')

    if inclusion_texts:
        catalog_lines.append("## INCLUSION TEXTS (Specific textual snippets, links, or notes to attach/include)")
        for inc in inclusion_texts:
            title = inc.get("title", "")
            tag = inc.get("descriptor_tag", "")
            inc_id = inc.get("id") or title
            content = inc.get("content") or inc.get("text", "")
            desc = f'When: "{tag}"' if tag else "When relevant"
            catalog_lines.append(f'- ID: "{inc_id}" | Title: "{title}" | Snippet: "{content}" | {desc}')

    if catalog_lines:
        sections.append(
            "AVAILABLE ARTIFACTS (you decide when to send these along with your message):\n"
            + "\n".join(catalog_lines)
            + "\n\n"
            "CRITICAL ARTIFACT SELECTION DIRECTIVES:\n"
            "1. First Interaction / Initial Greeting: If any artifact's description indicates it should be displayed at the start of conversation or initial greeting, you MUST include its ID in 'send_artifacts' on the first turn.\n"
            "2. User Intent & Interest Matching: When the user expresses interest in, chooses, or inquires about a specific offering, track, syllabus, brochure, location, or resource matching an artifact's 'When:' description, attach that artifact's ID in 'send_artifacts'.\n"
            "3. Delivery Frequency Control: Check the session DELIVERY HISTORY. Do NOT re-send an artifact that has already been delivered in this session on every turn unless the user explicitly asks for it again or the artifact description specifies recurring delivery.\n"
            "4. Structured Output: Always return your natural, warm conversational response in 'message' and the list of matching artifact IDs to deliver in 'send_artifacts'."
        )

    # ── Client-Configured Descriptive Trigger Policies ────────────────────
    if descriptive_rules:
        rules_text = ["CLIENT-DEFINED POLICIES:"]
        for r in descriptive_rules:
            title = r.get("title", "Policy")
            directive = r.get("prompt_directive", "").strip()
            if directive:
                rules_text.append(f"  • [{title}]: {directive}")
        sections.append("\n".join(rules_text))

    # ── Context Memory & Conversational Continuity ────────────────────────
    effective_mode = context_mode or "none"
    if effective_mode in ("adaptive", "full"):
        sections.append(
            f"### CONTEXT MEMORY (MANDATORY):\n"
            f"- Tracking Mode: {effective_mode.upper()}\n"
            f"- Actively collect and carry across turns: {context_instructions or 'name, qualification, interested_course, experience_level'}.\n"
            f"- When the user has an active interested course, answer follow-ups specifically for that course.\n"
            f"- When the user shifts interest, immediately update focus.\n"
            f"- Address user by name if known."
        )

    # ── Structured Response Format ────────────────────────────────────────
    sections.append(
        '### RESPONSE FORMAT (MANDATORY):\n'
        'You MUST respond with a JSON object. No markdown fences, no explanation outside the JSON.\n'
        '{\n'
        '  "message": "Your conversational response text here (supports markdown formatting)",\n'
        '  "send_artifacts": ["ARTIFACT_ID_1"],\n'
        '  "context_updates": {"user_name": "...", "interested_course": "..."}\n'
        '}\n\n'
        'Rules:\n'
        '- "message": REQUIRED. Your natural, warm, engaging response.\n'
        '- "send_artifacts": List of artifact IDs to attach. Use [] if none.\n'
        '- "context_updates": Any new user info extracted from the message (name, qualification, course interest, experience level). Use {} if none.\n'
        '- Output ONLY the JSON object. No preamble, no thinking tags, no explanation.'
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
    from app.services.context_media_service import normalize_menu_tree, get_context_maps, get_inclusion_texts
    menu_tree = normalize_menu_tree(settings, setup_cfg)

    # Context images, maps, and inclusion texts
    context_images = setup_cfg.get("context_images") or settings.get("context_images") or []
    context_maps = get_context_maps(settings, setup_cfg)
    inclusion_texts = get_inclusion_texts(settings, setup_cfg)

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
        context_maps=context_maps,
        descriptive_rules=descriptive_rules,
        context_mode=context_mode,
        context_instructions=context_instructions,
        inclusion_texts=inclusion_texts,
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
        "map_count": len(context_maps),
        "inclusion_count": len(inclusion_texts),
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
        "context_maps": context_maps,
        "inclusion_texts": inclusion_texts,
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
