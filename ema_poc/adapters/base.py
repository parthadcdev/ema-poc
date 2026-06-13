"""Shared LLM adapter interface and normalized response (§3, FR-201)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Citation:
    """A web source backing a grounded answer, normalized across vendors."""

    title: str
    url: str
    snippet: str | None = None


@dataclass
class LLMResponse:
    """A monitored LLM's answer, normalized across vendors.

    status matches ResponseStatus values: SUCCESS | FAILED | TRUNCATED | BLOCKED.
    finish_reason is normalized: stop | length | error | blocked.
    raw is a small JSON-serializable dict kept for the audit trail.
    """

    text: str
    finish_reason: str
    status: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    raw: dict = field(default_factory=dict)
    citations: list[Citation] = field(default_factory=list)


class LLMAdapter(ABC):
    """A monitored LLM target. Subclasses own vendor request-shaping and
    response normalization only; retry/rate-limiting live in the executor."""

    name: str
    model_version: str

    @abstractmethod
    def query(self, system_prompt: str, question_text: str) -> LLMResponse:
        """Submit one question and return a normalized LLMResponse. May raise
        on transport errors (the executor retries those)."""
