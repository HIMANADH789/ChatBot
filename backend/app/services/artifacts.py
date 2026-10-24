"""
WhatsApp and Channel Artifact Components Module:
Handles generic resolution, matching, safety nets, delivery tracking,
and content injection for UI artifact components:
  1. Menus (interactive button/list options)
  2. Context Images (media cards)
  3. Context Maps (location / address cards)
  4. Inclusion Texts (specific snippets, links, or notes)
"""
from __future__ import annotations

import logging
from typing import Optional, Any, NamedTuple

logger = logging.getLogger(__name__)


class ResolvedArtifacts(NamedTuple):
    menu: Optional[dict]
    images: list[dict]
    maps: list[dict]
    inclusions: list[dict]

    def to_dict(self) -> dict:
        return {
            "interactive_menu": self.menu,
            "context_images": self.images,
            "context_maps": self.maps,
            "inclusion_texts": self.inclusions,
        }


def build_artifact_delivery_history(session_state: Any) -> str:
    """Build a summary of which artifacts have already been sent this session."""
    if not session_state or not hasattr(session_state, "state_flags"):
        return "None sent yet."
    lines = []
    for key, ids in session_state.state_flags.items():
        if key.startswith("shown_") and isinstance(ids, list) and ids:
            artifact_type = key.replace("shown_", "").title()
            lines.append(f"  {artifact_type}: {', '.join(str(i) for i in ids)}")
    return "\n".join(lines) if lines else "None sent yet."


def resolve_artifacts(artifact_ids: list, profile: dict) -> tuple[Optional[dict], list[dict], list[dict], list[dict]]:
    """
    Resolve artifact IDs from the LLM response into actual artifact component data objects.
    Matches across menus, images, maps, and inclusion texts using ID, title/label, or path.
    """
    if not artifact_ids:
        return None, [], [], []

    matched_menu = None
    matched_images: list[dict] = []
    matched_maps: list[dict] = []
    matched_inclusions: list[dict] = []

    menu_tree = profile.get("menu_tree", [])
    context_images = profile.get("context_images", [])
    context_maps = profile.get("context_maps", [])
    inclusion_texts = profile.get("inclusion_texts", [])

    for aid in artifact_ids:
        aid_lower = str(aid).lower().strip().strip('"').strip("'")
        if not aid_lower:
            continue

        # 1. Menus: match by component id or title/label
        for node in menu_tree:
            node_id = str(node.get("id") or node.get("node_id") or "").lower()
            node_label = str(node.get("label") or node.get("title") or "").lower()
            if aid_lower in (node_id, node_label) or (
                len(aid_lower) > 3 and (aid_lower in node_id or aid_lower in node_label or (len(node_label) > 3 and node_label in aid_lower))
            ):
                if matched_menu is None:
                    matched_menu = node
                break

        # 2. Context Images: match by component id, title, or image path
        for img in context_images:
            img_path = str(img.get("image_path", "")).lower()
            img_title = str(img.get("title", "")).lower()
            img_id = str(img.get("id", "")).lower()
            matched = False
            if aid_lower in (img_id, img_title, img_path):
                matched = True
            elif len(aid_lower) >= 3 and (aid_lower in img_id or aid_lower in img_title or aid_lower in img_path):
                matched = True
            elif len(img_id) >= 3 and img_id in aid_lower:
                matched = True
            elif len(img_title) >= 3 and img_title in aid_lower:
                matched = True

            if matched:
                if img not in matched_images:
                    matched_images.append(img)
                break

        # 3. Context Maps: match by component id or title
        for m in context_maps:
            map_id = str(m.get("id") or m.get("title") or "").lower()
            map_title = str(m.get("title", "")).lower()
            if aid_lower in (map_id, map_title) or (len(aid_lower) > 3 and (aid_lower in map_id or aid_lower in map_title)):
                if m not in matched_maps:
                    matched_maps.append(m)
                break

        # 4. Inclusion Texts: match by component id or title
        for inc in inclusion_texts:
            inc_id = str(inc.get("id") or inc.get("title") or "").lower()
            inc_title = str(inc.get("title", "")).lower()
            if aid_lower in (inc_id, inc_title) or (len(aid_lower) > 3 and (aid_lower in inc_id or aid_lower in inc_title)):
                if inc not in matched_inclusions:
                    matched_inclusions.append(inc)
                break

    return matched_menu, matched_images, matched_maps, matched_inclusions


def apply_artifact_safety_nets(
    matched_menu: Optional[dict],
    profile: dict,
    session_state: Any = None,
    is_light: bool = False,
    history: list | None = None,
) -> Optional[dict]:
    """
    Description-driven fallback for root navigation:
    If no menu was selected by the LLM, but this is an initial greeting or first interaction,
    check if any menu node's descriptor_tag specifies display at the start of conversation.
    If not yet shown in the session, activate it.
    """
    if matched_menu is not None:
        return matched_menu

    if is_light or not history:
        for node in profile.get("menu_tree", []):
            desc = (node.get("descriptor_tag") or "").lower()
            if any(k in desc for k in ("start of conversation", "initial greeting", "first message", "first interaction", "first chat", "mandatory")):
                m_id = str(node.get("id") or node.get("node_id") or "")
                if session_state and not session_state.was_artifact_shown("menu", m_id):
                    return node
                elif not session_state:
                    return node

    return None


def append_inclusion_content(text: str, matched_inclusions: list[dict]) -> str:
    """
    Ensures snippet content from selected inclusion texts is attached to the response
    if not already seamlessly incorporated into the message.
    """
    if not matched_inclusions or not text:
        return text

    updated_text = text
    for inc in matched_inclusions:
        inc_content = inc.get("content") or inc.get("text", "")
        if inc_content and inc_content.lower() not in updated_text.lower():
            updated_text = f"{updated_text}\n\n{inc_content}".strip()

    return updated_text


# Backward compatibility aliases
_resolve_artifacts = resolve_artifacts
_build_artifact_delivery_history = build_artifact_delivery_history
_apply_artifact_safety_nets = apply_artifact_safety_nets
