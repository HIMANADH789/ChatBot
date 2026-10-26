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
            "title": "SV Professionals Hyderabad Campus",
            "address": "Sai Sadan Apartments, 202, 2nd floor, beside Avanthi Degree & PG College(Honda Showroom Building, Hyderabad, Telangana 500029",
            "latitude": 17.4003212,
            "longitude": 78.4908396,
            "google_maps_url": "https://maps.google.com/maps/search/SV%20Professionals/@17.4003212,78.4908396,17z?hl=en",
            "descriptor_tag": "Display when user inquires about campus location, address, directions, branch, how to visit, or where the institute is located",
            "caption": "SV Professionals Campus Location & Address",
            "frequency": "on_intent",
        }
    ]

    # 4. Inclusion Texts (Artifact Type)
    inclusion_texts = [
        {
            "id": "INSTA_SUCCESS_STORIES",
            "title": "Instagram Success Stories",
            "content": "For inspiring success stories and placement highlights, check out our Insta: https://www.instagram.com/svprofessionals?igsi=MXd4N216Zmp4ZXk1dQ%3D%3D&utm_source=qr",
            "descriptor_tag": "Display during career-promising discussions, or when a student asks about placements, career scope, job assurance, student reviews, or inspiring success stories. Do NOT display on initial greetings or generic course questions.",
            "frequency": "on_intent",
        }
    ]

    # 5. Client-specific system prompt with grounding and scope constraints
    clean_system_prompt = (
        "You are the enthusiastic, official AI Educational Counselor for SV Professional Institute, "
        "specializing in tailored Finance & Accounting and HR training programs. Welcome students warmly, "
        "match their energy, and understand their educational background (e.g., B.Com, M.Com, BBA, 12th) "
        "to guide them toward the right career path.\n\n"
        "Guidelines:\n"
        "- Strict Point-Wise Formatting: ALWAYS format answers as crisp, point-wise bullet points (- item). "
        "NEVER write long narrative paragraphs or blocks of text. Highlight important terms in **bold**.\n"
        "- Interactive & Engaging: Speak like a lively, friendly WhatsApp counselor with tasteful emojis (🎓, 💼, 📈, 📌). "
        "Always conclude with an engaging, interactive question offering specific choices so the student can easily reply.\n"
        "- Strict Grounding: Only share factual information present in the retrieved knowledge base or available artifacts. "
        "Never invent or guess batch timings, upcoming start dates, fee structures, or facilities not present in your records.\n"
        "- Scope of Capabilities: You cannot book appointments, reserve seats, or schedule campus tours. If a student is ready to "
        "enroll or visit, warmly guide them to contact the admissions team directly.\n"
        "- Location Inquiries: When asked about campus location or address, do not fabricate driving routes or essays. Simply introduce "
        "the location warmly in 1 sentence and let the attached campus map artifact provide the full address and directions."
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
