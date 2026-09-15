"""
Context Media Service:
Evaluates hierarchical menu trees and contextual image triggers based on
descriptor tags, conversation history, and frequency constraints.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional, Any

from app.providers.base import LLMProvider

logger = logging.getLogger(__name__)


def find_node_in_tree(nodes: list[dict], target_id_or_label: str) -> Optional[dict]:
    """Recursively search for a menu node matching an ID or label."""
    if not nodes or not target_id_or_label:
        return None
    target_clean = target_id_or_label.strip().lower()
    for node in nodes:
        node_id = str(node.get("id", "")).strip().lower()
        node_label = str(node.get("label", "")).strip().lower()
        if node_id == target_clean or node_label == target_clean:
            return node
        children = node.get("children", [])
        if children:
            found = find_node_in_tree(children, target_id_or_label)
            if found:
                return found
    return None


def is_leaf_node(node: dict) -> bool:
    """Check if node is a leaf (has no children and contains an action question)."""
    children = node.get("children", [])
    return not children or len(children) == 0


def normalize_menu_tree(settings: dict, setup_cfg: dict) -> list[dict]:
    """Retrieve menu tree with fallback to legacy menu_options converted into tree."""
    tree = setup_cfg.get("menu_tree") or settings.get("menu_tree") or []
    if tree:
        return tree

    # Legacy conversion: menu_options -> menu_tree
    legacy = settings.get("menu_options") or []
    converted = []
    for opt in legacy:
        opt_id = opt.get("id", "")
        opt_label = opt.get("label", "")
        children = []
        for sub in opt.get("submenus", []):
            sub_id = sub.get("id", "")
            sub_label = sub.get("label", "")
            sub_qs = sub.get("sub_questions", [])
            q_children = [
                {
                    "id": f"{sub_id}_q_{i}",
                    "label": q[:40],
                    "description": "",
                    "descriptor_tag": "",
                    "frequency": "on_intent",
                    "action_question": q,
                    "children": [],
                }
                for i, q in enumerate(sub_qs)
            ]
            children.append({
                "id": sub_id,
                "label": sub_label,
                "description": "",
                "descriptor_tag": "",
                "frequency": "on_intent",
                "action_question": "",
                "children": q_children,
            })
        converted.append({
            "id": opt_id,
            "label": opt_label,
            "description": "",
            "descriptor_tag": f"When user inquires about {opt_label}",
            "frequency": "on_intent",
            "action_question": "",
            "children": children,
        })
    return converted


def get_context_images(settings: dict, setup_cfg: dict) -> list[dict]:
    """Retrieve context images list from setup config or settings."""
    return setup_cfg.get("context_images") or settings.get("context_images") or []


def _was_node_shown_in_history(node_id_or_label: str, history: list) -> bool:
    """Check if a menu node or label was already shown in the session history."""
    if not history:
        return False
    target = node_id_or_label.lower()
    for msg in history:
        content = str(msg.get("content", "")).lower()
        if target in content:
            return True
    return False


def _was_image_shown_in_history(image_id_or_path: str, history: list) -> bool:
    """Check if an image path was already sent in the session history."""
    if not history:
        return False
    target = image_id_or_path.lower()
    for msg in history:
        content = str(msg.get("content", "")).lower()
        if target in content:
            return True
    return False


async def evaluate_menu_triggers(
    query: str,
    menu_tree: list[dict],
    history: list,
    llm: LLMProvider,
) -> Optional[dict]:
    """
    Evaluate if any root menu option's descriptor_tag matches the query/context.
    Enforces frequency ('only_once' | 'always' | 'on_intent').
    """
    if not menu_tree or not query:
        return None

    query_lower = query.lower()

    # If user explicitly asks for menus or options
    explicit_request = any(k in query_lower for k in ("menu", "options", "courses list", "programs list", "show options", "what can you do", "main menu"))

    for node in menu_tree:
        tag = (node.get("descriptor_tag") or "").strip()
        node_label = node.get("label", "")
        node_id = node.get("id", "")
        freq = node.get("frequency", "on_intent")

        # Frequency check: only_once
        if freq == "only_once" and not explicit_request:
            if _was_node_shown_in_history(node_label, history) or _was_node_shown_in_history(node_id, history):
                continue

        # Fast direct match on label
        if node_label.lower() in query_lower:
            return node

        # If descriptor tag is defined, evaluate match
        if tag:
            # Simple keyword overlap heuristic first to save LLM tokens
            tag_words = [w for w in re.findall(r"\b\w+\b", tag.lower()) if len(w) > 3 and w not in ("when", "user", "asks", "about", "inquires", "inquiry", "info", "information")]
            query_words = set(re.findall(r"\b\w+\b", query_lower))
            overlap = sum(1 for tw in tag_words if tw in query_words)
            if overlap >= 2 or (len(tag_words) == 1 and overlap == 1):
                return node

            # If uncertain but query is a substantial inquiry, use LLM for precision
            if len(query.split()) >= 3 and len(tag_words) > 0:
                eval_prompt = f"""You are a intent matching assistant for an educational institution.
