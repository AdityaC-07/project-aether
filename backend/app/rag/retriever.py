from __future__ import annotations

import time
from typing import Dict, List, Optional
from uuid import uuid4

from app.rag.chunking import ChunkStrategyType, ChunkingStrategy
from app.rag.embeddings import EmbeddingService
from app.rag.metrics import RetrievalLogger
from app.rag.models import Chunk, PdfDocument, RetrievalContext, RetrievalResult
from app.rag.vector_store import VectorStore, build_vector_store


class RetrievalPipeline:
    def __init__(
        self,
        *,
        chunking_strategy: ChunkingStrategy | None = None,
        embedding_service: EmbeddingService | None = None,
        vector_store: VectorStore | None = None,
        logger: RetrievalLogger | None = None,
        backend_name: str | None = None,
    ) -> None:
        self.chunking_strategy = chunking_strategy or ChunkingStrategy(ChunkStrategyType.semantic)
        self.embedding_service = embedding_service or EmbeddingService()
        self.vector_store = vector_store or build_vector_store(backend_name)
        self.logger = logger or RetrievalLogger()
        self.document_id = uuid4().hex
        self._chunks: List[Chunk] = []

    async def ingest_document(self, document: PdfDocument | Dict[str, object]) -> List[Chunk]:
        self.document_id = uuid4().hex
        self._chunks = await self.chunking_strategy.chunk_document(document, document_id=self.document_id)
        if not self._chunks:
            return []

        texts = [chunk.text for chunk in self._chunks]
        embeddings = await self.embedding_service.embed_texts(texts, task_type="RETRIEVAL_DOCUMENT")
        await self.vector_store.upsert(self._chunks, embeddings)
        return self._chunks

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        document_id: Optional[str] = None,
    ) -> RetrievalResult:
        started = time.perf_counter()
        query_embedding = await self.embedding_service.embed_text(query, task_type="RETRIEVAL_QUERY")
        matches = await self.vector_store.query(
            query_embedding,
            top_k=top_k,
            document_id=document_id or self.document_id,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        context = RetrievalContext(
            query=query,
            matches=matches,
            latency_ms=latency_ms,
            strategy=self.chunking_strategy.strategy.value,
            backend=self.vector_store.backend_name,
            top_k=top_k,
        )
        metrics = self.logger.log(context)
        return RetrievalResult(
            query=query,
            matches=matches,
            latency_ms=latency_ms,
            strategy=context.strategy,
            backend=context.backend,
            top_k=top_k,
            metrics=metrics.model_dump(),
        )

    @staticmethod
    def format_matches(result: RetrievalResult, *, max_chars_per_chunk: int = 1200) -> str:
        if not result.matches:
            return "No retrieved context was available."

        sections: List[str] = []
        for index, match in enumerate(result.matches, 1):
            chunk = match.chunk
            text = chunk.text[:max_chars_per_chunk]
            chunk_header = (
                f"[Chunk {index}] similarity={match.similarity:.4f} "
                f"type={chunk.chunk_type} "
                f"pages={chunk.page_start or '?'}-{chunk.page_end or '?'} "
                f"id={chunk.chunk_id}"
            )
            if chunk.section_title:
                chunk_header += f" title={chunk.section_title}"
            sections.append(f"{chunk_header}\n{text}")
        return "\n\n".join(sections)

