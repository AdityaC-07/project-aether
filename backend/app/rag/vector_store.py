from __future__ import annotations

import asyncio
import math
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Sequence

from app.rag.models import Chunk, RetrievalMatch


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


@dataclass(slots=True)
class StoredVector:
    chunk: Chunk
    embedding: List[float]


class VectorStore(ABC):
    backend_name = "abstract"

    @abstractmethod
    async def upsert(self, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def query(
        self,
        embedding: Sequence[float],
        *,
        top_k: int = 5,
        document_id: Optional[str] = None,
    ) -> List[RetrievalMatch]:
        raise NotImplementedError


class InMemoryVectorStore(VectorStore):
    backend_name = "in-memory"

    def __init__(self) -> None:
        self._vectors: List[StoredVector] = []

    async def upsert(self, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]) -> None:
        await asyncio.to_thread(self._upsert_sync, chunks, embeddings)

    def _upsert_sync(self, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]) -> None:
        for chunk, embedding in zip(chunks, embeddings):
            self._vectors.append(StoredVector(chunk=chunk, embedding=list(embedding)))

    async def query(
        self,
        embedding: Sequence[float],
        *,
        top_k: int = 5,
        document_id: Optional[str] = None,
    ) -> List[RetrievalMatch]:
        return await asyncio.to_thread(self._query_sync, embedding, top_k, document_id)

    def _query_sync(
        self,
        embedding: Sequence[float],
        top_k: int,
        document_id: Optional[str],
    ) -> List[RetrievalMatch]:
        results: List[RetrievalMatch] = []
        for stored in self._vectors:
            if document_id and stored.chunk.document_id != document_id:
                continue
            score = _cosine_similarity(embedding, stored.embedding)
            results.append(RetrievalMatch(chunk=stored.chunk, similarity=round(score, 6)))
        results.sort(key=lambda item: item.similarity, reverse=True)
        return results[:top_k]


class SupabaseVectorStore(VectorStore):
    backend_name = "supabase"

    def __init__(
        self,
        *,
        table_name: str = "document_chunks",
        url: Optional[str] = None,
        service_role_key: Optional[str] = None,
    ) -> None:
        self.table_name = table_name
        self.url = url or os.getenv("SUPABASE_URL")
        self.service_role_key = service_role_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    async def upsert(self, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]) -> None:
        raise NotImplementedError(
            "SupabaseVectorStore is an integration point. "
            "Use the in-memory backend or wire in a Supabase client adapter."
        )

    async def query(
        self,
        embedding: Sequence[float],
        *,
        top_k: int = 5,
        document_id: Optional[str] = None,
    ) -> List[RetrievalMatch]:
        raise NotImplementedError(
            "SupabaseVectorStore query support requires a Supabase vector RPC or client adapter."
        )


class PineconeVectorStore(VectorStore):
    backend_name = "pinecone"

    def __init__(
        self,
        *,
        index_name: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self.index_name = index_name or os.getenv("PINECONE_INDEX", "")
        self.api_key = api_key or os.getenv("PINECONE_API_KEY")

    async def upsert(self, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]) -> None:
        raise NotImplementedError(
            "PineconeVectorStore is an integration point. "
            "Use the in-memory backend or wire in a Pinecone client adapter."
        )

    async def query(
        self,
        embedding: Sequence[float],
        *,
        top_k: int = 5,
        document_id: Optional[str] = None,
    ) -> List[RetrievalMatch]:
        raise NotImplementedError(
            "PineconeVectorStore query support requires a Pinecone client adapter."
        )


def build_vector_store(kind: str | None = None) -> VectorStore:
    resolved = (kind or os.getenv("VECTOR_STORE_BACKEND", "in-memory")).strip().lower()
    if resolved == "pinecone":
        return PineconeVectorStore()
    if resolved == "supabase":
        return SupabaseVectorStore()
    return InMemoryVectorStore()

