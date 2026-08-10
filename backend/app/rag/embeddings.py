from __future__ import annotations

import asyncio
import hashlib
import math
import re
from dataclasses import dataclass
from typing import List, Sequence


@dataclass(slots=True)
class EmbeddingConfig:
    model: str = "local-hash-embedding-v1"
    output_dimensionality: int = 256
    use_bigrams: bool = True
    normalize: bool = True


class EmbeddingService:
    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self.config = config or EmbeddingConfig()

    async def embed_texts(self, texts: Sequence[str], *, task_type: str = "RETRIEVAL_DOCUMENT") -> List[List[float]]:
        return await asyncio.gather(*(self.embed_text(text, task_type=task_type) for text in texts))

    async def embed_text(self, text: str, *, task_type: str = "RETRIEVAL_DOCUMENT", title: str | None = None) -> List[float]:
        return await asyncio.to_thread(self._embed_text_sync, text, task_type, title)

    def _embed_text_sync(self, text: str, task_type: str, title: str | None) -> List[float]:
        vector = [0.0] * max(1, int(self.config.output_dimensionality))
        tokens = self._tokenize(text, title=title, task_type=task_type)
        if not tokens:
            return vector

        for token in tokens:
            self._add_feature(vector, token, weight=1.0)

        if self.config.use_bigrams and len(tokens) > 1:
            for left, right in zip(tokens, tokens[1:]):
                self._add_feature(vector, f"{left}::{right}", weight=0.5)

        if self.config.normalize:
            norm = math.sqrt(sum(value * value for value in vector))
            if norm:
                vector = [value / norm for value in vector]

        return vector

    def _tokenize(self, text: str, *, title: str | None, task_type: str) -> List[str]:
        parts = [text, title or "", task_type]
        normalized = " ".join(part for part in parts if part).lower()
        return re.findall(r"[a-z0-9]+", normalized)

    def _add_feature(self, vector: List[float], token: str, *, weight: float) -> None:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % len(vector)
        sign = -1.0 if digest[4] & 1 else 1.0
        magnitude = 1.0 + (digest[5] / 255.0)
        vector[index] += weight * sign * magnitude
