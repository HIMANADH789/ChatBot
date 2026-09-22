"""
WhatsApp Text Formatter

Converts LLM output into WhatsApp-optimized rich text using WhatsApp's
native formatting syntax:
  *bold*     → Bold text
  _italic_   → Italic text
  ~strike~   → Strikethrough

Also adds subtle, contextual emojis to section headings for visual readability
without cluttering the message. Designed for mobile-first readability.
"""
from __future__ import annotations
import re


# ── Heading Emoji Map ────────────────────────────────────────────────────────
# Maps common section heading keywords to subtle, relevant emojis.
# Only the FIRST matching keyword in a heading triggers an emoji.
HEADING_EMOJI_MAP = {
    # Programs / Courses
    "course": "📚",
    "courses": "📚",
    "program": "📚",
    "programs": "📚",
    "training": "📚",
    "curriculum": "📚",
    "syllabus": "📖",
    "modules": "📖",
    "subjects": "📖",
    "topics": "📖",
    # Specific domains
    "finance": "💰",
    "accounting": "💰",
    "f&a": "💰",
    "human resources": "👥",
    "hr": "👥",
    "sap": "🖥️",
    # Eligibility & Admission
    "eligibility": "✅",
    "eligible": "✅",
    "criteria": "✅",
    "requirement": "📋",
    "requirements": "📋",
    "admission": "🎓",
    "admissions": "🎓",
    "how to apply": "📝",
    "apply": "📝",
    "registration": "📝",
    "enroll": "📝",
    "enrollment": "📝",
    # Fees & Duration
    "fee": "💳",
    "fees": "💳",
    "fee structure": "💳",
    "cost": "💳",
    "price": "💳",
    "payment": "💳",
    "installment": "💳",
    "duration": "⏱️",
    "timing": "⏱️",
    "schedule": "📅",
    "batch": "📅",
    "batches": "📅",
    "dates": "📅",
    # Placement & Career
    "placement": "🏢",
    "placements": "🏢",
    "career": "🚀",
    "careers": "🚀",
    "job": "💼",
    "jobs": "💼",
    "opportunities": "🌟",
    "opportunity": "🌟",
    "companies": "🏢",
    "recruiters": "🏢",
    "salary": "💵",
    "package": "💵",
    # Content sections
    "overview": "📋",
    "highlights": "✨",
    "key topics": "📌",
    "key features": "📌",
    "features": "📌",
    "benefits": "🌟",
    "advantage": "🌟",
    "advantages": "🌟",
    "what you learn": "📖",
    "learning": "📖",
    "skills": "🛠️",
    # Contact & Location
    "contact": "📞",
    "address": "📍",
    "location": "📍",
    "campus": "🏛️",
    # Welcome & General
    "welcome": "👋",
    "about": "ℹ️",
    "about us": "ℹ️",
    "introduction": "👋",
    "available": "📋",
    # Certification
    "certificate": "🏆",
    "certification": "🏆",
    "demo": "🎯",
    "demo class": "🎯",
    "free demo": "🎯",
}


