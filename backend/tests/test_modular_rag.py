"""
Tests for Modular RAG Services:
  - app.services.artifacts (WhatsApp/channel UI components & inclusion texts)
  - app.services.llm_response (JSON extraction, markdown cleanup, stream filter)
  - app.services.retrieval (Contextual queries, where filters, decomposition)
  - app.services.rag_service (Central orchestrator & backward-compatible exports)
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return "asyncio"

from app.services.artifacts import (
    resolve_artifacts,
    apply_artifact_safety_nets,
    append_inclusion_content,
    build_artifact_delivery_history,
)
from app.services.llm_response import (
    parse_llm_json_response,
    clean_markdown,
    filter_thinking_stream,
    parse_json_response,
)
from app.services.retrieval import (
    build_where_filter,
)
from app.services import rag_service


# ── Artifacts Service Tests ──────────────────────────────────────────────────

async def test_artifacts_resolution_and_matching():
    sample_profile = {
        "menu_tree": [
            {"id": "MENU_ROOT", "label": "Main Menu", "descriptor_tag": "start of conversation initial greeting"},
            {"id": "FIN_MENU", "label": "Finance Programs", "descriptor_tag": "finance options"},
        ],
        "context_images": [
            {"id": "IMG_CAMPUS", "title": "Ameerpet Campus", "image_path": "https://img.example.com/campus.png"},
            {"id": "IMG_CURRICULUM", "title": "Finance Curriculum Infographic", "image_path": "https://img.example.com/finance.png"},
        ],
        "context_maps": [
            {"id": "MAP_AMEERPET", "title": "Ameerpet Metro Center", "address": "Beside Ameerpet Metro Station, Hyderabad"},
        ],
        "inclusion_texts": [
            {"id": "INC_FEES", "title": "Scholarship Link", "content": "Visit https://example.com/scholarships for 25% discount rules."},
        ],
    }

    # Match by ID
    menu, imgs, maps, incs = resolve_artifacts(["MENU_ROOT", "IMG_CAMPUS", "MAP_AMEERPET", "INC_FEES"], sample_profile)
    assert menu is not None and menu["id"] == "MENU_ROOT"
    assert len(imgs) == 1 and imgs[0]["id"] == "IMG_CAMPUS"
    assert len(maps) == 1 and maps[0]["id"] == "MAP_AMEERPET"
    assert len(incs) == 1 and incs[0]["id"] == "INC_FEES"

    # Match by title or partial string
    menu2, imgs2, maps2, incs2 = resolve_artifacts(["Finance Programs", "curriculum infographic", "ameerpet metro", "scholarship"], sample_profile)
    assert menu2 is not None and menu2["id"] == "FIN_MENU"
    assert len(imgs2) == 1 and imgs2[0]["id"] == "IMG_CURRICULUM"
    assert len(maps2) == 1 and maps2[0]["id"] == "MAP_AMEERPET"
    assert len(incs2) == 1 and incs2[0]["id"] == "INC_FEES"


async def test_artifacts_safety_net():
    sample_profile = {
        "menu_tree": [
            {"id": "MENU_ROOT", "label": "Main Menu", "descriptor_tag": "Display at start of conversation or initial greeting"},
        ],
    }

    class DummyState:
        def __init__(self):
            self.shown = set()
        def was_artifact_shown(self, art_type, art_id):
            return art_id in self.shown

    # When no menu was selected by LLM on first message / greeting:
    matched = apply_artifact_safety_nets(None, sample_profile, session_state=DummyState(), is_light=True, history=[])
    assert matched is not None
    assert matched["id"] == "MENU_ROOT"

    # If already shown, safety net doesn't duplicate
    state_shown = DummyState()
    state_shown.shown.add("MENU_ROOT")
    matched_shown = apply_artifact_safety_nets(None, sample_profile, session_state=state_shown, is_light=True, history=[])
    assert matched_shown is None


async def test_artifacts_inclusion_content_append():
    text = "Here are the program details."
    matched_inclusions = [
        {"id": "INC_1", "content": "Direct application link: https://portal.example.com"},
    ]
    updated = append_inclusion_content(text, matched_inclusions)
    assert "Direct application link: https://portal.example.com" in updated
    assert updated.startswith("Here are the program details.")

    # Does not duplicate if already present in text
    already_contains = "Here are the program details. Direct application link: https://portal.example.com"
    no_dup = append_inclusion_content(already_contains, matched_inclusions)
    assert no_dup.count("https://portal.example.com") == 1


# ── LLM Response Service Tests ───────────────────────────────────────────────

async def test_llm_response_json_parsing():
    # 1. Clean JSON
    raw1 = '{"message": "Hello there!", "send_artifacts": ["MENU_ROOT"], "context_updates": {"user_name": "Ravi"}}'
    p1 = parse_llm_json_response(raw1)
    assert p1["message"] == "Hello there!"
    assert p1["send_artifacts"] == ["MENU_ROOT"]
    assert p1["context_updates"]["user_name"] == "Ravi"

    # 2. Markdown fence with reasoning
    raw2 = """<think>Let's recommend the finance track.</think>
