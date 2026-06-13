"""OpenAI (GPT-4o) adapter — Chat Completions (IN-1)."""

from __future__ import annotations

from ema_poc.adapters.base import LLMAdapter, LLMResponse


class OpenAIAdapter(LLMAdapter):
    def __init__(self, *, name: str, model_version: str, params: dict, client):
        self.name = name
        self.model_version = model_version
        self.params = params
        self._client = client

    def query(self, system_prompt: str, question_text: str) -> LLMResponse:
        resp = self._client.chat.completions.create(
            model=self.model_version,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question_text},
            ],
            temperature=self.params.get("temperature", 0.3),
            max_tokens=self.params.get("max_tokens", 1024),
        )
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
        )
