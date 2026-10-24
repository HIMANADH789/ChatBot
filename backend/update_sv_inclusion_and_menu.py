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

    # 1. Enhanced MenuGraph nodes with clear, emphatic descriptor tags
    menu_graph_nodes = [
        {
            "node_id": "MENU_ROOT",
            "menu_number": "1.0",
            "title": "Courses & Offerings",
            "descriptor_tag": (
                "MANDATORY: Always display in the first message / initial greeting of a conversation or session "
                "so the visitor can immediately explore our available course options (Finance & Accounting, HR, Experienced). "
                "Also display whenever user inquires about or suggests interest in exploring our courses, training programs, "
                "what we offer, or asks for the menu."
            ),
            "whatsapp_media": {
                "image_url": "https://tse3.mm.bing.net/th/id/OIP.tkuIPIq9h-M1UjaIgJCDWwHaHa?r=0&rs=1&pid=ImgDetMain&o=7&rm=3",
                "caption": "Welcome to SV Professional Institute"
            },
            "frequency": "on_intent",
            "options": [
                {
                    "option_number": "1",
                    "button_text": "Finance & Accounting",
                    "target_type": "TRIGGER_RAG",
                    "rag_prompt": "Tell about Finance and accounting course"
                },
                {
                    "option_number": "2",
                    "button_text": "HR",
                    "target_type": "TRIGGER_RAG",
                    "rag_prompt": "Tell about HR course"
                },
                {
                    "option_number": "3",
                    "button_text": "Experienced",
                    "target_type": "TRIGGER_RAG",
                    "rag_prompt": "Tell the courses provided for experienced professionals"
                }
            ]
        },
        {
            "node_id": "MENU_COMMERCE",
            "menu_number": "1.1",
            "title": "Commerce & Professional Programs",
            "descriptor_tag": "Display when user inquires specifically about Chartered Accountancy, Commerce, CA Foundation, or CA Intermediate professional programs",
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

    # 2. Context Images
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

    # 3. Context Maps
    context_maps = [
        {
            "id": "sv_campus_location",
            "title": "SV Professionals",
            "address": "SV Professionals, Beside Ameerpet Metro Station, Ameerpet, Hyderabad, Telangana 500038",
            "latitude": 17.4003212,
            "longitude": 78.4908396,
            "google_maps_url": "https://maps.app.goo.gl/UmU6RZw3iHLQuQYs8",
            "descriptor_tag": "Show when asked by user for location, address, campus, directions, branch, or how to visit",
            "caption": "SV Professionals Hyderabad Campus Location",
            "frequency": "on_intent",
        }
    ]

    # 4. Inclusion Texts (New Artifact Type)
    inclusion_texts = [
        {
            "id": "INSTA_SUCCESS_STORIES",
            "title": "Instagram Success Stories",
            "content": "For inspiring success stories, check out our InstaId: https://www.instagram.com/svprofessionals?igsi=MXd4N216Zmp4ZXk1dQ%3D%3D&utm_source=qr",
            "descriptor_tag": "Display at the end of initial greetings or whenever a student inquires about student reviews, placements, achievements, or success stories",
            "frequency": "on_intent",
        }
    ]

    # 5. Clean system prompt without hardcoded instagram suffix
    clean_system_prompt = (
        "You are the official AI Front Desk Assistant & Educational Counselor for SV Professional Institute, "
        "a premier coaching academy specializing in tailored finance and HR training programs. Welcome every student warmly, "
        "match their energy with an encouraging and warm tone, and actively ask about their current educational background "
        "to guide them toward the right curated finance or HR career path. Provide clear, informative responses ranging between "
        "7 to 9 sentences, keeping them concise and perfectly optimized for mobile WhatsApp reading without using any raw markdown "
        "headers or code blocks. Draw freely upon your domain expertise to explain broad industry scopes, core modules, and professional "
        "pathways for our diverse training streams. If specific factual data like exact fee structures or localized timetables are absent "
        "from your immediate records, politely direct the student to connect with our administrative desk for the latest updates. "
        "Conclude your response with an engaging, forward-looking question to help the student explore their best career fit."
    )

    settings = client.get("settings", {})
    setups = settings.get("setups", {})
    for ch, s_cfg in setups.items():
        if isinstance(s_cfg, dict):
            s_cfg["system_prompt"] = clean_system_prompt
            s_cfg["menu_graph_nodes"] = menu_graph_nodes
            s_cfg["context_images"] = context_images
            s_cfg["context_maps"] = context_maps
            s_cfg["inclusion_texts"] = inclusion_texts
            s_cfg["context_mode"] = "adaptive"
            s_cfg["context_instructions"] = (
                "Track student name, educational qualification (e.g. B.Com/M.Com/BBA/12th), "
                "interested course domain (e.g. Finance & Accounting, Human Resources, or CA), and experience level. "
                "When a student's profile indicates B.Com or Finance & Accounting interest, answer fee structure, "
                "eligibility, syllabus, and placement inquiries specifically for Finance & Accounting."
            )
            if "menu_tree" in s_cfg:
                del s_cfg["menu_tree"]

    # Update in MongoDB
    await db[CLIENTS].update_one(
        {"client_id": client_id},
        {
            "$set": {
                "settings.system_prompt": clean_system_prompt,
                "settings.menu_graph_nodes": menu_graph_nodes,
                "settings.menu_graph_root_node_id": "MENU_ROOT",
                "settings.context_images": context_images,
                "settings.context_maps": context_maps,
                "settings.inclusion_texts": inclusion_texts,
                "settings.context_mode": "adaptive",
                "settings.context_instructions": (
                    "Track student name, educational qualification (e.g. B.Com/M.Com/BBA/12th), "
                    "interested course domain (e.g. Finance & Accounting, Human Resources, or CA), and experience level. "
                    "When a student's profile indicates B.Com or Finance & Accounting interest, answer fee structure, "
                    "eligibility, syllabus, and placement inquiries specifically for Finance & Accounting."
                ),
                "settings.setups": setups,
            },
            "$unset": {
                "settings.menu_tree": "",
                "menu_tree": "",
                "settings.compiled_profiles": "",
            }
        }
    )
    _PROFILE_CACHE.clear()
    print("Successfully updated sv_professionals with enhanced MENU_ROOT descriptor, inclusion_texts, cleaned prompt & cleared profile cache.")
    await close_db()

if __name__ == "__main__":
    asyncio.run(main())
