import pytest
from app.core.menu_graph import MenuGraph, TARGET_NAVIGATE_MENU, TARGET_TRIGGER_RAG, FREQ_ALWAYS, FREQ_ONLY_ONCE

def test_menu_graph_validation_valid():
    nodes = [
        {
            "node_id": "MENU_ROOT",
            "menu_number": "1.0",
            "title": "Main Menu",
            "options": [
                {
                    "option_number": "1",
                    "button_text": "Admissions",
                    "target_type": TARGET_NAVIGATE_MENU,
                    "target_id": "MENU_ADMISSIONS",
                },
                {
                    "option_number": "2",
                    "button_text": "Ask AI",
                    "target_type": TARGET_TRIGGER_RAG,
                    "rag_prompt": "Tell me about courses",
                },
            ],
        },
        {
            "node_id": "MENU_ADMISSIONS",
            "menu_number": "1.1",
            "title": "Admissions Menu",
            "whatsapp_media": {
                "image_url": "https://example.com/admissions.jpg",
                "caption": "Admissions 2026",
            },
            "frequency": FREQ_ONLY_ONCE,
            "options": [
                {
                    "option_number": "1",
                    "button_text": "Fee Structure",
                    "target_type": TARGET_TRIGGER_RAG,
                    "rag_prompt": "What are the admission fees?",
                }
            ],
        },
    ]

    res = MenuGraph.validate_config(nodes, root_node_id="MENU_ROOT")
    assert res["valid"] is True
    assert len(res["errors"]) == 0
    assert res["node_count"] == 2
    assert res["root_node_id"] == "MENU_ROOT"


def test_menu_graph_validation_dangling_target_id():
    nodes = [
        {
            "node_id": "MENU_ROOT",
            "menu_number": "1.0",
            "title": "Main Menu",
            "options": [
                {
                    "option_number": "1",
                    "button_text": "Non-existent",
                    "target_type": TARGET_NAVIGATE_MENU,
                    "target_id": "DOES_NOT_EXIST",
                }
            ],
        }
    ]

    res = MenuGraph.validate_config(nodes, root_node_id="MENU_ROOT")
    assert res["valid"] is False
    assert any("DOES_NOT_EXIST" in err for err in res["errors"])


def test_menu_graph_validation_missing_rag_prompt():
    nodes = [
        {
            "node_id": "MENU_ROOT",
            "menu_number": "1.0",
            "title": "Main Menu",
            "options": [
                {
                    "option_number": "1",
                    "button_text": "AI Info",
                    "target_type": TARGET_TRIGGER_RAG,
                    "rag_prompt": "",
                }
            ],
        }
    ]

    res = MenuGraph.validate_config(nodes, root_node_id="MENU_ROOT")
    assert res["valid"] is False
    assert any("rag_prompt" in err for err in res["errors"])


def test_menu_graph_validation_whatsapp_button_length_warning():
    nodes = [
        {
            "node_id": "MENU_ROOT",
            "menu_number": "1.0",
            "title": "Main Menu",
            "options": [
                {
                    "option_number": "1",
                    "button_text": "This button text is way too long for whatsapp",
                    "target_type": TARGET_TRIGGER_RAG,
                    "rag_prompt": "Help",
                }
            ],
        }
    ]

    res = MenuGraph.validate_config(nodes, root_node_id="MENU_ROOT")
    assert res["valid"] is True
    assert len(res["warnings"]) > 0
    assert any("20 chars" in w for w in res["warnings"])
