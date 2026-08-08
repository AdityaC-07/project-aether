from __future__ import annotations

import asyncio
import math
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from app.rag.models import Chunk, PdfDocument, PdfPage


class ChunkStrategyType(str, Enum):
    fixed_size = "fixed-size"
    semantic = "semantic"
    table_aware = "table-aware"


_WORD_RE = re.compile(r"\b[\w$%.-]+\b")
_HEADING_RE = re.compile(r"^(?:\d+(?:\.\d+)*\s+)?[A-Z][A-Za-z0-9 ,:/&()\-]{0,80}$")


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _word_tokens(text: str) -> List[str]:
    return _WORD_RE.findall(text.lower())


def _token_count(text: str) -> int:
    return len(_word_tokens(text))


def _split_paragraphs(text: str) -> List[str]:
    blocks = re.split(r"\n\s*\n", text)
    return [_normalize_whitespace(block) for block in blocks if _normalize_whitespace(block)]


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", text)
    return [part.strip() for part in parts if part.strip()]


def _is_heading(text: str) -> bool:
    stripped = text.strip()
    return bool(_HEADING_RE.match(stripped)) and len(stripped.split()) <= 14


def _term_frequency(text: str) -> Dict[str, float]:
    counts: Dict[str, int] = {}
    for token in _word_tokens(text):
        counts[token] = counts.get(token, 0) + 1
    total = float(sum(counts.values()) or 1)
    return {token: count / total for token, count in counts.items()}


