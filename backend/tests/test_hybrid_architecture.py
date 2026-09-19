"""
Unit and Integration Tests for Hybrid State-Machine & RAG Architecture
"""
import asyncio
import os
import sys
from typing import Dict, Any

import pytest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return "asyncio"

from app.core.user_event import UserEvent, EventType, ActionType
from app.services.state_store import StateStore, UserSessionState
from app.services.state_machine import StateMachineRouter
from app.services.bm25_search import TenantBM25Index, reciprocal_rank_fusion
from app.core.hybrid_engine import HybridEngine


async def test_layer1_user_event_normalization():
    # Test session_id auto derivation: tenant_id:channel:user_id
    event = UserEvent(
        tenant_id="sv_institute",
        channel="whatsapp",
        user_id="+919876543210",
        payload="What are the courses offered?",
        event_type=EventType.TEXT,
    )
    assert event.session_id == "sv_institute:whatsapp:919876543210"
    assert event.tenant_id == "sv_institute"
    assert event.channel == "whatsapp"
    print("[PASS] Layer 1: UserEvent normalization passed")


async def test_layer2_state_store_and_transitions():
    store = StateStore(ttl_seconds=3600)
    
    # 1. Get or create state
    state = await store.get_state(tenant_id="tenant_1", channel="whatsapp", user_id="user_123")
    assert state.session_id == "tenant_1:whatsapp:user_123"
    assert state.current_node_id is None
    assert state.navigation_stack == []

    # 2. Node transition
    await store.transition_node(
        state=state,
        next_node_id="admissions",
        active_menu_id="admissions",
        context_updates={"qualification": "12th Commerce"},
    )
    assert state.current_node_id == "admissions"
    assert state.active_menu_id == "admissions"
    assert state.context_variables.get("qualification") == "12th Commerce"

    # 3. Sub-transition with history trail
    await store.transition_node(
        state=state,
        next_node_id="ca_foundation",
        context_updates={"interested_program": "CA Foundation"},
    )
    assert state.current_node_id == "ca_foundation"
    assert "admissions" in state.navigation_stack
    assert state.context_variables.get("interested_program") == "CA Foundation"

    # 4. Reset state
    await store.reset_state(state)
    assert state.current_node_id is None
    assert state.navigation_stack == []
    # Context variables preserved across resets
    assert state.context_variables.get("interested_program") == "CA Foundation"
    print("[PASS] Layer 2: StateStore tracking and node transitions passed")


