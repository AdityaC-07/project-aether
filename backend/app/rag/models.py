from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TableBlock(BaseModel):
    page_number: int
    title: Optional[str] = None
    text: str
    rows: List[List[str]] = Field(default_factory=list)


class PdfPage(BaseModel):
    page_number: int
    text: str
    tables: List[TableBlock] = Field(default_factory=list)


class PdfDocument(BaseModel):
    text: str
    num_pages: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    metrics: List[Any] = Field(default_factory=list)
    pages: List[PdfPage] = Field(default_factory=list)


class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    chunk_type: str = "prose"
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    section_title: Optional[str] = None
    token_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetrievalMatch(BaseModel):
    chunk: Chunk
    similarity: float


class RetrievalContext(BaseModel):
    query: str
    matches: List[RetrievalMatch] = Field(default_factory=list)
    latency_ms: float = 0.0
    strategy: str = "unknown"
    backend: str = "unknown"
    top_k: int = 0


class RetrievalResult(BaseModel):
    query: str
    matches: List[RetrievalMatch] = Field(default_factory=list)
    latency_ms: float = 0.0
    strategy: str = "unknown"
    backend: str = "unknown"
    top_k: int = 0
    metrics: Dict[str, float] = Field(default_factory=dict)

