"""
Test Suite: Channel-Isolated State Management

Covers:
  - MenuGraph construction, O(1) lookups, and legacy bridge conversion
  - UserSessionState: navigation_stack, node_execution_counts, go_back()
  - StateMachineRouter: serial-number navigation, interactive ID, text match
  - Channel Renderers: WhatsApp (image + buttons/lists), Web (JSON), Default (text)
  - Frequency control: only_once skips re-rendering media
  - Backward compatibility with legacy menu_tree format
  - Full round-trip: UserEvent → Engine → Renderer → BotActions
"""
import asyncio
import sys
import os

# Ensure the backend package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest


def _run_async(coro):
    """Helper to run async code in sync tests — compatible with Python 3.10+."""
    return asyncio.run(coro)




# ═══════════════════════════════════════════════════════════════════════════════
# 1. MenuGraph Model Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestMenuGraphNode(unittest.TestCase):
    """Test MenuGraphNode and NodeOption data model."""

    def test_node_option_from_dict(self):
        from app.core.menu_graph import NodeOption, TARGET_NAVIGATE_MENU
        data = {
            "option_number": "1",
            "button_text": "CA / Commerce",
            "target_type": "NAVIGATE_MENU",
            "target_id": "MENU_110",
        }
        opt = NodeOption.from_dict(data)
        self.assertEqual(opt.option_number, "1")
        self.assertEqual(opt.button_text, "CA / Commerce")
        self.assertEqual(opt.target_type, TARGET_NAVIGATE_MENU)
        self.assertEqual(opt.target_id, "MENU_110")

    def test_node_from_dict(self):
        from app.core.menu_graph import MenuGraphNode
        data = {
            "node_id": "MENU_100",
            "menu_number": "1.0",
            "title": "Select Program Stream",
            "whatsapp_media": {"image_url": "https://example.com/img.jpg", "caption": "Brochure"},
            "frequency": "only_once",
            "options": [
                {"option_number": "1", "button_text": "CA / Commerce", "target_type": "NAVIGATE_MENU", "target_id": "MENU_110"},
                {"option_number": "2", "button_text": "Science", "target_type": "NAVIGATE_MENU", "target_id": "MENU_120"},
            ],
        }
        node = MenuGraphNode.from_dict(data)
        self.assertEqual(node.node_id, "MENU_100")
        self.assertEqual(node.menu_number, "1.0")
        self.assertEqual(node.title, "Select Program Stream")
        self.assertTrue(node.has_whatsapp_media)
        self.assertFalse(node.is_leaf)
        self.assertEqual(len(node.options), 2)
        self.assertEqual(node.frequency, "only_once")

    def test_leaf_node(self):
        from app.core.menu_graph import MenuGraphNode
        node = MenuGraphNode(
            node_id="LEAF_1",
            menu_number="1.1.1",
            title="What is CA?",
            options=[],
            direct_answer="CA stands for Chartered Accountant.",
        )
        self.assertTrue(node.is_leaf)
        self.assertFalse(node.has_whatsapp_media)
        self.assertEqual(node.direct_answer, "CA stands for Chartered Accountant.")