async def test_layer2_state_machine_deterministic_routing():
    router = StateMachineRouter()
    store = StateStore()
    state = await store.get_state(tenant_id="tenant_1", channel="whatsapp", user_id="user_abc")

    from app.core.menu_graph import MenuGraph
    nodes = [
        {
            "node_id": "MENU_ROOT",
            "title": "Main Menu",
            "options": [
                {"option_number": "1", "button_text": "Our Programs", "target_type": "NAVIGATE_MENU", "target_id": "programs_menu"},
            ]
        },
        {
            "node_id": "programs_menu",
            "title": "Our Programs",
            "options": [
                {"option_number": "1", "button_text": "Chartered Accountancy (CA)", "target_type": "TRIGGER_RAG", "rag_prompt": "Provide complete information regarding CA Foundation, Inter, and Final coaching."},
                {"option_number": "2", "button_text": "Office Hours", "target_type": "DIRECT_ANSWER", "direct_answer": "Our administrative office is open Mon-Sat 9:00 AM to 6:00 PM."},
            ]
        }
    ]
    graph = MenuGraph.from_config(nodes, root_node_id="MENU_ROOT")

    mock_profile = {
        "menu_graph": graph,
        "menu_index": {},
    }

    # Test Case 1: Clicking intermediate menu node -> Immediate sub-menu with ZERO LLM
    event1 = UserEvent(
        tenant_id="tenant_1",
        channel="whatsapp",
        user_id="user_abc",
        payload="Our Programs",
        event_type=EventType.BUTTON_CLICK,
    )
    res, requires_rag, query_override = await router.evaluate_event(event1, state, mock_profile)
    assert res is not None
    assert res.is_deterministic is True
    assert res.interactive_menu is not None
    assert len(res.interactive_menu["options"]) == 2
    assert requires_rag is False

    # Test Case 2: Clicking leaf node with direct answer -> Immediate direct text with ZERO LLM
    event2 = UserEvent(
        tenant_id="tenant_1",
        channel="whatsapp",
        user_id="user_abc",
        payload="Office Hours",
        event_type=EventType.BUTTON_CLICK,
    )
    res2, requires_rag2, query_override2 = await router.evaluate_event(event2, state, mock_profile)
    assert res2 is not None
    assert res2.is_deterministic is True
    assert "9:00 AM to 6:00 PM" in res2.text
    assert requires_rag2 is False

    # Test Case 3: Clicking leaf node with action question -> Routes to RAG with specific query
    event3 = UserEvent(
        tenant_id="tenant_1",
        channel="whatsapp",
        user_id="user_abc",
        payload="Chartered Accountancy (CA)",
        event_type=EventType.BUTTON_CLICK,
    )
    res3, requires_rag3, query_override3 = await router.evaluate_event(event3, state, mock_profile)
    assert res3 is None
    assert requires_rag3 is True
    assert query_override3 == "Provide complete information regarding CA Foundation, Inter, and Final coaching."

    # Test Case 4: Navigation 'main menu' command
    event4 = UserEvent(
        tenant_id="tenant_1",
        channel="whatsapp",
        user_id="user_abc",
        payload="main menu",
        event_type=EventType.TEXT,
    )
    res4, requires_rag4, _ = await router.evaluate_event(event4, state, mock_profile)
    assert res4 is not None
    assert res4.is_deterministic is True
    assert res4.interactive_menu is not None
    print("[PASS] Layer 2: State machine deterministic routing and menu navigation passed")


async def test_layer4_bm25_and_reciprocal_rank_fusion():
    bm25 = TenantBM25Index("test_tenant")
    chunks = [
        {"id": "doc1_c0", "text": "The CA Foundation registration fee is 9200 INR payable to ICAI.", "metadata": {"doc_id": "doc1", "chunk_index": 0}},
        {"id": "doc1_c1", "text": "CMA Foundation eligibility requires 10+2 passing marks from a recognized board.", "metadata": {"doc_id": "doc1", "chunk_index": 1}},
        {"id": "doc2_c0", "text": "Hostel facilities include high-speed Wi-Fi, 3 meals daily, and 24/7 security.", "metadata": {"doc_id": "doc2", "chunk_index": 0}},
    ]
    bm25.build_index(chunks)

    # Search exact keyword
    results = bm25.search("CA Foundation registration fee")
    assert len(results) > 0
    assert results[0]["id"] == "doc1_c0"
    assert "9200 INR" in results[0]["text"]

    # Test Reciprocal Rank Fusion (RRF)
    dense_results = [
        {"id": "doc1_c1", "text": chunks[1]["text"], "score": 0.85, "metadata": chunks[1]["metadata"]},
        {"id": "doc1_c0", "text": chunks[0]["text"], "score": 0.80, "metadata": chunks[0]["metadata"]},
    ]
    sparse_results = [
        {"id": "doc1_c0", "text": chunks[0]["text"], "score": 4.5, "metadata": chunks[0]["metadata"]},
        {"id": "doc1_c1", "text": chunks[1]["text"], "score": 1.2, "metadata": chunks[1]["metadata"]},
    ]

    fused = reciprocal_rank_fusion(dense_results, sparse_results, top_k=2)
    assert len(fused) == 2
    assert fused[0]["metadata"]["doc_id"] == "doc1"
    print("[PASS] Layer 4: BM25 sparse keyword search and Hybrid RRF passed")