def _get_heading_emoji(heading_text: str) -> str:
    """Return a contextual emoji for a heading, or empty string if no match."""
    heading_lower = heading_text.lower().strip()
    # Try longest match first (multi-word keys)
    sorted_keys = sorted(HEADING_EMOJI_MAP.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if key in heading_lower:
            return HEADING_EMOJI_MAP[key]
    return ""


def format_for_whatsapp(text: str) -> str:
    """
    Transform LLM-generated text into WhatsApp-optimized rich formatting.

    Transformations applied:
    1. Markdown headings (## Heading) → *🏢 Heading* (bold + emoji)
    2. Standalone section titles & lines ending with ':' → *emoji Section Title:*
    3. Markdown bold (**text** or __text__) → *text* (WhatsApp bold)
    4. Bullet labels (• Label: value) → • *Label:* value
    5. Bullet normalization: -, *, • → • (clean bullet) and sub-bullets ◦
    6. Code backticks: stripped (not supported in WhatsApp)
    7. Horizontal rules (---) → removed
    8. Excessive newlines → condensed
    """
    if not text:
        return ""

    lines = text.split("\n")
    formatted_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            formatted_lines.append("")
            continue

        # Skip horizontal rules
        if re.match(r"^[-*_]{3,}\s*$", stripped):
            continue

        # ── Heading conversion (# Heading → *emoji Heading*) ───────────
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            heading_text = heading_match.group(2).strip()
            heading_text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", heading_text)
            emoji = _get_heading_emoji(heading_text)
            if emoji:
                formatted_lines.append(f"*{emoji} {heading_text}*")
            else:
                formatted_lines.append(f"*{heading_text}*")
            continue

        # ── Bold line detection (standalone bold heading-like text) ─────
        bold_line_match = re.match(r"^\*{1,2}([^*]+)\*{1,2}$", stripped)
        if bold_line_match:
            inner = bold_line_match.group(1).strip()
            emoji = _get_heading_emoji(inner)
            if emoji:
                formatted_lines.append(f"*{emoji} {inner}*")
            else:
                formatted_lines.append(f"*{inner}*")
            continue

        # ── Standalone Section Heading Detection ──────────────────────────
        # Short lines (<= 50 chars) ending with ':' or looking like major title section labels
        title_colon_match = re.match(r"^([A-Z0-9\s&/\-()]{2,45}):$", stripped, re.IGNORECASE)
        if title_colon_match:
            title_text = title_colon_match.group(1).strip()
            emoji = _get_heading_emoji(title_text)
            prefix = f"*{emoji} " if emoji else "*"
            formatted_lines.append(f"{prefix}{title_text}:*")
            continue

        # Short title-cased or uppercase line without terminal punctuation (e.g. "Programs Available")
        if len(stripped) <= 45 and not stripped.endswith((".", "?", "!", ",", ";")) and not re.match(r"^[-*+•◦0-9]", stripped):
            if any(k in stripped.lower() for k in ("available", "overview", "program", "course", "finance", "hr", "accounting", "eligibility", "content", "welcome", "institute", "details", "features", "highlights", "placement", "fees", "contact", "about", "training", "curriculum")):
                emoji = _get_heading_emoji(stripped)
                prefix = f"*{emoji} " if emoji else "*"
                formatted_lines.append(f"{prefix}{stripped}*")
                continue

        # ── Inline markdown bold → WhatsApp bold ──────────────────────
        processed = re.sub(r"\*\*(.+?)\*\*", r"*\1*", stripped)
        processed = re.sub(r"__(.+?)__", r"*\1*", processed)

        # ── Strip backtick code markers ───────────────────────────────
        processed = re.sub(r"`(.+?)`", r"\1", processed)

        # ── Bullet normalization & Label Bolding ─────────────────────
        bullet_match = re.match(r"^(\s*)([-*+•◦])\s+(.+)$", processed)
        if bullet_match:
            indent = bullet_match.group(1)
            content = bullet_match.group(3).strip()

            # Format bullet key-value labels: e.g. "Eligibility: Graduated..." -> "*Eligibility:* Graduated..."
            label_match = re.match(r"^([A-Za-z0-9\s&/\-()]{2,30}:)(.+)$", content)
            if label_match and not content.startswith("*"):
                lbl = label_match.group(1).strip()
                rest = label_match.group(2).strip()
                sub_emoji = _get_heading_emoji(lbl)
                lbl_str = f"*{sub_emoji} {lbl}*" if sub_emoji else f"*{lbl}*"
                content = f"{lbl_str} {rest}"

            # Sub-bullets (indented) use ◦, main bullets use •
            if len(indent) >= 2:
                processed = f"  ◦ {content}"
            else:
                processed = f"• {content}"

        formatted_lines.append(processed)

    result = "\n".join(formatted_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def strip_formatting(text: str) -> str:
    """
    Remove all formatting from text (for web/generic channels).
    This is a plain-text converter for channels that don't support rich text.
    """
    if not text:
        return ""
    # Remove markdown headers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,2}(.+?)_{1,2}", r"\1", text)
    # Remove backticks
    text = re.sub(r"`(.+?)`", r"\1", text)
    # Remove horizontal rules
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    # Condense newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
