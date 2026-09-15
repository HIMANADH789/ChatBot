import json
import logging
import uuid
import time
from datetime import datetime, timezone
from typing import Optional

from app.db.mongodb import get_db
from app.db.collections import DOCUMENTS
from app.providers.base import EmbeddingProvider, LLMProvider, VectorStoreProvider
from app.utils.file_extractors import extract_text
from app.utils.chunking import recursive_chunk
from app.utils.query_cache import invalidate_client_cache
from app.services.bm25_search import bm25_registry

logger = logging.getLogger(__name__)


# ── Metadata extraction ───────────────────────────────────────────────────────

_METADATA_PROMPT = """Analyze this document excerpt and extract metadata as JSON.

Document name: {filename}
Content (first 2000 chars):
{content}

Return ONLY a JSON object with these fields:
{{
  "doc_type": "one of: fee_structure | syllabus | timetable | policy | result | admission | hostel | general",
  "tags": ["3 to 8 short topic tags relevant to the content"],
  "entities": {{
    "year": "1st | 2nd | 3rd | 4th | null",
    "semester": "1 | 2 | null",
    "department": "department name or null",
    "course": "course name or null",
    "category": "any other specific category or null"
  }}
}}
Return ONLY valid JSON. No explanation."""


async def _extract_doc_metadata(
    text: str, filename: str, llm: LLMProvider
) -> dict:
    """Use LLM to extract structured metadata from a document. Returns {} on failure."""
    try:
        response = await llm.generate(
            _METADATA_PROMPT.format(filename=filename, content=text[:2000]),
            temperature=0.0,
            max_tokens=300,
        )
        raw = response.text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        logger.warning(f"Metadata extraction failed for {filename}: {e}")
        return {}


def _build_chunk_metadata(
    doc_id: str,
    filename: str,
    chunk_index: int,
    doc_metadata: dict,
) -> dict:
    """Merge document-level metadata into per-chunk ChromaDB metadata."""
    entities: dict = doc_metadata.get("entities", {}) or {}
    meta = {
        "doc_id": doc_id,
        "filename": filename,
        "chunk_index": chunk_index,
        "doc_type": doc_metadata.get("doc_type", "general") or "general",
    }
    # Only store non-null entity values so ChromaDB filters work correctly
    for key, val in entities.items():
        if val and val != "null":
            meta[key] = val
    return meta


def _contextualize_chunks(chunks: list[str], filename: str, doc_metadata: dict) -> list[str]:
    """
    Prepend a context header to each chunk so both the embedding and the LLM
    receive document-level context alongside the raw text.

    Example header:
        [Source: Fee Structure 2024-25 | Type: fee_structure | Year: 2nd]
    """
    doc_title = filename.rsplit(".", 1)[0]  # strip extension
    parts = [f"Source: {doc_title}"]

    doc_type = doc_metadata.get("doc_type")
    if doc_type and doc_type != "general":
        parts.append(f"Type: {doc_type}")

    entities: dict = doc_metadata.get("entities", {}) or {}
    for key in ("year", "semester", "department", "course"):
        val = entities.get(key)
        if val and val != "null":
            parts.append(f"{key.capitalize()}: {val}")

    header = "[" + " | ".join(parts) + "]"
    return [f"{header}\n{chunk}" for chunk in chunks]


# ── Main service functions ────────────────────────────────────────────────────

async def upload_document(
    client_id: str,
    filename: str,
    file_bytes: bytes,
    embedding_provider: EmbeddingProvider,
    vectordb_provider: VectorStoreProvider,
    llm_provider: Optional[LLMProvider] = None,
) -> dict:
    db = get_db()
    doc_id = str(uuid.uuid4())
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"

    doc_record = {
        "doc_id": doc_id,
        "client_id": client_id,
        "filename": filename,
        "file_type": ext,
        "file_size_bytes": len(file_bytes),
        "status": "processing",
        "error_message": None,
        "chunks_count": 0,
        "uploaded_at": datetime.now(timezone.utc),
        "processed_at": None,
        "chunks": [],
    }
    await db[DOCUMENTS].insert_one(doc_record)

    try:
        start = time.time()

        # 1. Extract text
        text = extract_text(file_bytes, filename)
        if not text.strip():
            raise ValueError("No text content found in file")

        # 2. Chunk
        raw_chunks = recursive_chunk(text)
        if not raw_chunks:
            raise ValueError("No chunks produced from file content")

        # 3. Extract document-level metadata (optional — requires LLM)
        doc_metadata: dict = {}
        if llm_provider:
            doc_metadata = await _extract_doc_metadata(text, filename, llm_provider)
            logger.info(f"Extracted metadata for {filename}: {doc_metadata}")

        # 4. Contextualize chunks (add document header to each)
        chunks = _contextualize_chunks(raw_chunks, filename, doc_metadata)

        # 5. Embed contextualized chunks
        embeddings = await embedding_provider.embed_texts(chunks)

        # 6. Build per-chunk metadata (includes entity tags for filtering)
        metadatas = [
            _build_chunk_metadata(doc_id, filename, i, doc_metadata)
            for i in range(len(chunks))
        ]

        # 7. Store in vector DB
        await vectordb_provider.add_documents(
            client_id=client_id,
            doc_id=doc_id,
            chunks=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        processing_time = int((time.time() - start) * 1000)

        await db[DOCUMENTS].update_one(
            {"doc_id": doc_id},
            {
                "$set": {
                    "status": "ready",
                    "chunks_count": len(chunks),
                    "processing_time_ms": processing_time,
                    "processed_at": datetime.now(timezone.utc),
                    "chunks": raw_chunks,  # store raw (no header) for readability
                    "doc_metadata": doc_metadata,
                }
            },
        )

        # Invalidate semantic cache and BM25 index for this client since knowledge base changed
        await invalidate_client_cache(client_id)
        bm25_registry.invalidate(client_id)

        doc_record.update(
            status="ready",
            chunks_count=len(chunks),
            processed_at=datetime.now(timezone.utc),
        )
        return doc_record

    except Exception as e:
        await db[DOCUMENTS].update_one(
            {"doc_id": doc_id},
            {"$set": {"status": "failed", "error_message": str(e)}},
        )
        raise


async def list_documents(client_id: str) -> list[dict]:
    db = get_db()
    query = {"client_id": client_id}

    cursor = db[DOCUMENTS].find(
        query,
        {"chunks": 0},
    ).sort("uploaded_at", -1)
    return await cursor.to_list(length=100)


async def delete_document(
    client_id: str,
    doc_id: str,
    vectordb_provider: VectorStoreProvider,
) -> bool:
    db = get_db()
    result = await db[DOCUMENTS].delete_one(
        {"doc_id": doc_id, "client_id": client_id}
    )
    if result.deleted_count == 0:
        return False
    await vectordb_provider.delete_document(client_id, doc_id)
    # Invalidate cache and BM25 index since knowledge base changed
    await invalidate_client_cache(client_id)
    bm25_registry.invalidate(client_id)
    return True