class TestMenuGraph(unittest.TestCase):
    """Test MenuGraph construction and O(1) lookups."""

    def _build_sample_graph(self):
        from app.core.menu_graph import MenuGraph, MenuGraphNode, NodeOption, TARGET_NAVIGATE_MENU, TARGET_TRIGGER_RAG

        root = MenuGraphNode(
            node_id="MENU_100",
            menu_number="1.0",
            title="Welcome Menu",
            whatsapp_media={"image_url": "https://cdn.example.com/welcome.jpg"},
            frequency="only_once",
            options=[
                NodeOption("1", "CA / Commerce", TARGET_NAVIGATE_MENU, "MENU_110"),
                NodeOption("2", "Science Stream", TARGET_NAVIGATE_MENU, "MENU_120"),
                NodeOption("3", "Ask a Question", TARGET_TRIGGER_RAG, "", rag_prompt="General inquiry"),
            ],
        )

        sub1 = MenuGraphNode(
            node_id="MENU_110",
            menu_number="1.1",
            title="CA / Commerce Programs",
            options=[
                NodeOption("1", "CA Foundation", TARGET_TRIGGER_RAG, "LEAF_111", rag_prompt="Tell me about CA Foundation course"),
                NodeOption("2", "B.Com Honours", TARGET_TRIGGER_RAG, "LEAF_112", rag_prompt="Tell me about B.Com Honours"),
            ],
        )

        sub2 = MenuGraphNode(
            node_id="MENU_120",
            menu_number="1.2",
            title="Science Programs",
            options=[
                NodeOption("1", "B.Sc Physics", TARGET_TRIGGER_RAG, "LEAF_121", rag_prompt="B.Sc Physics details"),
            ],
        )

        leaf = MenuGraphNode(
            node_id="LEAF_111",
            menu_number="1.1.1",
            title="CA Foundation",
            direct_answer="CA Foundation is a 4-month entry-level course.",
        )

        graph = MenuGraph(root_node_id="MENU_100")
        for n in [root, sub1, sub2, leaf]:
            graph.add_node(n)
        return graph

    def test_node_count(self):
        graph = self._build_sample_graph()
        self.assertEqual(graph.node_count, 4)

    def test_get_root_node(self):
        graph = self._build_sample_graph()
        root = graph.get_root_node()
        self.assertIsNotNone(root)
        self.assertEqual(root.node_id, "MENU_100")

    def test_get_node_by_id(self):
        graph = self._build_sample_graph()
        node = graph.get_node("MENU_110")
        self.assertIsNotNone(node)
        self.assertEqual(node.title, "CA / Commerce Programs")

    def test_get_node_by_menu_number(self):
        graph = self._build_sample_graph()
        node = graph.get_node("1.2")
        self.assertIsNotNone(node)
        self.assertEqual(node.node_id, "MENU_120")

    def test_get_option_by_number(self):
        graph = self._build_sample_graph()
        opt = graph.get_option_by_number("MENU_100", "2")
        self.assertIsNotNone(opt)
        self.assertEqual(opt.button_text, "Science Stream")
        self.assertEqual(opt.target_id, "MENU_120")

    def test_get_option_by_text(self):
        graph = self._build_sample_graph()
        opt = graph.get_option_by_text("MENU_100", "CA / Commerce")
        self.assertIsNotNone(opt)
        self.assertEqual(opt.option_number, "1")

    def test_get_option_by_text_case_insensitive(self):
        graph = self._build_sample_graph()
        opt = graph.get_option_by_text("MENU_100", "ca / commerce")
        self.assertIsNotNone(opt)
        self.assertEqual(opt.option_number, "1")

    def test_get_option_by_interactive_id(self):
        graph = self._build_sample_graph()
        opt = graph.get_option_by_interactive_id("MENU_100", "1")
        self.assertIsNotNone(opt)
        self.assertEqual(opt.button_text, "CA / Commerce")

    def test_nonexistent_node(self):
        graph = self._build_sample_graph()
        self.assertIsNone(graph.get_node("NONEXISTENT"))

    def test_nonexistent_option(self):
        graph = self._build_sample_graph()
        self.assertIsNone(graph.get_option_by_number("MENU_100", "99"))

    def test_from_config(self):
        from app.core.menu_graph import MenuGraph
        config = [
            {
                "node_id": "N1",
                "menu_number": "1",
                "title": "Root",
                "options": [
                    {"option_number": "1", "button_text": "Opt A", "target_type": "NAVIGATE_MENU", "target_id": "N2"},
                ],
            },
            {
                "node_id": "N2",
                "menu_number": "1.1",
                "title": "Sub",
                "options": [],
                "direct_answer": "Answer for Sub",
            },
        ]
        graph = MenuGraph.from_config(config, root_node_id="N1")
        self.assertEqual(graph.node_count, 2)
        self.assertEqual(graph.get_root_node().node_id, "N1")
        self.assertTrue(graph.get_node("N2").is_leaf)