def _cosine_similarity(left: str, right: str) -> float:
    left_vec = _term_frequency(left)
    right_vec = _term_frequency(right)
    if not left_vec or not right_vec:
        return 0.0
    common = set(left_vec) & set(right_vec)
    dot = sum(left_vec[token] * right_vec[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left_vec.values()))
    right_norm = math.sqrt(sum(value * value for value in right_vec.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _group_semantically(paragraphs: Sequence[str], target_tokens: int, similarity_threshold: float) -> List[List[str]]:
    groups: List[List[str]] = []
    current: List[str] = []
    current_tokens = 0

    for paragraph in paragraphs:
        paragraph_tokens = _token_count(paragraph)
        if not current:
            current = [paragraph]
            current_tokens = paragraph_tokens
            continue

        similarity = _cosine_similarity(current[-1], paragraph)
        if current_tokens >= target_tokens or similarity < similarity_threshold or _is_heading(paragraph):
            groups.append(current)
            current = [paragraph]
            current_tokens = paragraph_tokens
            continue

        current.append(paragraph)
        current_tokens += paragraph_tokens

    if current:
        groups.append(current)
    return groups


class ChunkingStrategy:
    def __init__(
        self,
        strategy: ChunkStrategyType = ChunkStrategyType.semantic,
        *,
        target_tokens: int = 220,
        overlap_tokens: int = 40,
        similarity_threshold: float = 0.18,
    ) -> None:
        self.strategy = strategy
        self.target_tokens = max(50, target_tokens)
        self.overlap_tokens = max(0, overlap_tokens)
        self.similarity_threshold = similarity_threshold

    async def chunk_document(self, document: PdfDocument | Dict[str, Any], document_id: Optional[str] = None) -> List[Chunk]:
        return await asyncio.to_thread(self._chunk_document_sync, document, document_id)

    def _chunk_document_sync(self, document: PdfDocument | Dict[str, Any], document_id: Optional[str]) -> List[Chunk]:
        pdf = document if isinstance(document, PdfDocument) else PdfDocument.model_validate(document)
        resolved_document_id = document_id or pdf.metadata.get("document_id") or uuid4().hex

        if self.strategy == ChunkStrategyType.fixed_size:
            return self._chunk_fixed(pdf, resolved_document_id)
        if self.strategy == ChunkStrategyType.table_aware:
            return self._chunk_table_aware(pdf, resolved_document_id)
        return self._chunk_semantic(pdf, resolved_document_id)

    def _build_chunk(
        self,
        *,
        document_id: str,
        text: str,
        chunk_type: str,
        page_start: Optional[int] = None,
        page_end: Optional[int] = None,
        section_title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Chunk:
        clean_text = _normalize_whitespace(text)
        return Chunk(
            chunk_id=uuid4().hex,
            document_id=document_id,
            text=clean_text,
            chunk_type=chunk_type,
            page_start=page_start,
            page_end=page_end,
            section_title=section_title,
            token_count=_token_count(clean_text),
            metadata=metadata or {},
        )

    def _chunk_fixed(self, document: PdfDocument, document_id: str) -> List[Chunk]:
        sentences: List[Tuple[int, str]] = []
        for page in document.pages:
            for sentence in _sentences(page.text):
                sentences.append((page.page_number, sentence))

        if not sentences and document.text.strip():
            sentences = [(1, document.text)]

        chunks: List[Chunk] = []
        buffer: List[Tuple[int, str]] = []
        buffer_tokens = 0

        for page_number, sentence in sentences:
            sentence_tokens = _token_count(sentence)
            if buffer and buffer_tokens + sentence_tokens > self.target_tokens:
                chunks.append(
                    self._build_chunk(
                        document_id=document_id,
                        text=" ".join(part for _, part in buffer),
                        chunk_type="prose",
                        page_start=buffer[0][0],
                        page_end=buffer[-1][0],
                    )
                )
                if self.overlap_tokens > 0:
                    overlap: List[Tuple[int, str]] = []
                    overlap_tokens = 0
                    for candidate in reversed(buffer):
                        overlap.insert(0, candidate)
                        overlap_tokens += _token_count(candidate[1])
                        if overlap_tokens >= self.overlap_tokens:
                            break
                    buffer = overlap[:]
                    buffer_tokens = sum(_token_count(part) for _, part in buffer)
                else:
                    buffer = []
                    buffer_tokens = 0

            buffer.append((page_number, sentence))
            buffer_tokens += sentence_tokens

        if buffer:
            chunks.append(
                self._build_chunk(
                    document_id=document_id,
                    text=" ".join(part for _, part in buffer),
                    chunk_type="prose",
                    page_start=buffer[0][0],
                    page_end=buffer[-1][0],
                )
            )

        return chunks

    def _chunk_semantic(self, document: PdfDocument, document_id: str) -> List[Chunk]:
        chunks: List[Chunk] = []
        pages = document.pages or [PdfPage(page_number=1, text=document.text)]
        for page in pages:
            paragraphs = _split_paragraphs(page.text)
            if not paragraphs:
                continue

            for group in _group_semantically(paragraphs, self.target_tokens, self.similarity_threshold):
                section_title = group[0] if group and _is_heading(group[0]) else None
                body = group[1:] if section_title and len(group) > 1 else group
                chunks.append(
                    self._build_chunk(
                        document_id=document_id,
                        text="\n\n".join(body),
                        chunk_type="prose",
                        page_start=page.page_number,
                        page_end=page.page_number,
                        section_title=section_title,
                        metadata={"paragraph_count": len(group)},
                    )
                )

        if not chunks and document.text.strip():
            chunks.append(
                self._build_chunk(
                    document_id=document_id,
                    text=document.text,
                    chunk_type="prose",
                    page_start=1,
                    page_end=max(document.num_pages or 1, 1),
                )
            )

        return chunks

    def _chunk_table_aware(self, document: PdfDocument, document_id: str) -> List[Chunk]:
        chunks: List[Chunk] = []
        pages = document.pages or [PdfPage(page_number=1, text=document.text)]
        for page in pages:
            paragraphs = _split_paragraphs(page.text)
            paragraph_index = 0

            while paragraph_index < len(paragraphs):
                paragraph = paragraphs[paragraph_index]
                if _is_heading(paragraph):
                    chunks.append(
                        self._build_chunk(
                            document_id=document_id,
                            text=paragraph,
                            chunk_type="heading",
                            page_start=page.page_number,
                            page_end=page.page_number,
                            section_title=paragraph,
                        )
                    )
                    paragraph_index += 1
                    continue

                group: List[str] = [paragraph]
                group_tokens = _token_count(paragraph)
                paragraph_index += 1

                while paragraph_index < len(paragraphs):
                    next_paragraph = paragraphs[paragraph_index]
                    if _is_heading(next_paragraph):
                        break
                    next_tokens = _token_count(next_paragraph)
                    if group_tokens + next_tokens > self.target_tokens:
                        break
                    if _cosine_similarity(group[-1], next_paragraph) < self.similarity_threshold and group_tokens >= self.target_tokens // 2:
                        break
                    group.append(next_paragraph)
                    group_tokens += next_tokens
                    paragraph_index += 1

                chunks.append(
                    self._build_chunk(
                        document_id=document_id,
                        text="\n\n".join(group),
                        chunk_type="prose",
                        page_start=page.page_number,
                        page_end=page.page_number,
                        metadata={"paragraph_count": len(group)},
                    )
                )

            for table in page.tables:
                chunks.append(
                    self._build_chunk(
                        document_id=document_id,
                        text=table.text,
                        chunk_type="table",
                        page_start=table.page_number,
                        page_end=table.page_number,
                        section_title=table.title,
                        metadata={"rows": table.rows, "table": True},
                    )
                )

        if not chunks and document.text.strip():
            chunks.append(
                self._build_chunk(
                    document_id=document_id,
                    text=document.text,
                    chunk_type="prose",
                    page_start=1,
                    page_end=max(document.num_pages or 1, 1),
                )
            )

        return chunks

