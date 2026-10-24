"""
LLM Response Parsing and Text Sanitization Module:
Handles structured JSON extraction, think/reasoning tag stripping,
markdown normalization, and real-time streaming filters.
"""
from __future__ import annotations

import json
import logging
import re
from typing import AsyncGenerator, Dict, Any

logger = logging.getLogger(__name__)


def clean_markdown(text: str) -> str:
    """
    Cleans up raw LLM output by removing:
    - Internal think/thought/reasoning blocks (closed, unclosed, stray tags)
    - Chain-of-thought monologue headers (Qwen / DeepSeek)
    - Conflict resolution scratchpads
    - Redundant horizontal rules & excessive blank lines
    """
    if not text:
        return ""

    # 1. Remove closed <think>...</think>, <thought>...</thought>, <reasoning>...</reasoning> blocks
    text = re.sub(r"<(think|thought|reasoning)>[\s\S]*?</\1>", "", text, flags=re.IGNORECASE).strip()

    # 2. Remove unclosed <think>, <thought>, or <reasoning> blocks (e.g. max_tokens cutoff)
    if re.search(r"<(think|thought|reasoning)>", text, flags=re.IGNORECASE):
        text = re.sub(r"<(think|thought|reasoning)>[\s\S]*", "", text, flags=re.IGNORECASE).strip()

    # 3. Strip any stray closing or opening thinking tags
    text = re.sub(r"</?(think|thought|reasoning)>", "", text, flags=re.IGNORECASE).strip()

    # 4. Remove chain-of-thought / reasoning meta-monologue patterns
    thought_headers = [
        r"^Here'?s a thinking process:?[\s\S]*?(?=\n\n|\Z)",
        r"^(?:\*?\*?(?:Thinking Process|Thought Process|Internal reasoning|Chain of Thought|Reasoning Process)\*?\*?:?)[\s\S]*?(?=\n\n|\Z)",
        r"^(?:\*?\*?Conflict Resolution\*?\*?:?|Conflict:\*?|Decision:\*?|Re-reading the System Prompt:\*?|Re-reading the User Prompt:\*?)[\s\S]*?(?=\n\n|\Z)",
    ]
    for pattern in thought_headers:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE).strip()

    # 5. Filter internal conflict/reasoning debates
    if any(k in text for k in ("Conflict Resolution:", "Conflict Resolution:*", "CRITICAL OUTPUT INSTRUCTIONS", "Decision:*", "Resolution:*")):
        answer_match = re.search(r"(?:Final Answer|Answer|Response|Assistant):\s*([\s\S]+)", text, flags=re.IGNORECASE)
        if answer_match:
            text = answer_match.group(1).strip()
        else:
            paragraphs = text.split("\n\n")
            clean_paras = []
            for p in paragraphs:
                p_lower = p.lower()
                if any(bad in p_lower for bad in (
                    "conflict resolution", "system prompt", "user prompt", "rlhf",
                    "critical output instructions", "hard constraint", "specific prompt instruction",
                    "decision:*", "resolution:*", "standard constraint"
                )):
                    continue
                clean_paras.append(p)
            text = "\n\n".join(clean_paras).strip()

    # 6. Light cleanup — preserve formatting for channel-specific renderers
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_json_response(text: str) -> dict:
    """Best-effort JSON extraction from an LLM response string."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text.strip())
    except Exception:
        return {}


def parse_llm_json_response(raw_text: str) -> dict:
    """
    Parse LLM structured JSON response with multi-layer fallback:
    - Markdown code fences (```json ... ```)
    - Think/thought tags
    - Substring regex extraction
    - Partial/truncated JSON field recovery (e.g. max_token truncation)
    - Plain text fallback
    """
    text = raw_text.strip()

    # 1. Remove think/thought/reasoning blocks
    text = re.sub(r"<(think|thought|reasoning)>[\s\S]*?</\1>", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"<(think|thought|reasoning)>[\s\S]*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"</?(think|thought|reasoning)>", "", text, flags=re.IGNORECASE).strip()

    # 2. Remove markdown code fences
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.lower().startswith("json"):
            text = text[4:].strip()

    # 3. Try direct JSON parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "message" in parsed:
            return parsed
    except Exception:
        pass

    # 4. Try to find JSON object in the text
    json_match = re.search(r'\{[\s\S]*"message"\s*:\s*"[\s\S]*?\}', text)
    if json_match:
        try:
            parsed = json.loads(json_match.group())
            if isinstance(parsed, dict) and "message" in parsed:
                return parsed
        except Exception:
            pass

    # 5. Partial/Truncated JSON recovery: extract "message" directly
    msg_match = re.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if msg_match:
        try:
            extracted_msg = msg_match.group(1).encode().decode("unicode_escape", errors="ignore")
        except Exception:
            extracted_msg = msg_match.group(1).replace(r'\"', '"').replace(r'\n', '\n')

        send_arts = []
        art_match = re.search(r'"send_artifacts"\s*:\s*\[(.*?)\]', text, flags=re.DOTALL)
        if art_match:
            send_arts = [a.strip().strip('"').strip("'") for a in art_match.group(1).split(",") if a.strip()]

        if extracted_msg and len(extracted_msg.strip()) > 0:
            return {
                "message": extracted_msg.strip(),
                "send_artifacts": send_arts,
                "context_updates": {},
            }

    # 6. Fallback: treat entire text as the message
    clean_text = clean_markdown(text)
    return {
        "message": clean_text or raw_text,
        "send_artifacts": [],
        "context_updates": {},
    }


async def filter_thinking_stream(raw_stream) -> AsyncGenerator[str, None]:
    """
    Suppresses <think>...</think>, <thought>...</thought>, and <reasoning>...</reasoning> blocks
    in real-time during token streaming so internal reasoning is never emitted to the user.
    """
    in_think = False
    buffer = ""
    emitted_any = False
    think_accumulator = ""

    async for chunk in raw_stream:
        buffer += chunk

        while buffer:
            if not in_think:
                lower_buf = buffer.lower()
                think_pos = lower_buf.find("<think>")
                thought_pos = lower_buf.find("<thought>")
                reason_pos = lower_buf.find("<reasoning>")

                positions = [p for p in (think_pos, thought_pos, reason_pos) if p != -1]
                if positions:
                    first_pos = min(positions)
                    pre_text = buffer[:first_pos]
                    if pre_text:
                        if not emitted_any:
                            pre_text = re.sub(r"^Here'?s a thinking process:?\s*", "", pre_text, flags=re.IGNORECASE)
                        if pre_text:
                            emitted_any = True
                            yield pre_text

                    tag_len = 7 if (first_pos == think_pos) else (9 if first_pos == thought_pos else 11)
                    buffer = buffer[first_pos + tag_len:]
                    in_think = True
                else:
                    tag_start = buffer.rfind("<")
                    if tag_start != -1 and (len(buffer) - tag_start) <= 11 and (
                        "<think>".startswith(buffer[tag_start:].lower()) or
                        "<thought>".startswith(buffer[tag_start:].lower()) or
                        "<reasoning>".startswith(buffer[tag_start:].lower())
                    ):
                        emit_text = buffer[:tag_start]
                        buffer = buffer[tag_start:]
                        if emit_text:
                            if not emitted_any:
                                emit_text = re.sub(r"^Here'?s a thinking process:?\s*", "", emit_text, flags=re.IGNORECASE)
                            if emit_text:
                                emitted_any = True
                                yield emit_text
                        break
                    else:
                        emit_text = buffer
                        buffer = ""
                        if not emitted_any:
                            emit_text = re.sub(r"^Here'?s a thinking process:?\s*", "", emit_text, flags=re.IGNORECASE)
                        if emit_text:
                            emitted_any = True
                            yield emit_text
            else:
                lower_buf = buffer.lower()
                close_think = lower_buf.find("</think>")
                close_thought = lower_buf.find("</thought>")
                close_reason = lower_buf.find("</reasoning>")

                close_positions = [p for p in (close_think, close_thought, close_reason) if p != -1]
                if close_positions:
                    first_close = min(close_positions)
                    think_accumulator += buffer[:first_close]
                    tag_len = 8 if (first_close == close_think) else (10 if first_close == close_thought else 12)
                    buffer = buffer[first_close + tag_len:]
                    in_think = False
                else:
                    close_tag_start = buffer.rfind("<")
                    if close_tag_start != -1 and (len(buffer) - close_tag_start) <= 12 and (
                        "</think>".startswith(buffer[close_tag_start:].lower()) or
                        "</thought>".startswith(buffer[close_tag_start:].lower()) or
                        "</reasoning>".startswith(buffer[close_tag_start:].lower())
                    ):
                        think_accumulator += buffer[:close_tag_start]
                        buffer = buffer[close_tag_start:]
                        break
                    else:
                        think_accumulator += buffer
                        buffer = ""

    if not emitted_any:
        fallback_text = clean_markdown(think_accumulator or buffer)
        if fallback_text:
            yield fallback_text


# Backward compatibility aliases
_clean_markdown = clean_markdown
_parse_json_response = parse_json_response
_parse_llm_json_response = parse_llm_json_response
_filter_thinking_stream = filter_thinking_stream
