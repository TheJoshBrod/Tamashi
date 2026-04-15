"""Qdrant embedded vector store for Phase 3 GraphRAG retrieval.

Uses qdrant-client[fastembed] — local embeddings, no external API call.
Collection: "tamashi_memory"
Shared key with the Jac graph: payload["node_id"] == str(jid(fact_node))
"""
from __future__ import annotations

import hashlib
import logging

from core.config import settings

log = logging.getLogger(__name__)

_COLLECTION = "tamashi_memory"
_EMBED_MODEL = "BAAI/bge-small-en-v1.5"


class QdrantMemoryStore:
    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(path=settings.vector_db_path)
            self._ensure_collection()
        return self._client

    def _ensure_collection(self) -> None:
        """Create the collection if it doesn't exist yet."""
        from qdrant_client.models import Distance, VectorParams
        from fastembed import TextEmbedding
        client = self._client
        existing = [c.name for c in client.get_collections().collections]
        if _COLLECTION not in existing:
            # Determine vector size from the embedding model
            model = TextEmbedding(model_name=_EMBED_MODEL)
            sample = list(model.embed(["probe"]))[0]
            size = len(sample)
            client.create_collection(
                collection_name=_COLLECTION,
                vectors_config=VectorParams(size=size, distance=Distance.COSINE),
            )

    def _embed(self, text: str) -> list[float]:
        from fastembed import TextEmbedding
        model = TextEmbedding(model_name=_EMBED_MODEL)
        return list(model.embed([text]))[0].tolist()

    def upsert(self, node_id: str, user_id: str, kind: str, text: str) -> None:
        """Embed text and upsert a point keyed by node_id (jac jid string).

        Uses a stable integer point ID derived from node_id so re-ingestion
        is idempotent (same fact → same point → overwrites instead of duplicating).
        """
        if not text or not text.strip():
            return
        try:
            from qdrant_client.models import PointStruct
            client = self._get_client()
            point_id = int(hashlib.md5(node_id.encode()).hexdigest(), 16) % (2 ** 63)
            client.upsert(
                collection_name=_COLLECTION,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=self._embed(text),
                        payload={
                            "node_id": node_id,
                            "user_id": user_id,
                            "kind": kind,
                            "text": text,
                        },
                    )
                ],
            )
        except Exception:
            log.exception("vector upsert failed for node %s", node_id)

    def search(self, user_id: str, query: str, k: int = 5) -> list[str]:
        """Return up to k node_id strings (jac jids) for the nearest facts.

        Filters by user_id so results are always scoped to one user.
        Returns [] on any error so retrieval degrades gracefully.
        """
        if not query or not query.strip():
            return []
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            client = self._get_client()
            response = client.query_points(
                collection_name=_COLLECTION,
                query=self._embed(query),
                query_filter=Filter(
                    must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
                ),
                limit=k,
                with_payload=True,
            )
            return [r.payload["node_id"] for r in response.points if r.payload]
        except Exception:
            log.exception("vector search failed for user %s", user_id)
            return []

    def search_with_scores(self, user_id: str, query: str, k: int = 5) -> list[dict]:
        """Like search() but returns [{node_id, score}] for edge weight assignment."""
        if not query or not query.strip():
            return []
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            client = self._get_client()
            response = client.query_points(
                collection_name=_COLLECTION,
                query=self._embed(query),
                query_filter=Filter(
                    must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
                ),
                limit=k,
                with_payload=True,
                score_threshold=0.7,
            )
            return [
                {"node_id": r.payload["node_id"], "score": r.score}
                for r in response.points
                if r.payload
            ]
        except Exception:
            log.exception("vector search_with_scores failed for user %s", user_id)
            return []

    def count(self, user_id: str) -> int:
        """Return number of indexed points for a user. Used by linker."""
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            client = self._get_client()
            result = client.count(
                collection_name=_COLLECTION,
                count_filter=Filter(
                    must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
                ),
            )
            return result.count
        except Exception:
            return 0


# Module-level singleton — one Qdrant connection per process
vector_store = QdrantMemoryStore()
