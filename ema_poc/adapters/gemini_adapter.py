"""Google Gemini adapter — system instruction + user content (IN-2, IN-204).

The Gemini SDK sets the system instruction at model construction, so this
adapter is given a `model_factory(system_prompt) -> model` callable and builds
a fresh model per query (system prompt varies per persona)."""

from __future__ import annotations

from typing import Callable

from ema_poc.adapters.base import Citation, LLMAdapter, LLMResponse


def _name(value) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", None) or str(value)


def _extract_gemini_citations(candidate) -> list[Citation]:
    gm = getattr(candidate, "grounding_metadata", None)
    if gm is None:
        return []
    out: list[Citation] = []
    seen: set[str] = set()
    for chunk in getattr(gm, "grounding_chunks", None) or []:
        web = getattr(chunk, "web", None)
        url = getattr(web, "uri", None) if web else None
        if url and url not in seen:
            seen.add(url)
            out.append(Citation(title=getattr(web, "title", "") or url, url=url))
    return out


class GeminiAdapter(LLMAdapter):
    def __init__(
        self,
        *,
        name: str,
        model_version: str,
        params: dict,
        model_factory: Callable[[str], object],
        grounded: bool = False,
    ):
        self.name = name
        self.model_version = model_version
        self.params = params
        self._model_factory = model_factory
        self.grounded = grounded

    def query(self, system_prompt: str, question_text: str) -> LLMResponse:
        model = self._model_factory(system_prompt)
        gen_kwargs = {
            "generation_config": {
                "temperature": self.params.get("temperature", 0.3),
                "max_output_tokens": self.params.get("max_output_tokens", 4096),
            }
        }
        if self.grounded:
            gen_kwargs["tools"] = [{"google_search": {}}]
        resp = model.generate_content(question_text, **gen_kwargs)

        candidates = getattr(resp, "candidates", None) or []
        finish_name = _name(candidates[0].finish_reason) if candidates else None
        feedback = getattr(resp, "prompt_feedback", None)
        block_name = _name(getattr(feedback, "block_reason", None)) if feedback else None

        usage = getattr(resp, "usage_metadata", None)
        ptok = getattr(usage, "prompt_token_count", None) if usage else None
        ctok = getattr(usage, "candidates_token_count", None) if usage else None

        blocked = finish_name == "SAFETY" or (
            block_name is not None and block_name != "BLOCK_REASON_UNSPECIFIED"
        )
        if blocked:
            return LLMResponse(
                text="",
                finish_reason="blocked",
                status="BLOCKED",
                prompt_tokens=ptok,
                completion_tokens=None,
                raw={"block_reason": block_name, "finish_reason": finish_name},
            )

        truncated = finish_name == "MAX_TOKENS"
        citations = _extract_gemini_citations(candidates[0]) if (candidates and self.grounded) else []
        return LLMResponse(
            text=getattr(resp, "text", "") or "",
            finish_reason="length" if truncated else "stop",
            status="TRUNCATED" if truncated else "SUCCESS",
            prompt_tokens=ptok,
            completion_tokens=ctok,
            raw={"finish_reason": finish_name, "model": self.model_version},
            citations=citations,
            actual_model=getattr(resp, "model_version", None),
        )
