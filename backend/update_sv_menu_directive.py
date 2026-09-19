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

    settings = client.get("settings", {})
    menu_tree = settings.get("menu_tree", [])
    
    tag = "Display at start of conversation or initial greeting, or when user explicitly asks for courses or menu list"
    
    if menu_tree and len(menu_tree) > 0:
        menu_tree[0]["descriptor_tag"] = tag
        print("Updated menu_tree[0] descriptor_tag to:", tag)

    menu_graph_nodes = settings.get("menu_graph_nodes", [])
    if menu_graph_nodes and len(menu_graph_nodes) > 0:
        menu_graph_nodes[0]["descriptor_tag"] = tag
        print("Updated menu_graph_nodes[0] descriptor_tag to:", tag)

    context_images = settings.get("context_images", [])
    for img in context_images:
        if "Finance" in img.get("title", ""):
            img["descriptor_tag"] = "Display once per session when user asks about Finance and Accounting F&A course details, fees, or syllabus"
        elif "HR" in img.get("title", ""):
            img["descriptor_tag"] = "Display once per session when user asks about HR Human Resources course details, fees, or syllabus"

    # Also update setups dict if present
    setups = settings.get("setups", {})
    for ch, s_cfg in setups.items():
        if isinstance(s_cfg, dict):
            s_cfg["menu_tree"] = menu_tree
            s_cfg["menu_graph_nodes"] = menu_graph_nodes
            s_cfg["context_images"] = context_images

    await db[CLIENTS].update_one(
        {"client_id": client_id},
        {"$set": {
            "settings.menu_tree": menu_tree,
            "settings.menu_graph_nodes": menu_graph_nodes,
            "settings.context_images": context_images,
            "settings.setups": setups,
        }}
    )
    _PROFILE_CACHE.clear()
    print("Successfully updated DB settings & cleared profile cache for sv_professionals.")
    await close_db()

if __name__ == "__main__":
    asyncio.run(main())
