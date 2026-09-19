import uuid
from datetime import datetime, timezone

from app.db.mongodb import get_db
from app.db.collections import CHAT_SESSIONS


async def get_or_create_session(client_id: str, session_id: str | None) -> str:
    db = get_db()
    if session_id:
        session = await db[CHAT_SESSIONS].find_one({"session_id": session_id})
        if session:
            return session_id

    # Create new session
    new_id = session_id or str(uuid.uuid4())
    await db[CHAT_SESSIONS].insert_one({
        "session_id": new_id,
        "client_id": client_id,
        "messages": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    return new_id


async def add_message(session_id: str, role: str, content: str, sources: list | None = None):
    db = get_db()
    message = {
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc),
    }
    if sources:
        message["sources"] = sources

    await db[CHAT_SESSIONS].update_one(
        {"session_id": session_id},
        {
            "$push": {"messages": message},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )


async def get_history(session_id: str, max_turns: int = 5) -> list[dict]:
    db = get_db()
    session = await db[CHAT_SESSIONS].find_one({"session_id": session_id})
    if not session:
        return []
    messages = session.get("messages", [])
    # Return last N turns (each turn = user + assistant = 2 messages)
    return messages[-(max_turns * 2):]


async def count_session_queries(session_id: str) -> int:
    """Return the number of user messages (queries) in a session."""
    db = get_db()
    session = await db[CHAT_SESSIONS].find_one({"session_id": session_id})
    if not session:
        return 0
    messages = session.get("messages", [])
    return sum(1 for m in messages if m.get("role") == "user")


async def clear_session_history(session_id: str):
    """Clear all messages from a chat session to completely reload the session."""
    db = get_db()
    await db[CHAT_SESSIONS].update_one(
        {"session_id": session_id},
        {
            "$set": {
                "messages": [],
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
