"""Google Gemini adapter — uses the google-genai SDK (google-genai>=1.0).

A google.genai Client is injected at construction time so tests can provide
a fake without touching the real SDK.  The system instruction and generation
config are assembled per-query and passed via GenerateContentConfig."""

from __future__ import annotations

from ema_poc.adapters.base import Citation, LLMAdapter, LLMResponse


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
        client: object,
        grounded: bool = False,
    ):
        self.name = name
        self.model_version = model_version
        self.params = params
        self._client = client
        self.grounded = grounded

    def query(self, system_prompt: str, question_text: str) -> LLMResponse:
        from google.genai import types

        cfg_kwargs: dict = dict(
            system_instruction=system_prompt,
            max_output_tokens=self.params.get("max_output_tokens", 4096),
        )
        if "temperature" in self.params:
            cfg_kwargs["temperature"] = self.params["temperature"]
        if self.grounded:
            cfg_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]

        config = types.GenerateContentConfig(**cfg_kwargs)
        resp = self._client.models.generate_content(
            model=self.model_version, contents=question_text, config=config
        )
        return self._normalize(resp)

    def _normalize(self, resp) -> LLMResponse:
        text = getattr(resp, "text", "") or ""

        candidates = getattr(resp, "candidates", None) or []
        cand = candidates[0] if candidates else None

        finish = getattr(getattr(cand, "finish_reason", None), "name", None)

        pf = getattr(resp, "prompt_feedback", None)
        block = getattr(pf, "block_reason", None) if pf else None

        block_name = getattr(block, "name", None) or (str(block) if block is not None else None)
        blocked = finish == "SAFETY" or (block_name is not None and block_name != "BLOCKED_REASON_UNSPECIFIED")

        usage = getattr(resp, "usage_metadata", None)
        ptok = getattr(usage, "prompt_token_count", None)
        ctok = getattr(usage, "candidates_token_count", None)

        if blocked:
            return LLMResponse(
                text="",
                finish_reason="blocked",
                status="BLOCKED",
                prompt_tokens=ptok,
                completion_tokens=None,
                raw={"finish_reason": finish, "block_reason": str(block) if block else None},
                actual_model=getattr(resp, "model_version", None),
            )

        truncated = finish == "MAX_TOKENS"
        citations = _extract_gemini_citations(cand) if (self.grounded and cand is not None) else []

        return LLMResponse(
            text=text,
            finish_reason="length" if truncated else "stop",
            status="TRUNCATED" if truncated else "SUCCESS",
            prompt_tokens=ptok,
            completion_tokens=ctok,
            raw={"finish_reason": finish, "model": self.model_version},
            citations=citations,
            actual_model=getattr(resp, "model_version", None),
        )
