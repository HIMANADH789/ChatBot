"""
Core Node Model: The Dynamic Menu Graph

Represents all tenant interaction paths as a Graph of Nodes.
Each node has a unique ID, serial menu_number, channel-specific media,
and a list of options that lead to other nodes or RAG queries.

The MenuGraph builds an O(1) lookup index by node_id, menu_number,
and lowercased button_text for sub-millisecond routing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Target Type Constants ───────────────────────────────────────────────────────
TARGET_NAVIGATE_MENU = "NAVIGATE_MENU"
TARGET_TRIGGER_RAG = "TRIGGER_RAG"
TARGET_DIRECT_ANSWER = "DIRECT_ANSWER"

# ── Frequency Constants ─────────────────────────────────────────────────────────
FREQ_ALWAYS = "always"
FREQ_ONLY_ONCE = "only_once"
FREQ_ON_INTENT = "on_intent"


@dataclass
class NodeOption:
    """
    A single selectable option within a menu node.

    - option_number: Serial number for input matching ("1", "2", "3")
    - button_text: Display label (≤20 chars for WhatsApp buttons, ≤24 for lists)
    - target_type: TARGET_NAVIGATE_MENU, TARGET_TRIGGER_RAG, or TARGET_DIRECT_ANSWER
    - target_id: node_id to navigate to (when target_type is NAVIGATE_MENU)
    - rag_prompt: Augmented query for RAG pipeline (when target_type is TRIGGER_RAG)
    - direct_answer: Static answer text returned directly (when target_type is DIRECT_ANSWER)
    """
    option_number: str
    button_text: str
    target_type: str = TARGET_NAVIGATE_MENU
    target_id: str = ""
    rag_prompt: str = ""
    direct_answer: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NodeOption:
        return cls(
            option_number=str(data.get("option_number", "")),
            button_text=str(data.get("button_text", "")),
            target_type=data.get("target_type", TARGET_NAVIGATE_MENU),
            target_id=str(data.get("target_id", "")),
            rag_prompt=str(data.get("rag_prompt", "")),
            direct_answer=str(data.get("direct_answer", "")),
        )


@dataclass
class MenuGraphNode:
    """
    A single node in the dynamic menu graph.

    - node_id: Unique identifier (e.g. "MENU_100", "MENU_110")
    - menu_number: Hierarchical serial number (e.g. "1.0", "1.1", "1.1.1")
    - title: Menu heading / display text
    - whatsapp_media: Channel-specific media for WhatsApp {"image_url": "...", "caption": "..."}
    - options: Ordered list of selectable options
    - frequency: "always" | "only_once" — controls media re-delivery
    - direct_answer: If set, zero-LLM static response (leaf node shortcut)
    """
    node_id: str
    menu_number: str
    title: str
    options: List[NodeOption] = field(default_factory=list)
    whatsapp_media: Dict[str, str] = field(default_factory=dict)
    frequency: str = FREQ_ALWAYS
    direct_answer: str = ""

    @property
    def is_leaf(self) -> bool:
        """True if this node has no options (terminal node)."""
        return len(self.options) == 0

    @property
    def has_whatsapp_media(self) -> bool:
        """True if this node has a WhatsApp image attachment."""
        return bool(self.whatsapp_media.get("image_url"))

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["options"] = [opt.to_dict() for opt in self.options]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MenuGraphNode:
        options_raw = data.get("options") or []
        options = [NodeOption.from_dict(o) for o in options_raw]
        return cls(
            node_id=str(data.get("node_id", "")),
            menu_number=str(data.get("menu_number", "")),
            title=str(data.get("title", "")),
            options=options,
            whatsapp_media=data.get("whatsapp_media") or {},
            frequency=data.get("frequency", FREQ_ALWAYS),
            direct_answer=str(data.get("direct_answer", "")),
        )


class MenuGraph:
    """
    In-memory graph of all menu nodes for a tenant, with O(1) lookup by
    node_id, menu_number, and lowercased button_text.
    """

    def __init__(self, root_node_id: str = ""):
        self.root_node_id: str = root_node_id
        self._nodes: Dict[str, MenuGraphNode] = {}
        # O(1) lookup indices
        self._index_by_id: Dict[str, MenuGraphNode] = {}
        self._index_by_menu_number: Dict[str, MenuGraphNode] = {}
        # Maps lowercased button_text → (parent_node_id, NodeOption)
        self._index_by_button_text: Dict[str, List[tuple[str, NodeOption]]] = {}

    def add_node(self, node: MenuGraphNode) -> None:
        """Register a node and update all lookup indices."""
        self._nodes[node.node_id] = node
        self._index_by_id[node.node_id] = node
        if node.menu_number:
            self._index_by_menu_number[node.menu_number] = node

        # Index each option's button_text for text-match resolution
        for opt in node.options:
            key = opt.button_text.strip().lower()
            if key:
                if key not in self._index_by_button_text:
                    self._index_by_button_text[key] = []
                self._index_by_button_text[key].append((node.node_id, opt))

    def get_node(self, id_or_number: str) -> Optional[MenuGraphNode]:
        """O(1) lookup by node_id or menu_number."""
        if not id_or_number:
            return None
        node = self._index_by_id.get(id_or_number)
        if node:
            return node
        return self._index_by_menu_number.get(id_or_number)

    def get_root_node(self) -> Optional[MenuGraphNode]:
        """Return the designated root node of the graph."""
        if self.root_node_id:
            return self.get_node(self.root_node_id)
        # Fallback: return the first node
        if self._nodes:
            return next(iter(self._nodes.values()))
        return None

    def get_option_by_number(
        self, node_id: str, option_number: str
    ) -> Optional[NodeOption]:
        """
        Given the active node and a serial number input ("1", "2"),
        resolve to the matching NodeOption. O(1).
        """
        node = self.get_node(node_id)
        if not node:
            return None
        for opt in node.options:
            if opt.option_number == option_number:
                return opt
        return None

    def get_option_by_text(
        self, node_id: str, text: str
    ) -> Optional[NodeOption]:
        """
        Match user text input against the button_text of the active node's options.
        Scoped to the active node only (not global) for disambiguation.
        """
        node = self.get_node(node_id)
        if not node:
            return None
        norm_text = text.strip().lower()
        for opt in node.options:
            if opt.button_text.strip().lower() == norm_text:
                return opt
        return None

    def get_option_by_interactive_id(
        self, node_id: str, interactive_id: str
    ) -> Optional[NodeOption]:
        """
        Match a WhatsApp interactive callback ID (option_number or button_text)
        against the active node's options.
        """
        node = self.get_node(node_id)
        if not node:
            return None
        norm_id = interactive_id.strip().lower()
        for opt in node.options:
            if opt.option_number == interactive_id or opt.option_number == norm_id:
                return opt
            if opt.button_text.strip().lower() == norm_id:
                return opt
        return None

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def all_nodes(self) -> List[MenuGraphNode]:
        return list(self._nodes.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root_node_id": self.root_node_id,
            "nodes": {nid: n.to_dict() for nid, n in self._nodes.items()},
        }

    @classmethod
    def from_config(cls, config: List[Dict[str, Any]], root_node_id: str = "") -> MenuGraph:
        """
        Build a MenuGraph from a list of node dicts (tenant config format).
        """
        graph = cls(root_node_id=root_node_id)
        for node_data in config:
            node = MenuGraphNode.from_dict(node_data)
            graph.add_node(node)

        # Auto-detect root if not specified
        if not graph.root_node_id and graph._nodes:
            graph.root_node_id = next(iter(graph._nodes.keys()))

        logger.debug(
            "Built MenuGraph with %d nodes (root=%s)",
            graph.node_count,
            graph.root_node_id,
        )
        return graph

    @classmethod
    def validate_config(
        cls, config: List[Dict[str, Any]], root_node_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validate menu graph configuration before publishing.
        Returns:
            {
                "valid": bool,
                "errors": list[str],
                "warnings": list[str],
                "node_count": int,
                "root_node_id": str,
            }
        """
        errors: List[str] = []
        warnings: List[str] = []

        if not config:
            return {
                "valid": True,
                "errors": [],
                "warnings": ["Menu graph is empty."],
                "node_count": 0,
                "root_node_id": "",
            }

        node_ids: set[str] = set()
        menu_numbers: set[str] = set()

        for idx, node_data in enumerate(config):
            node_id = str(node_data.get("node_id", "")).strip()
            if not node_id:
                errors.append(f"Node at index {idx} is missing a 'node_id'.")
            elif node_id in node_ids:
                errors.append(f"Duplicate node_id '{node_id}' found at index {idx}.")
            else:
                node_ids.add(node_id)

            menu_num = str(node_data.get("menu_number", "")).strip()
            if not menu_num:
                warnings.append(f"Node '{node_id or idx}' has no menu_number (e.g. '1.0').")
            elif menu_num in menu_numbers:
                warnings.append(f"Duplicate menu_number '{menu_num}' on node '{node_id}'.")
            else:
                menu_numbers.add(menu_num)

            title = str(node_data.get("title", "")).strip()
            if not title:
                errors.append(f"Node '{node_id or idx}' has an empty title.")

            # Validate options
            options = node_data.get("options", [])
            opt_nums: set[str] = set()
            for opt_idx, opt in enumerate(options):
                opt_num = str(opt.get("option_number", "")).strip()
                if not opt_num:
                    errors.append(f"Option {opt_idx + 1} in node '{node_id}' is missing 'option_number'.")
                elif opt_num in opt_nums:
                    errors.append(f"Duplicate option_number '{opt_num}' in node '{node_id}'.")
                else:
                    opt_nums.add(opt_num)

                btn_text = str(opt.get("button_text", "")).strip()
                if not btn_text:
                    errors.append(f"Option {opt_idx + 1} in node '{node_id}' has empty button_text.")
                elif len(btn_text) > 20:
                    warnings.append(
                        f"Option '{btn_text}' in node '{node_id}' has {len(btn_text)} chars. "
                        f"WhatsApp Quick Reply buttons truncate at 20 chars."
                    )
                elif len(btn_text) > 24:
                    warnings.append(
                        f"Option '{btn_text}' in node '{node_id}' exceeds WhatsApp List Title limit (24 chars)."
                    )

                target_type = opt.get("target_type", TARGET_NAVIGATE_MENU)
                target_id = str(opt.get("target_id", "")).strip()
                rag_prompt = str(opt.get("rag_prompt", "")).strip()

                if target_type == TARGET_TRIGGER_RAG and not rag_prompt:
                    errors.append(f"Option '{btn_text or opt_idx + 1}' in node '{node_id}' is set to TRIGGER_RAG but has no rag_prompt.")

        # Second pass: check dangling target_ids
        for node_data in config:
            node_id = str(node_data.get("node_id", "")).strip()
            options = node_data.get("options", [])
            for opt in options:
                target_type = opt.get("target_type", TARGET_NAVIGATE_MENU)
                target_id = str(opt.get("target_id", "")).strip()
                if target_type == TARGET_NAVIGATE_MENU and target_id:
                    if target_id not in node_ids:
                        errors.append(
                            f"Node '{node_id}' references unknown target_id '{target_id}'."
                        )

        # Validate root node
        effective_root = root_node_id or (config[0].get("node_id") if config else "")
        if effective_root and effective_root not in node_ids:
            errors.append(f"Specified root_node_id '{effective_root}' not found among graph nodes.")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "node_count": len(node_ids),
            "root_node_id": effective_root,
        }


