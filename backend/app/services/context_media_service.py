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


def get_context_maps(settings: dict, setup_cfg: dict) -> list[dict]:
    """Retrieve context maps/locations list from setup config or settings."""
    return setup_cfg.get("context_maps") or settings.get("context_maps") or []


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


def _was_map_shown_in_history(map_id_or_title: str, history: list) -> bool:
    """Check if a map/location was already sent in the session history."""
    if not history or not map_id_or_title:
        return False
    target = map_id_or_title.lower().strip()
    for msg in history:
        msg_maps = msg.get("maps") or msg.get("context_maps") or []
        for m in msg_maps:
            if isinstance(m, dict):
                m_title = str(m.get("title") or m.get("id", "")).lower()
                if target in m_title:
                    return True
        content = str(msg.get("content", "")).lower()
        if target in content and any(k in content for k in ("map", "location", "address", "directions")):
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
    words = query_lower.split()
    word_count = len(words)

    # 1. Pure greeting check (e.g. "hi", "hello", "good morning", "hey") without detailed query
    greeting_words = {"hello", "hi", "hey", "greetings", "good morning", "good afternoon", "good evening", "/start", "start", "welcome"}
    has_greeting_keyword = any(g in query_lower for g in greeting_words)
    is_pure_greeting = (word_count <= 4 and has_greeting_keyword)

    # 2. Explicit menu or course list request
    is_explicit_request = any(
        k in query_lower for k in (
            "show menu", "main menu", "menu", "options", "courses list", "programs list", "show options",
            "what can you do", "list of courses", "show courses", "courses again", "give me list",
            "course menu", "courses offered", "programs offered", "show all courses"
        )
    )

    # 3. Specific factual query / detailed inquiry check (suppresses generic menu override)
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

    # 4. Detailed educational / career background inquiry (e.g. "I am Tanishka I did MBA in Cambridge...")
    is_detailed_profile_inquiry = (
        word_count > 4 and (
            any(k in query_lower for k in (
                "mba", "bcom", "b.com", "mcom", "m.com", "bba", "engineering", "graduate",
                "years of work", "years of experience", "work in", "worked in", "amazon",
                "skills", "career", "higher positions", "uplevel", "upgrade", "recommend"
            )) or any(k in query_lower for k in ("can you tell me courses", "tell me courses", "which course", "what course"))
        )
    )

    # Do not trigger generic menu override if user is asking a specific factual query or detailed profile inquiry
    if (is_specific_factual_query or is_detailed_profile_inquiry) and not is_explicit_request:
        logger.debug("Suppressing menu trigger for detailed inquiry/factual query: %s", query)
        return None

    # Pure greeting / explicit menu request -> deliver root menu if available
    if (is_pure_greeting or is_explicit_request) and menu_tree:
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
        if is_pure_greeting and any(k in tag_lower for k in ("start", "greeting", "welcome", "initial", "first turn", "first interaction", "beginning")):
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
    context_variables: Optional[dict] = None,
) -> list[dict]:
    """
    Evaluate if any configured contextual image should be triggered for this turn.
    Prompt directives in descriptor_tag (e.g. "at start", "once per session", "on fee inquiry")
    and dynamic session context variables (e.g. interested_course) are evaluated.
    """
    if not context_images or not query:
        return []

    query_lower = query.lower().strip()
    norm_query = query_lower.replace("&", "and").replace("/", " ")
    is_start_or_greeting = (not history or len(history) <= 1) or any(
        g in query_lower for g in ("hello", "hi", "hey", "greetings", "good morning", "good afternoon", "start")
    )
    is_explicit_request = any(
        k in query_lower for k in ("image", "photo", "chart", "picture", "brochure", "diagram", "show", "view", "send")
    )

    active_course = ""
    if context_variables:
        active_course = (
            context_variables.get("interested_course")
            or context_variables.get("target_course")
            or ""
        ).lower()

    matched = []
    seen_paths = set()

    stop_words = {
        "when", "user", "asks", "about", "inquires", "inquiry", "wants", "view",
        "image", "photo", "chart", "map", "complete", "details", "course", "courses",
        "institute", "professional", "including", "eligibility", "program", "programs",
        "coaching", "training", "academy", "overall", "what", "are", "the", "with", "at", "sv",
        "and", "or", "for", "in", "on", "of", "to",
        "is", "it", "by", "from", "an", "a", "as", "also", "can", "you", "give", "me", "tell", "us",
        "display", "show", "fee", "fees", "cost", "price", "installment", "structure",
        "syllabus", "duration", "overview", "curriculum", "placement", "brochure", "info", "information"
    }

    for img in context_images:
        path = img.get("image_path", "").strip()
        tag = (img.get("descriptor_tag") or "").strip()
        title = (img.get("title") or "").strip()

        if not path or path in seen_paths:
            continue

        was_shown = _was_image_shown_in_history(path, history) or _was_image_shown_in_history(title, history)
        tag_lower = tag.lower()

        # Directive 1: Already-shown suppression rule (unless explicitly requested)
        if was_shown and not is_explicit_request:
            logger.debug("Skipping image '%s' because it was already sent in this session", title)
            continue

        # Directive 2: Start of conversation directive
        if is_start_or_greeting and any(k in tag_lower for k in ("start", "greeting", "welcome", "initial", "first turn", "beginning")):
            matched.append(img)
            seen_paths.add(path)
            continue

        # Directive 3: Dynamic State Machine Context Match (e.g. active interested_course)
        # If user asks a follow-up (fees, syllabus, duration, brochure) and session has active interested_course
        is_followup = any(k in query_lower for k in (
            "fee", "fees", "cost", "syllabus", "duration", "eligibility", "structure",
            "brochure", "details", "overview", "curriculum", "placement", "timing", "batch"
        ))
        if active_course and is_followup:
            if any(k in active_course for k in ("finance", "accounting", "f&a")) and any(k in title.lower() or k in tag_lower for k in ("finance", "accounting", "f&a")):
                matched.append(img)
                seen_paths.add(path)
                continue
            elif any(k in active_course for k in ("hr", "human resources")) and any(k in title.lower() or k in tag_lower for k in ("hr", "human resources")):
                matched.append(img)
                seen_paths.add(path)
                continue
            elif any(k in active_course for k in ("ca", "commerce")) and any(k in title.lower() or k in tag_lower for k in ("ca", "commerce")):
                matched.append(img)
                seen_paths.add(path)
                continue
            else:
                # Active course is set and user is asking a generic followup, but this image belongs to a different domain
                # and user didn't explicitly query this domain -> skip this image
                img_is_fa = any(k in title.lower() or k in tag_lower for k in ("finance", "accounting", "f&a"))
                img_is_hr = any(k in title.lower() or k in tag_lower for k in ("hr", "human resources"))
                img_is_ca = any(k in title.lower() or k in tag_lower for k in ("ca", "commerce"))
                user_asked_fa = any(k in query_lower for k in ("finance", "accounting", "f&a", "f and a"))
                user_asked_hr = any(k in query_lower for k in ("hr", "human resources"))
                user_asked_ca = any(k in query_lower for k in ("ca", "commerce"))
                if (img_is_fa and not user_asked_fa) or (img_is_hr and not user_asked_hr) or (img_is_ca and not user_asked_ca):
                    continue

        # Directive 4: Abbreviation & Course Keyword Matching in query (F&A, Finance, Accounting, HR, CA)
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
            seen_paths.add(path)
            continue

        # Directive 5: Direct title match in query (bidirectional)
        norm_title = title.lower().replace("&", "and").replace("/", " ")
        if norm_title and len(norm_title) >= 2:
            if norm_title in norm_query or (len(norm_query) >= 3 and norm_query in norm_title):
                matched.append(img)
                seen_paths.add(path)
                continue

        # Directive 6: Descriptor tag keyword overlap
        if tag:
            norm_tag = tag_lower.replace("&", "and").replace("/", " ")
            tag_words = set(w for w in re.findall(r"\b\w+\b", norm_tag) if len(w) >= 2 and w not in stop_words)
            query_words = set(re.findall(r"\b\w+\b", norm_query))
            overlap = tag_words.intersection(query_words)
            if len(overlap) >= 1:
                matched.append(img)
                seen_paths.add(path)
                continue

            # LLM Fallback evaluator for complex image prompt directives
            if len(query.split()) >= 2:
                eval_prompt = f"""Evaluate if this image should be attached to answer the user message.
User Message: "{query}"
Active User Course Context: "{active_course}"
Session State:
- Start of conversation/greeting: {is_start_or_greeting}
- Image previously shown: {was_shown}

Image Trigger Directive: "{tag}"

Respond ONLY with YES or NO:"""
                try:
                    resp = await llm.generate(eval_prompt, temperature=0.0, max_tokens=10)
                    if "yes" in resp.text.lower():
                        matched.append(img)
                        seen_paths.add(path)
                except Exception as e:
                    logger.debug("Image directive LLM evaluation failed: %s", e)

    return matched