class TestMenuGraphLegacyBridge(unittest.TestCase):
    """Test backward-compatible conversion from legacy menu_tree to MenuGraph."""

    def test_from_legacy_menu_tree(self):
        from app.core.menu_graph import MenuGraph, TARGET_NAVIGATE_MENU, TARGET_TRIGGER_RAG
        legacy_tree = [
            {
                "id": "courses",
                "label": "Our Courses",
                "children": [
                    {
                        "id": "ca",
                        "label": "CA Program",
                        "children": [],
                        "action_question": "Tell me about the CA program",
                    },
                    {
                        "id": "bcom",
                        "label": "B.Com",
                        "children": [],
                        "direct_answer": "B.Com is a 3-year degree program.",
                    },
                ],
            },
            {
                "id": "admissions",
                "label": "Admissions",
                "children": [],
                "action_question": "",
            },
        ]
        graph = MenuGraph.from_legacy_menu_tree(legacy_tree)
        self.assertGreater(graph.node_count, 0)

        # Root should be the first node
        root = graph.get_root_node()
        self.assertIsNotNone(root)

        # Root should have options pointing to children
        self.assertGreater(len(root.options), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. UserSessionState Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestUserSessionState(unittest.TestCase):
    """Test the updated UserSessionState with navigation_stack and execution counts."""

    def test_navigation_stack_default(self):
        from app.services.state_store import UserSessionState
        state = UserSessionState(
            session_id="t:c:u", tenant_id="t", channel="c", user_id="u"
        )
        self.assertEqual(state.navigation_stack, [])
        self.assertEqual(state.node_execution_counts, {})

    def test_increment_node_count(self):
        from app.services.state_store import UserSessionState
        state = UserSessionState(
            session_id="t:c:u", tenant_id="t", channel="c", user_id="u"
        )
        self.assertFalse(state.was_node_shown("MENU_100"))
        state.increment_node_count("MENU_100")
        self.assertTrue(state.was_node_shown("MENU_100"))
        self.assertEqual(state.get_node_show_count("MENU_100"), 1)

        state.increment_node_count("MENU_100")
        self.assertEqual(state.get_node_show_count("MENU_100"), 2)

    def test_from_dict_backward_compat(self):
        """Deserializing with legacy 'history_trail' should populate navigation_stack."""
        from app.services.state_store import UserSessionState
        data = {
            "session_id": "t:c:u",
            "tenant_id": "t",
            "channel": "c",
            "user_id": "u",
            "current_node_id": "MENU_100",
            "history_trail": ["MENU_ROOT", "MENU_50"],
        }
        state = UserSessionState.from_dict(data)
        self.assertEqual(state.navigation_stack, ["MENU_ROOT", "MENU_50"])

    def test_from_dict_new_format(self):
        from app.services.state_store import UserSessionState
        data = {
            "session_id": "t:c:u",
            "tenant_id": "t",
            "channel": "c",
            "user_id": "u",
            "navigation_stack": ["N1", "N2"],
            "node_execution_counts": {"N1": 3, "N2": 1},
        }
        state = UserSessionState.from_dict(data)
        self.assertEqual(state.navigation_stack, ["N1", "N2"])
        self.assertEqual(state.get_node_show_count("N1"), 3)

    def test_to_dict_roundtrip(self):
        from app.services.state_store import UserSessionState
        state = UserSessionState(
            session_id="t:c:u", tenant_id="t", channel="c", user_id="u",
            navigation_stack=["A", "B"],
            node_execution_counts={"A": 1, "B": 2},
        )
        d = state.to_dict()
        restored = UserSessionState.from_dict(d)
        self.assertEqual(restored.navigation_stack, ["A", "B"])
        self.assertEqual(restored.node_execution_counts, {"A": 1, "B": 2})


class TestStateStoreGoBack(unittest.TestCase):
    """Test StateStore.go_back() with in-memory store."""

    def test_go_back_pops_stack(self):
        from app.services.state_store import StateStore, UserSessionState

        async def _run():
            store = StateStore()
            state = UserSessionState(
                session_id="t:w:u", tenant_id="t", channel="w", user_id="u",
                current_node_id="MENU_110",
                active_menu_id="MENU_110",
                navigation_stack=["MENU_100"],
            )
            store._memory_store[state.session_id] = state

            prev = await store.go_back(state)
            self.assertEqual(prev, "MENU_100")
            self.assertEqual(state.current_node_id, "MENU_100")
            self.assertEqual(state.navigation_stack, [])

        _run_async(_run())

    def test_go_back_empty_stack_returns_none(self):
        from app.services.state_store import StateStore, UserSessionState

        async def _run():
            store = StateStore()
            state = UserSessionState(
                session_id="t:w:u", tenant_id="t", channel="w", user_id="u",
                navigation_stack=[],
            )
            store._memory_store[state.session_id] = state
            prev = await store.go_back(state)
            self.assertIsNone(prev)

        _run_async(_run())

    def test_transition_node_pushes_stack(self):
        from app.services.state_store import StateStore, UserSessionState

        async def _run():
            store = StateStore()
            state = UserSessionState(
                session_id="t:w:u", tenant_id="t", channel="w", user_id="u",
                current_node_id="MENU_100",
                navigation_stack=[],
            )
            store._memory_store[state.session_id] = state

            await store.transition_node(state, next_node_id="MENU_110", active_menu_id="MENU_110")
            self.assertEqual(state.navigation_stack, ["MENU_100"])
            self.assertEqual(state.current_node_id, "MENU_110")
            self.assertEqual(state.get_node_show_count("MENU_110"), 1)

        _run_async(_run())


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Channel Renderer Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestWhatsAppRenderer(unittest.TestCase):
    """Test WhatsAppChannelRenderer produces correct BotAction payloads."""

    def _make_response(self, options_count=3, include_media=True, frequency="always"):
        from app.core.user_event import EngineResponse, BotAction, ActionType
        from app.services.state_store import UserSessionState

        options = []
        for i in range(1, options_count + 1):
            options.append({
                "id": str(i),
                "option_number": str(i),
                "label": f"Option {i} Label Text",
                "button_text": f"Option {i} Label Text",
                "target_type": "NAVIGATE_MENU",
            })

        media = {"image_url": "https://cdn.example.com/img.jpg", "caption": "Test"} if include_media else {}

        resp = EngineResponse(
            session_id="t:w:u",
            text="Menu",
            is_deterministic=True,
            active_node_id="MENU_100",
            actions=[],
            interactive_menu={
                "body_text": "Select an option:",
                "options": options,
                "header_text": "Test Menu",
                "node_id": "MENU_100",
                "whatsapp_media": media,
                "frequency": frequency,
            },
        )

        state = UserSessionState(
            session_id="t:w:u", tenant_id="t", channel="whatsapp", user_id="u",
            navigation_stack=["MENU_ROOT"],
        )

        return resp, state

    def test_buttons_for_3_or_fewer(self):
        from app.adapters.channel_renderer import WhatsAppChannelRenderer
        from app.core.user_event import ActionType

        renderer = WhatsAppChannelRenderer()
        resp, state = self._make_response(options_count=3)
        actions = renderer.render_menu_actions(resp, state)

        # Should have IMAGE_MEDIA + INTERACTIVE_MENU = 2 actions
        types = [a.action_type for a in actions]
        self.assertIn(ActionType.IMAGE_MEDIA, types)
        self.assertIn(ActionType.INTERACTIVE_MENU, types)

        # Check button text is truncated to 20 chars
        menu_action = [a for a in actions if a.action_type == ActionType.INTERACTIVE_MENU][0]
        for opt in menu_action.payload["options"]:
            self.assertLessEqual(len(opt["label"]), 20)

    def test_list_for_more_than_3(self):
        from app.adapters.channel_renderer import WhatsAppChannelRenderer
        from app.core.user_event import ActionType

        renderer = WhatsAppChannelRenderer()
        resp, state = self._make_response(options_count=5)
        actions = renderer.render_menu_actions(resp, state)

        menu_action = [a for a in actions if a.action_type == ActionType.INTERACTIVE_MENU][0]
        # List items truncated to 24 chars
        for opt in menu_action.payload["options"]:
            self.assertLessEqual(len(opt["label"]), 24)

    def test_no_image_when_no_media(self):
        from app.adapters.channel_renderer import WhatsAppChannelRenderer
        from app.core.user_event import ActionType

        renderer = WhatsAppChannelRenderer()
        resp, state = self._make_response(options_count=2, include_media=False)
        actions = renderer.render_menu_actions(resp, state)

        types = [a.action_type for a in actions]
        self.assertNotIn(ActionType.IMAGE_MEDIA, types)
        self.assertIn(ActionType.INTERACTIVE_MENU, types)

    def test_only_once_skips_image_on_repeat(self):
        """When frequency is 'only_once' and node was shown before, skip image."""
        from app.adapters.channel_renderer import WhatsAppChannelRenderer
        from app.core.user_event import ActionType

        renderer = WhatsAppChannelRenderer()
        resp, state = self._make_response(frequency="only_once", include_media=True)

        # Mark node as already shown
        state.node_execution_counts["MENU_100"] = 1

        actions = renderer.render_menu_actions(resp, state)
        types = [a.action_type for a in actions]
        # Image should be SKIPPED because only_once + already shown
        self.assertNotIn(ActionType.IMAGE_MEDIA, types)
        # Menu should still be present
        self.assertIn(ActionType.INTERACTIVE_MENU, types)


class TestWebRenderer(unittest.TestCase):
    """Test WebChannelRenderer produces clean JSON without images."""

    def test_web_no_images(self):
        from app.adapters.channel_renderer import WebChannelRenderer
        from app.core.user_event import EngineResponse, ActionType
        from app.services.state_store import UserSessionState

        renderer = WebChannelRenderer()
        resp = EngineResponse(
            session_id="t:w:u",
            text="Menu",
            is_deterministic=True,
            active_node_id="N1",
            actions=[],
            interactive_menu={
                "body_text": "*Select*:",
                "options": [
                    {"option_number": "1", "button_text": "Choice A", "target_type": "NAVIGATE_MENU"},
                    {"option_number": "2", "button_text": "Choice B", "target_type": "TRIGGER_RAG"},
                ],
                "header_text": "Menu",
                "whatsapp_media": {"image_url": "https://example.com/img.jpg"},
            },
        )
        state = UserSessionState(
            session_id="t:w:u", tenant_id="t", channel="widget", user_id="u"
        )

        actions = renderer.render_menu_actions(resp, state)
        types = [a.action_type for a in actions]

        # No IMAGE_MEDIA for web
        self.assertNotIn(ActionType.IMAGE_MEDIA, types)
        # Should have INTERACTIVE_MENU + TEXT
        self.assertIn(ActionType.INTERACTIVE_MENU, types)
        self.assertIn(ActionType.TEXT, types)

        # Body text should have *bold* stripped
        menu_action = [a for a in actions if a.action_type == ActionType.INTERACTIVE_MENU][0]
        self.assertNotIn("*", menu_action.payload["body_text"])

        # Options should have option_number and button_text keys
        for opt in menu_action.payload["options"]:
            self.assertIn("option_number", opt)
            self.assertIn("button_text", opt)


class TestDefaultRenderer(unittest.TestCase):
    """Test DefaultChannelRenderer produces numbered text list."""

    def test_numbered_list(self):
        from app.adapters.channel_renderer import DefaultChannelRenderer
        from app.core.user_event import EngineResponse, ActionType
        from app.services.state_store import UserSessionState

        renderer = DefaultChannelRenderer()
        resp = EngineResponse(
            session_id="t:tg:u",
            text="Menu",
            is_deterministic=True,
            active_node_id="N1",
            actions=[],
            interactive_menu={
                "body_text": "Choose:",
                "options": [
                    {"option_number": "1", "button_text": "Alpha"},
                    {"option_number": "2", "button_text": "Beta"},
                ],
                "header_text": "Test",
            },
        )
        state = UserSessionState(
            session_id="t:tg:u", tenant_id="t", channel="telegram", user_id="u"
        )

        actions = renderer.render_menu_actions(resp, state)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action_type, ActionType.TEXT)

        text = actions[0].payload["text"]
        self.assertIn("1. Alpha", text)
        self.assertIn("2. Beta", text)
        self.assertIn("Reply with the option number", text)


