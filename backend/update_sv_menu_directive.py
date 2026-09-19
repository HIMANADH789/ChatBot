import asyncio
from app.db.mongodb import connect_db, get_db, close_db
from app.db.collections import CLIENTS
from app.services.profile_compiler import _PROFILE_CACHE

async def main():
    await connect_db()
    db = get_db()
    client_id = "sv_professionals"
    
    client = await db[CLIENTS].find_one({"client_id": client_id})
    if not client:
        print(f"Client {client_id} not found.")
        await close_db()
        return

    # Unified MenuGraph nodes for sv_professionals
    menu_graph_nodes = [
        {
            "node_id": "MENU_ROOT",
            "menu_number": "1.0",
            "title": "Courses & Offerings",
            "descriptor_tag": "Display at start of conversation or initial greeting, or when user explicitly asks for courses or menu list",
            "whatsapp_media": {
                "image_url": "https://tse3.mm.bing.net/th/id/OIP.tkuIPIq9h-M1UjaIgJCDWwHaHa?r=0&rs=1&pid=ImgDetMain&o=7&rm=3",
                "caption": "Welcome to SV Professional Institute"
            },
            "frequency": "on_intent",
            "options": [
                {
                    "option_number": "1",
                    "button_text": "Commerce / CA",
                    "target_type": "NAVIGATE_MENU",
                    "target_id": "MENU_COMMERCE"
                },
                {
                    "option_number": "2",
                    "button_text": "Admissions Info",
                    "target_type": "TRIGGER_RAG",
                    "rag_prompt": "What are the admission requirements, fee structure, and application process at SV Professional Institute?"
                }
            ]
        },
        {
            "node_id": "MENU_COMMERCE",
            "menu_number": "1.1",
            "title": "Commerce & Professional Programs",
            "descriptor_tag": "When user inquires specifically about Commerce or CA professional programs",
            "whatsapp_media": {
                "image_url": "",
                "caption": "Commerce Stream Brochure"
            },
            "frequency": "on_intent",
            "options": [
                {
                    "option_number": "1",
                    "button_text": "CA Foundation",
                    "target_type": "TRIGGER_RAG",
                    "rag_prompt": "What is the fee structure and syllabus for CA Foundation?"
                },
                {
                    "option_number": "2",
                    "button_text": "CA Intermediate",
                    "target_type": "TRIGGER_RAG",
                    "rag_prompt": "What is the eligibility and course structure for CA Intermediate?"
                }
            ]
        }
    ]

    context_images = [
        {
            "id": "f79aebba-6180-4fee-af67-b104595e45d7",
            "title": "Finance & Accounting",
            "image_path": "https://drive.google.com/file/d/1tV_nFbzA2PKgp1azvxrN2uUdpmvNIkwm/view",
            "descriptor_tag": "Display when user inquires about Finance and Accounting F&A course brochure, fee structure, or syllabus",
            "caption": "Finance & Accounting Program Overview",
            "frequency": "on_intent"
        },
        {
            "id": "d39e2337-7d12-4df2-bc38-70fe2439852b",
            "title": "HR",
            "image_path": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQXFFUZvbIJQpodMqCtURu1w_oaXUj1_d9EzodJSF0DrEpnr6uHJ2UeCS8&s=10",
            "descriptor_tag": "Display when user inquires about HR Human Resources course brochure, fee structure, or syllabus",
            "caption": "HR Course Overview",
            "frequency": "on_intent"
        }
    ]

    settings = client.get("settings", {})
    setups = settings.get("setups", {})
    for ch, s_cfg in setups.items():
        if isinstance(s_cfg, dict):
            s_cfg["menu_graph_nodes"] = menu_graph_nodes
            s_cfg["context_images"] = context_images
            if "menu_tree" in s_cfg:
                del s_cfg["menu_tree"]

    # Unset legacy menu_tree from root settings as well
    await db[CLIENTS].update_one(
        {"client_id": client_id},
        {
            "$set": {
                "settings.menu_graph_nodes": menu_graph_nodes,
                "settings.menu_graph_root_node_id": "MENU_ROOT",
                "settings.context_images": context_images,
                "settings.setups": setups,
            },
            "$unset": {
                "settings.menu_tree": "",
                "menu_tree": ""
            }
        }
    )
    _PROFILE_CACHE.clear()
    print("Successfully migrated sv_professionals DB settings to unified MenuGraph architecture & cleared profile cache.")
    await close_db()

if __name__ == "__main__":
    asyncio.run(main())
