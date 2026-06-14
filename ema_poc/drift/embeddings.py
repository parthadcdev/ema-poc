"""Embedding generation + cosine similarity for semantic drift detection.

The OpenAI SDK is imported lazily inside the default client so tests run with a
fake client and no SDK/network."""

from __future__ import annotations

import math
from typing import Protocol


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("vectors must have equal length")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class EmbeddingClient(Protocol):
    def embed(self, text: str) -> list[float]: ...


class OpenAIEmbeddingClient:
    """Default EmbeddingClient backed by the OpenAI embeddings API."""

    def __init__(self, *, client, model: str):
        self._client = client
        self.model = model

    def embed(self, text: str) -> list[float]:
        resp = self._client.embeddings.create(model=self.model, input=text)
        return list(resp.data[0].embedding)


def default_embedding_client(api_key: str, model: str) -> OpenAIEmbeddingClient:
    from openai import OpenAI

    return OpenAIEmbeddingClient(client=OpenAI(api_key=api_key), model=model)


def embed_response(conn, response, *, client: EmbeddingClient, model: str, now: str,
                   id_factory=None) -> bool:
    """Idempotent: embed and store response.response_text if not already embedded.
    Returns True if a new embedding was written, False if it already existed."""
    from ema_poc.repositories.embeddings import has_embedding, save_embedding

    if has_embedding(conn, response.response_id):
        return False
    vector = client.embed(response.response_text)
    save_embedding(conn, response_id=response.response_id, model=model, vector=vector, now=now)
    return True
