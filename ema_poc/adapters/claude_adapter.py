"""Anthropic Claude adapter — Claude queried as a monitored end-user target
(IN-3, IN-301/303). Adaptive thinking; max_tokens from config; NO temperature
(Opus 4.8 rejects temperature/top_p/budget_tokens). Distinct from the
orchestrator/scoring Claude client; the runner tags this role=TARGET."""

from __future__ import annotations

from ema_poc.adapters.base import Citation, LLMAdapter, LLMResponse

_STATUS_BY_STOP = {
    "end_turn": "SUCCESS",
    "max_tokens": "TRUNCATED",
    "refusal": "BLOCKED",
    "stop_sequence": "SUCCESS",
}
_FINISH_BY_STOP = {
    "end_turn": "stop",
    "max_tokens": "length",
    "refusal": "blocked",
    "stop_sequence": "stop",
}


def _extract_claude_citations(resp) -> list[Citation]:
    out: list[Citation] = []
    seen: set[str] = set()
    for block in getattr(resp, "content", None) or []:
        for cite in getattr(block, "citations", None) or []:
            url = getattr(cite, "url", None)
            if url and url not in seen:
                seen.add(url)
                out.append(Citation(
                    title=getattr(cite, "title", "") or url,
                    url=url,
                    snippet=getattr(cite, "cited_text", None),
                ))
    return out


class ClaudeTargetAdapter(LLMAdapter):
    def __init__(self, *, name: str, model_version: str, params: dict, client, grounded: bool = False):
        self.name = name
        self.model_version = model_version
        self.params = params
        self._client = client
        self.grounded = grounded

    def query(self, system_prompt: str, question_text: str) -> LLMResponse:
        kwargs = dict(
            model=self.model_version,
            max_tokens=self.params.get("max_tokens", 1024),
            thinking={"type": "adaptive"},
            system=system_prompt,
            messages=[{"role": "user", "content": question_text}],
        )
        if self.grounded:
            kwargs["tools"] = [
                {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
            ]
        resp = self._client.messages.create(**kwargs)
        text = "".join(
            getattr(b, "text", "") for b in resp.content
            if getattr(b, "type", None) == "text"
        )
        citations = _extract_claude_citations(resp) if self.grounded else []
        stop = resp.stop_reason
        return LLMResponse(
            text=text,
            finish_reason=_FINISH_BY_STOP.get(stop, "stop"),
            status=_STATUS_BY_STOP.get(stop, "SUCCESS"),
            prompt_tokens=getattr(resp.usage, "input_tokens", None),
            completion_tokens=getattr(resp.usage, "output_tokens", None),
            raw={"stop_reason": stop, "model": self.model_version},
            citations=citations,
            actual_model=getattr(resp, "model", None),
        )
