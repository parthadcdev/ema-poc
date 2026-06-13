"""Execute one adapter query with retry + exponential backoff (FR-206/207).

Pure: calls adapter.query and retries on exception, returning a normalized
LLMResponse. Never touches the database (the runner persists results in the
main thread). After max_retries failed attempts, returns a FAILED LLMResponse.
TRUNCATED/BLOCKED responses are returned as-is (stored flagged); the
max_tokens-bump retry of FR-211 is a deferred SHOULD enhancement."""

from __future__ import annotations

import time

from ema_poc.adapters.base import LLMAdapter, LLMResponse


def execute(
    adapter: LLMAdapter,
    system_prompt: str,
    question_text: str,
    *,
    max_retries: int,
    backoff: list[int],
    rate_limiter=None,
    sleep=time.sleep,
) -> LLMResponse:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):  # initial attempt + max_retries retries
        if rate_limiter is not None:
            rate_limiter.acquire()
        try:
            return adapter.query(system_prompt, question_text)
        except Exception as exc:  # transport/transient error — retry
            last_exc = exc
            if attempt < max_retries:
                sleep(backoff[min(attempt, len(backoff) - 1)])
    return LLMResponse(
        text="",
        finish_reason="error",
        status="FAILED",
        raw={"error": str(last_exc)},
    )