```json
{
  "message": "Welcome! We offer great programs.",
  "send_artifacts": ["FIN_MENU"]
}
```"""
    p2 = parse_llm_json_response(raw2)
    assert p2["message"] == "Welcome! We offer great programs."
    assert p2["send_artifacts"] == ["FIN_MENU"]

    # 3. Truncated JSON recovery
    raw3 = '{"message": "Here is the fee breakdown for CMA USA course..."'
    p3 = parse_llm_json_response(raw3)
    assert "Here is the fee breakdown" in p3["message"]


async def test_clean_markdown_strips_thinking_tags():
    raw = """<think>
Internal thought: The student wants CA coaching.
</think>
Hello! Welcome to our coaching institute."""
    cleaned = clean_markdown(raw)
    assert "<think>" not in cleaned
    assert "Internal thought" not in cleaned
    assert cleaned == "Hello! Welcome to our coaching institute."


async def test_filter_thinking_stream():
    async def sample_stream():
        chunks = ["<think>Thinking about options...", " done.</think>", "Hello ", "World!"]
        for c in chunks:
            yield c

    filtered_chunks = []
    async for item in filter_thinking_stream(sample_stream()):
        filtered_chunks.append(item)

    combined = "".join(filtered_chunks)
    assert combined == "Hello World!"
    assert "<think>" not in combined


# ── Retrieval Service Tests ──────────────────────────────────────────────────

async def test_retrieval_where_filter():
    meta = {"year": "3rd", "semester": "1", "department": None, "course": "B.Com"}
    where = build_where_filter(meta)
    assert "$and" in where
    assert {"year": {"$eq": "3rd"}} in where["$and"]
    assert {"semester": {"$eq": "1"}} in where["$and"]
    assert {"course": {"$eq": "B.Com"}} in where["$and"]

    empty_where = build_where_filter({"year": None, "semester": None})
    assert empty_where is None


# ── RAG Service Orchestrator & Backward Compatibility ────────────────────────

async def test_rag_service_exports():
    # Verify backward-compatible exports exist on rag_service
    assert hasattr(rag_service, "_parse_llm_json_response")
    assert hasattr(rag_service, "_resolve_artifacts")
    assert hasattr(rag_service, "extract_user_name")
    assert hasattr(rag_service, "query")
    assert hasattr(rag_service, "query_stream")
    assert hasattr(rag_service, "get_remaining_quota")

    # Name extraction
    assert rag_service.extract_user_name("Hi my name is Priya Sharma, interested in HR") == "Priya Sharma"
    assert rag_service.extract_user_name("I am Rahul from Hyderabad") == "Rahul"

    # Lightweight query detector
    assert rag_service._is_lightweight_query("hello") is True
    assert rag_service._is_lightweight_query("what is the fee structure for CA Inter?") is False
