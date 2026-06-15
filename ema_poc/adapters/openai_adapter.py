"""OpenAI adapter. Ungrounded: Chat Completions. Grounded: Responses API web_search.
Params are config-driven (temperature optional; max_completion_tokens for reasoning models)."""

from __future__ import annotations

from ema_poc.adapters.base import Citation, LLMAdapter, LLMResponse


class OpenAIAdapter(LLMAdapter):
    def __init__(self, *, name: str, model_version: str, params: dict, client, grounded: bool = False):
        self.name = name
        self.model_version = model_version
        self.params = params
        self._client = client
        self.grounded = grounded

    def query(self, system_prompt: str, question_text: str) -> LLMResponse:
        if self.grounded:
            return self._query_grounded(system_prompt, question_text)
        return self._query_chat(system_prompt, question_text)

    def _query_chat(self, system_prompt: str, question_text: str) -> LLMResponse:
        kwargs = dict(
            model=self.model_version,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question_text},
            ],
        )
        if "temperature" in self.params:
            kwargs["temperature"] = self.params["temperature"]
        if "max_completion_tokens" in self.params:
            kwargs["max_completion_tokens"] = self.params["max_completion_tokens"]
        elif "max_tokens" in self.params:
            kwargs["max_tokens"] = self.params["max_tokens"]
        else:
            kwargs["max_tokens"] = 1024
        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        finish = choice.finish_reason
        text = choice.message.content or ""
        if finish == "content_filter":
            norm_finish, status = "blocked", "BLOCKED"
        elif finish == "length":
            norm_finish, status = "length", "TRUNCATED"
        else:
            norm_finish, status = "stop", "SUCCESS"
        return LLMResponse(
            text=text,
            finish_reason=norm_finish,
            status=status,
            prompt_tokens=getattr(resp.usage, "prompt_tokens", None),
            completion_tokens=getattr(resp.usage, "completion_tokens", None),
            raw={"finish_reason": finish, "model": self.model_version},
            actual_model=getattr(resp, "model", None),
        )

    def _query_grounded(self, system_prompt: str, question_text: str) -> LLMResponse:
        resp = self._client.responses.create(
            model=self.model_version,
            tools=[{"type": "web_search_preview"}],
            instructions=system_prompt,
            input=question_text,
            max_output_tokens=self.params.get("max_tokens", 4096),
        )
        text = getattr(resp, "output_text", "") or ""
        citations = _extract_openai_citations(resp)
        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text=text,
            finish_reason="stop" if text else "error",
            status="SUCCESS" if text else "FAILED",
            prompt_tokens=getattr(usage, "input_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "output_tokens", None) if usage else None,
            raw={"model": self.model_version, "grounded": True,
                 "status": getattr(resp, "status", None)},
            citations=citations,
            actual_model=getattr(resp, "model", None),
        )


def _extract_openai_citations(resp) -> list[Citation]:
    out: list[Citation] = []
    seen: set[str] = set()
    for block in getattr(resp, "output", None) or []:
        for content in getattr(block, "content", None) or []:
            for ann in getattr(content, "annotations", None) or []:
                if getattr(ann, "type", None) == "url_citation":
                    url = getattr(ann, "url", None)
                    if url and url not in seen:
                        seen.add(url)
                        out.append(Citation(title=getattr(ann, "title", "") or url, url=url))
    return out
