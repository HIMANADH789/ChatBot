"""
Layer 4: In-Memory Sparse BM25 Keyword Search Engine

Provides fast BM25 token-based sparse retrieval per tenant.
Allows exact-term matching (e.g. course codes, fees, specific dates, eligibility)
to complement dense vector embeddings via Hybrid Search & Reciprocal Rank Fusion (RRF).
"""
from __future__ import annotations

import math
import re
import logging
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from app.db.mongodb import get_db
from app.db.collections import DOCUMENTS

logger = logging.getLogger(__name__)

# BM25 Hyperparameters
K1 = 1.5
B = 0.75
RRF_K = 60


def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase alphanumeric tokens."""
    if not text:
        return []
    return re.findall(r"\b[a-zA-Z0-9_\-\.]{2,}\b", text.lower())


class TenantBM25Index:
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.corpus: List[Dict[str, Any]] = []  # [{ "id": chunk_id, "text": text, "metadata": meta, "tokens": [...] }]
        self.doc_lengths: List[int] = []
        self.avg_doc_len: float = 0.0
        self.doc_freqs: Dict[str, int] = defaultdict(int)
        self.total_docs: int = 0
        self.is_indexed: bool = False

    def build_index(self, chunks: List[Dict[str, Any]]) -> None:
        self.corpus = []
        self.doc_lengths = []
        self.doc_freqs.clear()
        self.total_docs = len(chunks)

        if not chunks:
            self.avg_doc_len = 0.0
            self.is_indexed = True
            return

        total_len = 0
        for chunk in chunks:
            text = chunk.get("text", "")
            tokens = _tokenize(text)
            doc_len = len(tokens)
            total_len += doc_len
            self.doc_lengths.append(doc_len)

            unique_tokens = set(tokens)
            for token in unique_tokens:
                self.doc_freqs[token] += 1

            self.corpus.append({
                "id": chunk.get("id", ""),
                "text": text,
                "metadata": chunk.get("metadata", {}),
                "token_counts": Counter(tokens),
            })

        self.avg_doc_len = total_len / max(self.total_docs, 1)
        self.is_indexed = True

    def search(self, query: str, top_k: int = 25) -> List[Dict[str, Any]]:
        if not self.is_indexed or self.total_docs == 0:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scores: List[Tuple[int, float]] = []

        for idx, doc in enumerate(self.corpus):
            doc_len = self.doc_lengths[idx]
            token_counts = doc["token_counts"]
            score = 0.0

            for qt in query_tokens:
                if qt in token_counts:
                    tf = token_counts[qt]
                    df = self.doc_freqs.get(qt, 0)
                    # Lucene / Robertson BM25 IDF formulation
                    idf = math.log(1.0 + (self.total_docs - df + 0.5) / (df + 0.5))
                    # Term frequency saturation
                    num = tf * (K1 + 1.0)
                    denom = tf + K1 * (1.0 - B + B * (doc_len / max(self.avg_doc_len, 1.0)))
                    score += idf * (num / denom)

            if score > 0.0:
                scores.append((idx, score))

        # Sort by BM25 score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        top_results = scores[:top_k]

        results = []
        for idx, score in top_results:
            doc = self.corpus[idx]
            results.append({
                "id": doc["id"],
                "text": doc["text"],
                "metadata": doc["metadata"],
                "score": float(score),
            })
        return results


def _safe_get_db():
    try:
        return get_db()
    except Exception:
        return None


class BM25Registry:
    """Registry maintaining in-memory BM25 indices per tenant."""
    def __init__(self):
        self._indices: Dict[str, TenantBM25Index] = {}

    def get_index(self, client_id: str) -> TenantBM25Index:
        if client_id not in self._indices:
            self._indices[client_id] = TenantBM25Index(client_id)
        return self._indices[client_id]

    async def ensure_indexed(self, client_id: str) -> TenantBM25Index:
        index = self.get_index(client_id)
        if not index.is_indexed:
            await self.rebuild_index(client_id)
        return index

    async def rebuild_index(self, client_id: str) -> None:
        db = _safe_get_db()
        chunks = []
        if db is not None:
            cursor = db[DOCUMENTS].find({"client_id": client_id, "status": "processed"})
            docs = await cursor.to_list(length=1000)
            for doc in docs:
                doc_id = str(doc.get("_id", doc.get("doc_id", "")))
                filename = doc.get("filename", "")
                for i, chunk_text in enumerate(doc.get("chunks", [])):
                    chunks.append({
                        "id": f"{doc_id}_chunk_{i}",
                        "text": chunk_text,
                        "metadata": {
                            "doc_id": doc_id,
                            "filename": filename,
                            "chunk_index": i,
                        },
                    })

        index = self.get_index(client_id)
        index.build_index(chunks)
        logger.info("BM25 index built for tenant '%s' with %d chunks", client_id, len(chunks))

    def invalidate(self, client_id: str) -> None:
        if client_id in self._indices:
            del self._indices[client_id]


bm25_registry = BM25Registry()


def reciprocal_rank_fusion(
    dense_results: List[Dict[str, Any]],
    sparse_results: List[Dict[str, Any]],
    top_k: int = 25,
    dense_weight: float = 0.6,
    sparse_weight: float = 0.4,
) -> List[Dict[str, Any]]:
    """
    Fuses dense vector results and sparse BM25 results using Reciprocal Rank Fusion (RRF).
    RRF_score(d) = sum_m ( weight_m / (RRF_K + rank_m(d)) )
    """
    fused_scores: Dict[str, float] = defaultdict(float)
    chunk_map: Dict[str, Dict[str, Any]] = {}

    def get_chunk_key(item: Dict[str, Any]) -> str:
        meta = item.get("metadata", {})
        doc_id = str(meta.get("doc_id", ""))
        chunk_idx = str(meta.get("chunk_index", ""))
        if doc_id:
            return f"{doc_id}_{chunk_idx}"
        return item.get("id") or item.get("text", "")[:50]

    # Dense rankings
    for rank, item in enumerate(dense_results):
        key = get_chunk_key(item)
        fused_scores[key] += dense_weight / (RRF_K + rank + 1)
        if key not in chunk_map:
            chunk_map[key] = item

    # Sparse rankings
    for rank, item in enumerate(sparse_results):
        key = get_chunk_key(item)
        fused_scores[key] += sparse_weight / (RRF_K + rank + 1)
        if key not in chunk_map:
            chunk_map[key] = item

    # Sort items by fused RRF score
    sorted_keys = sorted(fused_scores.keys(), key=lambda k: fused_scores[k], reverse=True)

    fused_candidates = []
    for k in sorted_keys[:top_k]:
        candidate = dict(chunk_map[k])
        candidate["score"] = fused_scores[k]
        fused_candidates.append(candidate)

    return fused_candidates
