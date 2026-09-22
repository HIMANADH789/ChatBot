from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import sys

from app.config import settings

if sys.platform == "win32":
    try:
        import dns.resolver
        dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
        dns.resolver.default_resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
    except Exception:
        pass

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_db() -> None:
    global _client, _db

    uri = settings.MONGODB_URI

    _client = AsyncIOMotorClient(
        uri,
        maxPoolSize=50,
        minPoolSize=10,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=10000,
        socketTimeoutMS=10000,
        tls=True,
        tlsAllowInvalidCertificates=False,
    )

    await _client.admin.command("ping")
    _db = _client[settings.MONGODB_DB_NAME]


async def close_db() -> None:
    global _client, _db
    if _client:
        _client.close()
    _client = None
    _db = None


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialized. Call connect_db() first.")
    return _db
