from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition,
    MatchValue, ScoredPoint,
)


COLLECTION = "tasks"
VECTOR_SIZE = 768  # gemini text-embedding-004 default


class QdrantStore:
    """Task embedding store for warm-start topology search."""

    def __init__(self, host: str = "localhost", port: int = 6333, api_key: str | None = None):
        if api_key:
            self._client = QdrantClient(url=f"http://{host}:{port}", api_key=api_key)
        else:
            self._client = QdrantClient(host=host, port=port)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        existing = [c.name for c in self._client.get_collections().collections]
        if COLLECTION not in existing:
            self._client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

    def upsert_task(
        self,
        task_id: str,
        embedding: List[float],
        category: str,
        best_workflow_id: str,
        best_score: float,
    ) -> None:
        self._client.upsert(
            collection_name=COLLECTION,
            points=[PointStruct(
                id=_uuid_int(task_id),
                vector=embedding,
                payload={
                    "task_id": task_id,
                    "category": category,
                    "best_workflow_id": best_workflow_id,
                    "best_score": best_score,
                },
            )],
        )

    def find_similar(self, embedding: List[float], limit: int = 5) -> List[Dict[str, Any]]:
        hits: List[ScoredPoint] = self._client.search(
            collection_name=COLLECTION,
            query_vector=embedding,
            limit=limit,
        )
        return [
            {**h.payload, "similarity": h.score}
            for h in hits
        ]


def _uuid_int(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest(), 16) % (2**63)
