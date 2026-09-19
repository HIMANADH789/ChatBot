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
    """Retrieve menu structure with priority to MenuGraph nodes over legacy trees."""
    graph_nodes = setup_cfg.get("menu_graph_nodes") or settings.get("menu_graph_nodes") or []
    if graph_nodes:
        tree = []
        for g_node in graph_nodes:
            opts = g_node.get("options", [])
            children = [
                {
                    "id": opt.get("target_id") or opt.get("option_number") or f"opt_{i}",
                    "label": opt.get("button_text") or opt.get("label", ""),
                    "description": "",
                    "descriptor_tag": "",
                    "action_question": opt.get("rag_prompt") or "",
                    "target_type": opt.get("target_type") or "TRIGGER_RAG",
                    "children": [],
                }
                for i, opt in enumerate(opts)
            ]
            tree.append({
                "id": g_node.get("node_id", ""),
                "node_id": g_node.get("node_id", ""),
                "label": g_node.get("title", ""),
                "title": g_node.get("title", ""),
                "description": g_node.get("whatsapp_media", {}).get("caption", "") or f"Options for {g_node.get('title')}",
                "descriptor_tag": g_node.get("descriptor_tag", ""),
                "frequency": g_node.get("frequency", "on_intent"),
                "options": opts,
                "children": children,
                "whatsapp_media": g_node.get("whatsapp_media", {}),
            })
        return tree
    return []


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
    if not history or not image_id_or_path:
        return False
    path_clean = image_id_or_path.lower().strip()
    basename = path_clean.split("/")[-1].split("\\")[-1]
    if not basename or len(basename) < 4:
        return False

    for msg in history:
        # Check explicit image metadata on stored message if present
        msg_images = msg.get("images") or msg.get("context_images") or []
        for img in msg_images:
            if isinstance(img, dict):
                img_p = str(img.get("image_path") or img.get("image_url", "")).lower()
                if path_clean in img_p or basename in img_p:
                    return True
        # Check content ONLY for explicit media link / filename tag
        content = str(msg.get("content", "")).lower()
        if (f"[image:" in content or f"/static/" in content or f"http" in content) and basename in content:
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
            "courses again", "give me list", "again", "course menu", "courses offered",
            "courses in", "what courses", "tell me about courses", "tell about courses",
            "courses", "programs offered"
        )
    )
    is_specific_factual_query = any(
        k in query_lower for k in (
            "fee", "fees", "eligibility", "syllabus", "location", "address",
            "admission process", "installment", "payment", "duration", "timing",
            "dates", "how to apply", "cost", "price", "discount", "requirement",
            "requirements", "curriculum", "subjects", "topics", "explain",
            "details of", "detail of", "overview of", "ca foundation", "ca intermediate",
            "ca final", "finance & accounting fee", "human resources fee", "hr course fee", "f&a course fee"
        )
    )

    # Do not trigger full menu navigation if user is asking a specific detailed query like fee/syllabus (unless explicitly requesting menu)
    if is_specific_factual_query and not is_explicit_request:
        logger.debug("Suppressing menu trigger for specific factual query: %s", query)
        return None

    # First turn / greeting / course inquiry -> deliver root menu if available
    if (is_start_or_greeting or is_explicit_request) and menu_tree:
        # Check if any specific node matches first
        for node in menu_tree:
            tag = (node.get("descriptor_tag") or "").strip().lower()
            if any(k in tag for k in ("start", "greeting", "welcome", "initial", "first turn", "beginning")):
                return node
        return menu_tree[0]

    for node in menu_tree:
        tag = (node.get("descriptor_tag") or "").strip()
        node_label = (node.get("label") or node.get("title") or "").strip()
        node_id = (node.get("id") or node.get("node_id") or "").strip()
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
        "and", "or", "for", "in", "on", "of", "to",
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

        # Directive 3: Abbreviation & Course Keyword Matching (F&A, Finance, Accounting, HR, CA)
        abbrev_matched = False
        if any(k in query_lower for k in ("f&a", "f and a", "finance", "accounting")):
            if any(k in title.lower() or k in tag_lower for k in ("f&a", "finance", "accounting")):
                abbrev_matched = True
        elif any(k in query_lower for k in ("hr", "human resources")):
            if any(k in title.lower() or k in tag_lower for k in ("hr", "human resources")):
                abbrev_matched = True
        elif any(k in query_lower for k in ("ca", "commerce")):
            if any(k in title.lower() or k in tag_lower for k in ("ca", "commerce")):
                abbrev_matched = True

        if abbrev_matched:
            matched.append(img)
            continue

        # Directive 4: Direct title match in query (bidirectional)
        norm_title = title.lower().replace("&", "and").replace("/", " ")
        if norm_title and len(norm_title) >= 2:
            if norm_title in norm_query or (len(norm_query) >= 3 and norm_query in norm_title):
                matched.append(img)
                continue

        # Directive 5: Descriptor tag keyword overlap
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