class TestRendererRegistry(unittest.TestCase):
    """Test the renderer registry returns correct renderers."""

    def test_whatsapp_renderer(self):
        from app.adapters.channel_renderer import get_channel_renderer, WhatsAppChannelRenderer
        r = get_channel_renderer("whatsapp")
        self.assertIsInstance(r, WhatsAppChannelRenderer)

    def test_widget_renderer(self):
        from app.adapters.channel_renderer import get_channel_renderer, WebChannelRenderer
        r = get_channel_renderer("widget")
        self.assertIsInstance(r, WebChannelRenderer)

    def test_web_renderer(self):
        from app.adapters.channel_renderer import get_channel_renderer, WebChannelRenderer
        r = get_channel_renderer("web")
        self.assertIsInstance(r, WebChannelRenderer)

    def test_unknown_falls_to_default(self):
        from app.adapters.channel_renderer import get_channel_renderer, DefaultChannelRenderer
        r = get_channel_renderer("unknown_channel_xyz")
        self.assertIsInstance(r, DefaultChannelRenderer)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. StateMachineRouter Tests (MenuGraph path)
# ═══════════════════════════════════════════════════════════════════════════════

class TestStateMachineGraphEvaluation(unittest.TestCase):
    """Test StateMachineRouter._evaluate_graph with serial-number navigation."""

    def _build_graph_and_state(self):
        from app.core.menu_graph import MenuGraph, MenuGraphNode, NodeOption, TARGET_NAVIGATE_MENU, TARGET_TRIGGER_RAG
        from app.services.state_store import UserSessionState

        root = MenuGraphNode(
            node_id="ROOT",
            menu_number="1",
            title="Main Menu",
            options=[
                NodeOption("1", "Courses", TARGET_NAVIGATE_MENU, "COURSES"),
                NodeOption("2", "Ask Anything", TARGET_TRIGGER_RAG, "", rag_prompt="Open question"),
            ],
        )
        courses = MenuGraphNode(
            node_id="COURSES",
            menu_number="1.1",
            title="Our Courses",
            options=[
                NodeOption("1", "CA Foundation", TARGET_TRIGGER_RAG, "CA_LEAF", rag_prompt="Tell me about CA Foundation"),
            ],
        )
        leaf = MenuGraphNode(
            node_id="DIRECT_LEAF",
            menu_number="2",
            title="Direct Answer Node",
            direct_answer="This is a direct answer.",
        )

        graph = MenuGraph(root_node_id="ROOT")
        for n in [root, courses, leaf]:
            graph.add_node(n)

        state = UserSessionState(
            session_id="t:w:u", tenant_id="t", channel="whatsapp", user_id="u",
            current_node_id="ROOT",
            active_menu_id="ROOT",
        )

        return graph, state

    def test_serial_number_navigate_menu(self):
        """Typing "1" on ROOT should navigate to COURSES."""
        from app.core.user_event import UserEvent
        from app.services.state_machine import StateMachineRouter

        graph, state = self._build_graph_and_state()
        router = StateMachineRouter()
        event = UserEvent(tenant_id="t", channel="whatsapp", user_id="u", payload="1")

        async def _run():
            resp, requires_rag, query = await router._evaluate_graph(event, state, graph)
            self.assertIsNotNone(resp)
            self.assertFalse(requires_rag)
            self.assertEqual(resp.active_node_id, "COURSES")
            self.assertTrue(resp.is_deterministic)
            # Navigation stack should have ROOT
            self.assertIn("ROOT", state.navigation_stack)

        _run_async(_run())

    def test_serial_number_trigger_rag(self):
        """Typing "2" on ROOT should trigger RAG."""
        from app.core.user_event import UserEvent
        from app.services.state_machine import StateMachineRouter

        graph, state = self._build_graph_and_state()
        router = StateMachineRouter()
        event = UserEvent(tenant_id="t", channel="whatsapp", user_id="u", payload="2")

        async def _run():
            resp, requires_rag, query = await router._evaluate_graph(event, state, graph)
            self.assertIsNone(resp)
            self.assertTrue(requires_rag)
            self.assertEqual(query, "Open question")

        _run_async(_run())

    def test_go_back_command(self):
        """Typing "0" should pop the navigation stack."""
        from app.core.user_event import UserEvent
        from app.services.state_machine import StateMachineRouter

        graph, state = self._build_graph_and_state()
        state.navigation_stack = ["ROOT"]
        state.current_node_id = "COURSES"
        state.active_menu_id = "COURSES"
        router = StateMachineRouter()
        event = UserEvent(tenant_id="t", channel="whatsapp", user_id="u", payload="0")

        async def _run():
            resp, requires_rag, query = await router._evaluate_graph(event, state, graph)
            self.assertIsNotNone(resp)
            self.assertFalse(requires_rag)
            # Should be back at ROOT
            self.assertEqual(resp.active_node_id, "ROOT")
            self.assertEqual(state.navigation_stack, [])

        _run_async(_run())

    def test_main_menu_command(self):
        """Typing 'menu' should reset to root."""
        from app.core.user_event import UserEvent
        from app.services.state_machine import StateMachineRouter

        graph, state = self._build_graph_and_state()
        state.navigation_stack = ["ROOT"]
        state.current_node_id = "COURSES"
        router = StateMachineRouter()
        event = UserEvent(tenant_id="t", channel="whatsapp", user_id="u", payload="menu")

        async def _run():
            resp, requires_rag, query = await router._evaluate_graph(event, state, graph)
            self.assertIsNotNone(resp)
            self.assertFalse(requires_rag)
            self.assertEqual(resp.active_node_id, "ROOT")

        _run_async(_run())

    def test_unmatched_text_falls_to_rag(self):
        """Typing random text should fallthrough to RAG."""
        from app.core.user_event import UserEvent
        from app.services.state_machine import StateMachineRouter

        graph, state = self._build_graph_and_state()
        router = StateMachineRouter()
        event = UserEvent(tenant_id="t", channel="whatsapp", user_id="u", payload="What is the fee structure?")

        async def _run():
            resp, requires_rag, query = await router._evaluate_graph(event, state, graph)
            self.assertIsNone(resp)
            self.assertTrue(requires_rag)
            self.assertEqual(query, "What is the fee structure?")

        _run_async(_run())

    def test_text_match_option(self):
        """Typing the button text should match the option."""
        from app.core.user_event import UserEvent
        from app.services.state_machine import StateMachineRouter

        graph, state = self._build_graph_and_state()
        router = StateMachineRouter()
        event = UserEvent(tenant_id="t", channel="whatsapp", user_id="u", payload="Courses")

        async def _run():
            resp, requires_rag, query = await router._evaluate_graph(event, state, graph)
            self.assertIsNotNone(resp)
            self.assertFalse(requires_rag)
            self.assertEqual(resp.active_node_id, "COURSES")

        _run_async(_run())


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Integration Tests — Full Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullPipelineIntegration(unittest.TestCase):
    """End-to-end: UserEvent → StateMachine → Renderer → BotActions."""

    def test_whatsapp_menu_with_image(self):
        """WhatsApp channel should get IMAGE_MEDIA + INTERACTIVE_MENU actions."""
        from app.core.menu_graph import MenuGraph, MenuGraphNode, NodeOption, TARGET_NAVIGATE_MENU
        from app.core.user_event import UserEvent, EngineResponse, ActionType
        from app.services.state_store import UserSessionState
        from app.services.state_machine import StateMachineRouter
        from app.adapters.channel_renderer import get_channel_renderer

        root = MenuGraphNode(
            node_id="ROOT",
            menu_number="1",
            title="Welcome",
            whatsapp_media={"image_url": "https://cdn.example.com/welcome.jpg", "caption": "Hello!"},
            frequency="always",
            options=[
                NodeOption("1", "Option A", TARGET_NAVIGATE_MENU, "A"),
                NodeOption("2", "Option B", TARGET_NAVIGATE_MENU, "B"),
            ],
        )
        node_a = MenuGraphNode(node_id="A", menu_number="1.1", title="A", options=[])
        node_b = MenuGraphNode(node_id="B", menu_number="1.2", title="B", options=[])

        graph = MenuGraph(root_node_id="ROOT")
        for n in [root, node_a, node_b]:
            graph.add_node(n)

        state = UserSessionState(
            session_id="t:wa:u", tenant_id="t", channel="whatsapp", user_id="u"
        )

        router = StateMachineRouter()
        event = UserEvent(tenant_id="t", channel="whatsapp", user_id="u", payload="menu")

        async def _run():
            resp, _, _ = await router._evaluate_graph(event, state, graph)
            self.assertIsNotNone(resp)

            # Apply WhatsApp renderer
            renderer = get_channel_renderer("whatsapp")
            rendered = renderer.render(resp, state)

            action_types = [a.action_type for a in rendered.actions]
            self.assertIn(ActionType.IMAGE_MEDIA, action_types)
            self.assertIn(ActionType.INTERACTIVE_MENU, action_types)

            # Verify image comes before menu
            img_idx = action_types.index(ActionType.IMAGE_MEDIA)
            menu_idx = action_types.index(ActionType.INTERACTIVE_MENU)
            self.assertLess(img_idx, menu_idx)

        _run_async(_run())

    def test_web_menu_no_image(self):
        """Web channel should get INTERACTIVE_MENU + TEXT, NO IMAGE."""
        from app.core.menu_graph import MenuGraph, MenuGraphNode, NodeOption, TARGET_NAVIGATE_MENU
        from app.core.user_event import UserEvent, ActionType
        from app.services.state_store import UserSessionState
        from app.services.state_machine import StateMachineRouter
        from app.adapters.channel_renderer import get_channel_renderer

        root = MenuGraphNode(
            node_id="ROOT",
            menu_number="1",
            title="Welcome",
            whatsapp_media={"image_url": "https://cdn.example.com/img.jpg"},
            options=[
                NodeOption("1", "A", TARGET_NAVIGATE_MENU, "A"),
            ],
        )
        node_a = MenuGraphNode(node_id="A", menu_number="1.1", title="A", options=[])
        graph = MenuGraph(root_node_id="ROOT")
        graph.add_node(root)
        graph.add_node(node_a)

        state = UserSessionState(
            session_id="t:w:u", tenant_id="t", channel="widget", user_id="u"
        )

        router = StateMachineRouter()
        event = UserEvent(tenant_id="t", channel="widget", user_id="u", payload="menu")

        async def _run():
            resp, _, _ = await router._evaluate_graph(event, state, graph)
            self.assertIsNotNone(resp)

            renderer = get_channel_renderer("widget")
            rendered = renderer.render(resp, state)

            action_types = [a.action_type for a in rendered.actions]
            self.assertNotIn(ActionType.IMAGE_MEDIA, action_types)
            self.assertIn(ActionType.INTERACTIVE_MENU, action_types)

        _run_async(_run())


if __name__ == "__main__":
    unittest.main()