Evaluate if the user inquiry matches the menu trigger condition.

User inquiry: "{query}"
Trigger Condition: "{tag}"

Respond ONLY with YES or NO:"""
                try:
                    resp = await llm.generate(eval_prompt, temperature=0.0, max_tokens=10)
                    if "yes" in resp.text.lower():
                        return node
                except Exception as e:
                    logger.debug("Menu descriptor eval failed: %s", e)

    return None


async def evaluate_image_triggers(
    query: str,
    context: str,
    context_images: list[dict],
    history: list,
    llm: LLMProvider,
) -> list[dict]:
    """
    Evaluate if any configured contextual image should be triggered for this turn.
    Enforces frequency ('only_once' | 'always' | 'on_intent').
    """
    if not context_images or not query:
        return []

    query_lower = query.lower()
    norm_query = query_lower.replace("&", "and").replace("/", " ")
    matched = []

    stop_words = {
        "when", "user", "asks", "about", "inquires", "inquiry", "wants", "view",
        "image", "photo", "chart", "map", "complete", "details", "course", "courses",
        "institute", "professional", "including", "eligibility", "program", "programs",
        "coaching", "training", "academy", "overall", "what", "are", "the", "with", "at", "sv",
        "foundation", "intermediate", "advanced", "and", "or", "for", "in", "on", "of", "to",
        "is", "it", "by", "from", "an", "a", "as", "also", "can", "you", "give", "me", "tell", "us"
    }

    for img in context_images:
        path = img.get("image_path", "").strip()
        tag = (img.get("descriptor_tag") or "").strip()
        title = (img.get("title") or "").strip()
        freq = img.get("frequency", "on_intent")

        if not path:
            continue

        # Frequency check: only_once
        if freq == "only_once":
            if _was_image_shown_in_history(path, history) or _was_image_shown_in_history(title, history):
                continue

        # 1. Direct title check with normalization
        norm_title = title.lower().replace("&", "and").replace("/", " ")
        if norm_title and len(norm_title) >= 2 and norm_title in norm_query:
            matched.append(img)
            continue

        # 2. Descriptor tag match
        if tag:
            norm_tag = tag.lower().replace("&", "and").replace("/", " ")
            tag_words = set(w for w in re.findall(r"\b\w+\b", norm_tag) if len(w) >= 2 and w not in stop_words)
            query_words = set(re.findall(r"\b\w+\b", norm_query))
            overlap = tag_words.intersection(query_words)
            if len(overlap) >= 1:
                matched.append(img)
                continue

            # LLM Fallback check if tag is complex
            if len(query.split()) >= 3:
                eval_prompt = f"""Evaluate if this image should be attached to answer the user's question.
User question: "{query}"
Image trigger condition: "{tag}"

Respond ONLY with YES or NO:"""
                try:
                    resp = await llm.generate(eval_prompt, temperature=0.0, max_tokens=10)
                    if "yes" in resp.text.lower():
                        matched.append(img)
                except Exception as e:
                    logger.debug("Image descriptor eval failed: %s", e)

    return matched
