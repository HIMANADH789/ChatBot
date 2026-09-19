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
    Evaluate if any menu option's descriptor_tag directive matches the current query and state context.
    Directives in descriptor_tag (e.g. "at start of conversation", "once per session", "on explicit request")
    are dynamically evaluated by the state machine and LLM evaluator.
    """
    if not menu_tree or not query:
        return None

    query_lower = query.lower().strip()
    is_start_or_greeting = (not history or len(history) <= 1) or any(
        g in query_lower for g in ("hello", "hi", "hey", "greetings", "good morning", "good afternoon", "start")
    )
    is_explicit_request = any(
        k in query_lower for k in (
            "menu", "options", "courses list", "programs list", "show options",
            "what can you do", "main menu", "list of courses", "show courses",
            "courses again", "give me list", "again"
        )
    )

    for node in menu_tree:
        tag = (node.get("descriptor_tag") or "").strip()
        node_label = (node.get("label") or "").strip()
        node_id = (node.get("id") or "").strip()
        was_shown = _was_node_shown_in_history(node_label, history) or _was_node_shown_in_history(node_id, history)

        tag_lower = tag.lower()

        # Directive 1: Start of conversation / greeting directive
        if is_start_or_greeting and any(k in tag_lower for k in ("start", "greeting", "welcome", "initial", "first turn", "first interaction", "beginning")):
            logger.info("Menu node '%s' triggered via start of conversation / greeting directive: '%s'", node_label, tag)
            return node

        # Directive 2: Explicit re-request (e.g. "can you give me list of courses again")
        if is_explicit_request and (node_label.lower() in query_lower or any(k in query_lower for k in ("course", "menu", "program", "list", "option"))):
            logger.info("Menu node '%s' triggered via explicit re-request: '%s'", node_label, query)
            return node

        # Directive 3: "Once per session" suppression rule (unless explicitly re-requested)
        if was_shown and any(k in tag_lower for k in ("once", "only once", "first time")) and not is_explicit_request:
            continue

        # Directive 4: Direct label match in query
        if node_label and len(node_label) >= 3 and node_label.lower() in query_lower:
            return node

        # Directive 5: Context / Intent tag matching
        if tag:
            # Keyword overlap check
            stop_words = {
                "when", "user", "asks", "about", "inquires", "inquiry", "info", "information",
                "display", "show", "at", "start", "of", "conversation", "or", "initial", "greeting",
                "explicitly", "give", "can", "you", "me", "is", "it", "for", "the", "a", "an", "and"
            }
            tag_words = [w for w in re.findall(r"\b\w+\b", tag_lower) if len(w) > 3 and w not in stop_words]
            query_words = set(re.findall(r"\b\w+\b", query_lower))
            overlap = sum(1 for tw in tag_words if tw in query_words)
            if overlap >= 2 or (len(tag_words) == 1 and overlap == 1):
                return node

            # LLM Evaluator for natural language prompt directives
            if len(query.split()) >= 2 and len(tag_words) > 0:
                eval_prompt = f"""You are an intelligent state machine evaluator for an educational assistant.
Evaluate whether the menu item "{node_label}" should be triggered for the current user message based on the state machine directive.

User Message: "{query}"
Session State:
- Start of conversation / greeting: {is_start_or_greeting}
- Previously shown in session: {was_shown}
- Explicit request for menu/courses list: {is_explicit_request}

State Machine Directive: "{tag}"

Respond ONLY with YES or NO:"""
                try:
                    resp = await llm.generate(eval_prompt, temperature=0.0, max_tokens=10)
                    if "yes" in resp.text.lower():
                        logger.info("Menu node '%s' matched via LLM directive evaluation", node_label)
                        return node
                except Exception as e:
                    logger.debug("Menu directive LLM evaluation failed: %s", e)

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
    Prompt directives in descriptor_tag (e.g. "at start", "once per session", "on fee inquiry")
    are dynamically evaluated by the state machine and LLM evaluator.
    """
    if not context_images or not query:
        return []

    query_lower = query.lower().strip()
    norm_query = query_lower.replace("&", "and").replace("/", " ")
    is_start_or_greeting = (not history or len(history) <= 1) or any(
        g in query_lower for g in ("hello", "hi", "hey", "greetings", "good morning", "good afternoon", "start")
    )
    is_explicit_request = any(
        k in query_lower for k in ("image", "photo", "chart", "map", "brochure", "diagram", "show", "view", "send")
    )

    matched = []

    stop_words = {
        "when", "user", "asks", "about", "inquires", "inquiry", "wants", "view",
        "image", "photo", "chart", "map", "complete", "details", "course", "courses",
        "institute", "professional", "including", "eligibility", "program", "programs",
        "coaching", "training", "academy", "overall", "what", "are", "the", "with", "at", "sv",
        "foundation", "intermediate", "advanced", "and", "or", "for", "in", "on", "of", "to",
        "is", "it", "by", "from", "an", "a", "as", "also", "can", "you", "give", "me", "tell", "us",
        "display", "show"
    }

    for img in context_images:
        path = img.get("image_path", "").strip()
        tag = (img.get("descriptor_tag") or "").strip()
        title = (img.get("title") or "").strip()

        if not path:
            continue

        was_shown = _was_image_shown_in_history(path, history) or _was_image_shown_in_history(title, history)
        tag_lower = tag.lower()

        # Directive 1: "Once per session" suppression rule (unless explicitly requested)
        if was_shown and any(k in tag_lower for k in ("once", "only once", "first time")) and not is_explicit_request:
            continue

        # Directive 2: Start of conversation directive
        if is_start_or_greeting and any(k in tag_lower for k in ("start", "greeting", "welcome", "initial", "first turn", "beginning")):
            matched.append(img)
            continue

        # Directive 3: Direct title match in query
        norm_title = title.lower().replace("&", "and").replace("/", " ")
        if norm_title and len(norm_title) >= 2 and norm_title in norm_query:
            matched.append(img)
            continue

        # Directive 4: Descriptor tag keyword overlap
        if tag:
            norm_tag = tag_lower.replace("&", "and").replace("/", " ")
            tag_words = set(w for w in re.findall(r"\b\w+\b", norm_tag) if len(w) >= 2 and w not in stop_words)
            query_words = set(re.findall(r"\b\w+\b", norm_query))
            overlap = tag_words.intersection(query_words)
            if len(overlap) >= 1:
                matched.append(img)
                continue

            # LLM Fallback evaluator for complex image prompt directives
            if len(query.split()) >= 2:
                eval_prompt = f"""Evaluate if this image should be attached to answer the user message.
User Message: "{query}"
Session State:
- Start of conversation/greeting: {is_start_or_greeting}
- Image previously shown: {was_shown}

Image Trigger Directive: "{tag}"

Respond ONLY with YES or NO:"""
                try:
                    resp = await llm.generate(eval_prompt, temperature=0.0, max_tokens=10)
                    if "yes" in resp.text.lower():
                        matched.append(img)
                except Exception as e:
                    logger.debug("Image directive LLM evaluation failed: %s", e)

    return matched
