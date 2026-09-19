import asyncio
from app.db.mongodb import connect_db, get_db, close_db
from app.db.collections import CLIENTS
from app.services.profile_compiler import invalidate_client_profile

async def main():
    await connect_db()
    db = get_db()
    client_id = "sv_professionals"
    
    client = await db[CLIENTS].find_one({"client_id": client_id})
    if not client:
        print(f"Client {client_id} not found.")
        await close_db()
        return

    # Update context_images to include CA / Commerce Overview image
    context_images = [
        {
            "id": "ca_commerce_brochure",
            "title": "Commerce & CA Programs",
            "image_path": "https://tse3.mm.bing.net/th/id/OIP.tkuIPIq9h-M1UjaIgJCDWwHaHa?r=0&rs=1&pid=ImgDetMain&o=7&rm=3",
            "descriptor_tag": "Display when user inquires about CA Chartered Accountancy, CA Foundation, CA Intermediate, or Commerce course brochure, overview, or details",
            "caption": "Commerce & CA Programs Overview",
            "frequency": "on_intent"
        },
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
    settings["context_images"] = context_images

    # Update setups.whatsapp context_images and clean MENU_COMMERCE media caption if image_url is empty
    setups = settings.get("setups", {})
    for ch, s_cfg in setups.items():
        if isinstance(s_cfg, dict):
            s_cfg["context_images"] = context_images
            nodes = s_cfg.get("menu_graph_nodes", [])
            for n in nodes:
                if n.get("node_id") == "MENU_COMMERCE":
                    if not n.get("whatsapp_media", {}).get("image_url"):
                        n["whatsapp_media"] = {"image_url": "", "caption": ""}

    await db[CLIENTS].update_one(
        {"client_id": client_id},
        {"$set": {
            "settings": settings,
            "updated_at": client.get("updated_at")
        }}
    )
    print("Successfully updated sv_professionals context images and menu graph nodes.")

    invalidate_client_profile(client_id)
    print("Invalidated compiled profile cache for sv_professionals.")

    await close_db()

if __name__ == "__main__":
    asyncio.run(main())