async def test_end_to_end_hybrid_engine():
    # Setup mock profile in memory cache for "tenant_demo"
    from app.services.profile_compiler import _PROFILE_CACHE
    from app.core.menu_graph import MenuGraph
    demo_nodes = [
        {
            "node_id": "MENU_ROOT",
            "title": "Welcome Menu",
            "options": [
                {"option_number": "1", "button_text": "Fee Structures", "target_type": "NAVIGATE_MENU", "target_id": "fees_menu"},
            ]
        },
        {
            "node_id": "fees_menu",
            "title": "Fee Structures",
            "options": [
                {"option_number": "1", "button_text": "CA Fees", "target_type": "DIRECT_ANSWER", "direct_answer": "CA Foundation fee is 9200 INR."},
            ]
        }
    ]
    demo_graph = MenuGraph.from_config(demo_nodes, root_node_id="MENU_ROOT")

    _PROFILE_CACHE[("tenant_demo", "whatsapp")] = {
        "client_id": "tenant_demo",
        "channel": "whatsapp",
        "compiled_system_prompt": "You are a professional assistant for Demo Institute.",
        "menu_graph": demo_graph,
        "menu_index": {},
        "context_images": [],
        "descriptive_rules": [],
        "context_config": {"mode": "none", "instructions": "", "capacity": 4},
    }

    engine = HybridEngine()

    # 1. Deterministic menu button click
    event_menu = UserEvent(
        tenant_id="tenant_demo",
        channel="whatsapp",
        user_id="phone_123",
        payload="Fee Structures",
        event_type=EventType.BUTTON_CLICK,
    )
    res1 = await engine.process_event(event_menu)
    assert res1.is_deterministic is True
    assert res1.interactive_menu is not None
    assert res1.active_node_id == "fees_menu"

    # 2. Deterministic leaf selection
    event_leaf = UserEvent(
        tenant_id="tenant_demo",
        channel="whatsapp",
        user_id="phone_123",
        payload="CA Fees",
        event_type=EventType.BUTTON_CLICK,
    )
    res2 = await engine.process_event(event_leaf)
    assert res2.is_deterministic is True
    assert "9200 INR" in res2.text

    print("[PASS] End-to-End: HybridEngine execution with zero-LLM deterministic routing passed")


async def test_state_machine_aware_query_cache():
    from app.utils.query_cache import generalize_response_for_cache, hydrate_cached_response

    # Test 1: Generalizing state variables into placeholders
    raw_response = "Hello Katrina! Welcome to SV Professional Institute. Here are your options."
    context_vars = {"user_name": "Katrina"}
    generalized = generalize_response_for_cache(raw_response, context_vars)
    assert "{user_name}" in generalized
    assert "Katrina" not in generalized

    # Test 2: Hydrating cached template response with a new visitor's name
    new_context = {"user_name": "Rahul"}
    hydrated = hydrate_cached_response(generalized, new_context)
    assert "Hello Rahul!" in hydrated
    assert "{user_name}" not in hydrated

    # Test 3: Hydrating when no user name is present in context
    no_name_context = {}
    hydrated_no_name = hydrate_cached_response(generalized, no_name_context)
    assert "Hello!" in hydrated_no_name
    assert "Katrina" not in hydrated_no_name
    assert "Rahul" not in hydrated_no_name

    print("[PASS] State-Machine Aware Semantic Cache template generalization & dynamic hydration passed")


async def main():
    print("==================================================")
    print("Running Hybrid State-Machine & RAG Test Suite")
    print("==================================================")
    await test_layer1_user_event_normalization()
    await test_layer2_state_store_and_transitions()
    await test_layer2_state_machine_deterministic_routing()
    await test_layer4_bm25_and_reciprocal_rank_fusion()
    await test_end_to_end_hybrid_engine()
    await test_state_machine_aware_query_cache()
    print("==================================================")
    print("ALL TESTS COMPLETED SUCCESSFULLY (100% PASS)")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(main())