async def evaluate_map_triggers(
    query: str,
    context: str,
    context_maps: list[dict],
    history: list,
    llm: LLMProvider,
    context_variables: Optional[dict] = None,
) -> list[dict]:
    """
    Evaluate if any configured location/map should be attached for this turn.
    Triggered when user asks about location, campus address, directions, how to reach/visit,
    or matches map descriptor tags.
    """
    if not context_maps or not query:
        return []

    query_lower = query.lower().strip()
    is_first_chat = not history or len(history) <= 1
    is_explicit_location_query = any(k in query_lower for k in (
        "location", "address", "where is", "where are you", "where located",
        "how to reach", "directions", "map", "campus", "how to visit",
        "visit", "office address", "branch address", "venue", "google map"
    ))
    is_explicit_request = any(k in query_lower for k in ("map", "location", "address", "directions"))

    matched = []
    seen_ids = set()

    for m in context_maps:
        map_id = str(m.get("id") or m.get("title", "")).strip()
        tag = (m.get("descriptor_tag") or "").strip()
        title = (m.get("title") or "").strip()
        address = (m.get("address") or "").strip()

        if not map_id or map_id in seen_ids:
            continue

        was_shown = _was_map_shown_in_history(map_id, history) or _was_map_shown_in_history(title, history)

        # Directive 1: Already-shown suppression rule (unless explicitly re-requested)
        if was_shown and not is_explicit_request:
            continue

        tag_lower = tag.lower()

        # Directive 2: First chat / initial greeting directive
        if is_first_chat and any(k in tag_lower for k in ("first chat", "first turn", "start", "initial", "greeting", "welcome")):
            matched.append(m)
            seen_ids.add(map_id)
            continue

        # Directive 3: Explicit location / address query
        if is_explicit_location_query:
            matched.append(m)
            seen_ids.add(map_id)
            continue

        # Directive 4: Descriptor tag keyword overlap
        if tag:
            stop_words = {"when", "user", "asks", "about", "show", "in", "and", "or", "for", "the", "with", "this", "that"}
            tag_words = set(w for w in re.findall(r"\b\w+\b", tag_lower) if len(w) >= 3 and w not in stop_words)
            query_words = set(re.findall(r"\b\w+\b", query_lower))
            if len(tag_words.intersection(query_words)) >= 2 or (len(tag_words) == 1 and len(tag_words.intersection(query_words)) == 1):
                matched.append(m)
                seen_ids.add(map_id)
                continue

    return matched
