import asyncio
import logging
from dotenv import load_dotenv

load_dotenv("c:/ChatX/backend/.env")

from app.db.mongodb import get_db, connect_db, close_db
from app.services.profile_compiler import compile_client_profile, invalidate_client_profile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("update_brochures")

NEW_CONTEXT_IMAGES = [
    {
        "id": "IMG_FINANCE",
        "title": "Finance & Accounting Course Brochure",
        "image_path": "https://drive.google.com/file/d/1tV_nFbzA2PKgp1azvxrN2uUdpmvNIkwm/view",
        "descriptor_tag": "Send when the user indicates interest in Finance, chooses 'Finance side', asks about Finance & Accounting, or requests course details/syllabus/brochure. IMPORTANT: Send ONLY ONCE upon initial course selection or interest; do NOT re-send repeatedly across subsequent messages in the conversation.",
        "caption": "SV Professionals - Finance & Accounting Program Overview",
        "frequency": "on_intent",
    },
    {
        "id": "IMG_HR",
        "title": "HR (Human Resources) Course Brochure",
        "image_path": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQXFFUZvbIJQpodMqCtURu1w_oaXUj1_d9EzodJSF0DrEpnr6uHJ2UeCS8&s=10",
        "descriptor_tag": "Send when the user indicates interest in HR, chooses 'HR side', asks about Human Resources, or requests course details/syllabus/brochure. IMPORTANT: Send ONLY ONCE upon initial course selection or interest; do NOT re-send repeatedly across subsequent messages in the conversation.",
        "caption": "SV Professionals - Human Resources Program Overview",
        "frequency": "on_intent",
    },
]

async def run():
    await connect_db()
    db = get_db()

    client = await db["clients"].find_one({"client_id": "sv_professionals"})
    if not client:
        logger.error("Client sv_professionals not found!")
        await close_db()
        return

    update_doc = {
        "settings.context_images": NEW_CONTEXT_IMAGES,
    }

    setups = client.get("settings", {}).get("setups", {})
    for channel, cfg in setups.items():
        if isinstance(cfg, dict) and "context_images" in cfg:
            update_doc[f"settings.setups.{channel}.context_images"] = NEW_CONTEXT_IMAGES

    res = await db["clients"].update_one(
        {"client_id": "sv_professionals"},
        {"$set": update_doc}
    )
    logger.info("Updated sv_professionals client context_images: matched=%s, modified=%s", res.matched_count, res.modified_count)

    invalidate_client_profile("sv_professionals")
    for channel in ["whatsapp", "widget", "web_api"]:
        compiled = await compile_client_profile("sv_professionals", channel)
        logger.info("Recompiled profile for channel %s (v:%s)", channel, compiled.get("version_hash"))
        print(f"\n--- CATALOG FOR {channel.upper()} ---")
        prompt = compiled.get("compiled_system_prompt", "")
        # print the catalog portion of the prompt
        if "AVAILABLE ARTIFACTS" in prompt:
            print(prompt[prompt.find("AVAILABLE ARTIFACTS"):prompt.find("CLIENT-DEFINED") if "CLIENT-DEFINED" in prompt else len(prompt)])

    await close_db()

if __name__ == "__main__":
    asyncio.run(run())
