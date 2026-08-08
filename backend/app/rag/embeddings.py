from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import List, Sequence

from google import genai
from google.genai import types


@dataclass(slots=True)
class EmbeddingConfig:
    model: str = "gemini-embedding-001"
    output_dimensionality: int | None = None
    location: str = "us-central1"


class EmbeddingService:
    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        resolved_dimensionality = os.getenv("GOOGLE_EMBEDDING_DIMENSIONALITY", "").strip()
        self.config = config or EmbeddingConfig(
            model=os.getenv("GOOGLE_EMBEDDING_MODEL", "gemini-embedding-001"),
            output_dimensionality=int(resolved_dimensionality) if resolved_dimensionality else None,
            location=os.getenv("GCP_LOCATION", os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")),
        )
        self.client = genai.Client(
            vertexai=True,
            project=os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT")),
            location=self.config.location,
        )

    async def embed_texts(self, texts: Sequence[str], *, task_type: str = "RETRIEVAL_DOCUMENT") -> List[List[float]]:
        return await asyncio.gather(*(self.embed_text(text, task_type=task_type) for text in texts))

    async def embed_text(self, text: str, *, task_type: str = "RETRIEVAL_DOCUMENT", title: str | None = None) -> List[float]:
        return await asyncio.to_thread(self._embed_text_sync, text, task_type, title)

    def _embed_text_sync(self, text: str, task_type: str, title: str | None) -> List[float]:
        config_kwargs: dict[str, object] = {"task_type": task_type}
        if self.config.output_dimensionality:
            config_kwargs["output_dimensionality"] = self.config.output_dimensionality
        if title:
            config_kwargs["title"] = title

        response = self.client.models.embed_content(
            model=self.config.model,
            contents=text,
            config=types.EmbedContentConfig(**config_kwargs),
        )
        return list(response.embeddings[0].values)

