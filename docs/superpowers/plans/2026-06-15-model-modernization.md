# Model Modernization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** GPT-5.5 support (config-driven OpenAI params) + Gemini on the `google-genai` SDK so grounding works; swap GPT-4o → GPT-5.5 in config.

**Branch:** `feature/model-modernization`. **Spec:** `docs/superpowers/specs/2026-06-15-model-modernization-design.md`.

---

### Task 1: OpenAI adapter — config-driven params

**Files:** `ema_poc/adapters/openai_adapter.py`, `tests/adapters/test_openai_adapter.py`.

- READ the current `_query_chat`. Replace the hardcoded `temperature=...` and `max_tokens=...` with config-driven kwargs:
```python
    def _query_chat(self, system_prompt, question_text):
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
        # ... rest of the normalization unchanged (finish_reason→status, tokens, etc.)
```
  Keep the rest of `_query_chat` (choice/finish/status mapping, usage tokens, raw, actual_model if present) IDENTICAL. Keep `_query_grounded` unchanged.
- Tests (extend the existing fake-client tests):
  - A target with `params={"max_completion_tokens": 4096}` (no temperature): the captured `chat.completions.create` kwargs include `max_completion_tokens=4096`, do NOT include `temperature`, do NOT include `max_tokens`.
  - A target with `params={"temperature": 0.3, "max_tokens": 4096}` (GPT-4o style): kwargs include `temperature=0.3` and `max_tokens=4096`, NOT max_completion_tokens.
  - A target with empty `params={}`: kwargs include `max_tokens=1024` default, no temperature.
  - Existing ungrounded + grounded tests still pass.

### Task 2: Gemini adapter → google-genai

**Files:** `pyproject.toml`, `ema_poc/adapters/gemini_adapter.py`, `ema_poc/adapters/registry.py`, `tests/adapters/test_gemini_adapter.py`, `tests/adapters/test_registry.py`.

- `pyproject.toml`: add `"google-genai>=1.0"` to dependencies (it is already pip-installed in the venv).
- **Rewrite `gemini_adapter.py`** so `GeminiAdapter.__init__(*, name, model_version, params, client, grounded=False)` holds an injected client. `query(system_prompt, question_text)`:
```python
    def query(self, system_prompt, question_text):
        from google.genai import types  # lazy; tests inject a fake client and don't need this
        cfg_kwargs = dict(
            system_instruction=system_prompt,
            max_output_tokens=self.params.get("max_output_tokens", 4096),
        )
        if "temperature" in self.params:
            cfg_kwargs["temperature"] = self.params["temperature"]
        if self.grounded:
            cfg_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        config = types.GenerateContentConfig(**cfg_kwargs)
        resp = self._client.models.generate_content(
            model=self.model_version, contents=question_text, config=config)
        return self._normalize(resp)
```
  IMPORTANT: the `from google.genai import types` import inside `query` will run in production but NOT in tests if the fake adapter path avoids it. To keep tests offline WITHOUT importing the real SDK, the cleanest design: build the `config` object only when grounded needs `types`, OR pass a `config_factory`. SIMPLER + testable: inject a `tool_factory` is overkill. Instead, make the grounded tool construction tolerant: wrap the `types` import so tests that pass `grounded=False` never import it, and the ONE grounded test installs google-genai (it IS installed in the venv, so `from google.genai import types` works in tests too). Since google-genai is installed, importing `types` in tests is fine — the FAKE is the `client` (its `.models.generate_content`), not the SDK types. So: keep `from google.genai import types` at the top of `query` (or module-lazy). Tests pass a fake `client`; `types` import is real (installed) and harmless.
  - `_normalize(resp)` → `LLMResponse`:
    - `text = getattr(resp, "text", "") or ""`.
    - `cand = (resp.candidates or [None])[0]`; `finish = getattr(getattr(cand, "finish_reason", None), "name", None)`.
    - blocked = `finish == "SAFETY"` or `getattr(getattr(resp, "prompt_feedback", None), "block_reason", None)` truthy → status BLOCKED, finish "blocked", text "".
    - truncated = `finish == "MAX_TOKENS"` → status TRUNCATED, finish "length".
    - else status SUCCESS, finish "stop".
    - usage: `u = resp.usage_metadata`; prompt_tokens=`getattr(u,"prompt_token_count",None)`, completion_tokens=`getattr(u,"candidates_token_count",None)`.
    - citations (only when grounded and not blocked): from `cand.grounding_metadata.grounding_chunks[].web.{uri,title}` → `Citation(title=title or uri, url=uri)`, dedup by url. Reuse a helper `_extract_gemini_citations(cand)`.
    - `actual_model = getattr(resp, "model_version", None)`.
    - return `LLMResponse(text=, finish_reason=, status=, prompt_tokens=, completion_tokens=, raw={"finish_reason": finish, "model": self.model_version}, citations=citations, actual_model=actual_model)`.
- **registry.py**: replace `_default_gemini_model(api_key, model_version, system_instruction)` with `_default_gemini_client(api_key)`:
```python
def _default_gemini_client(api_key):
    from google import genai
    return genai.Client(api_key=api_key)
```
  In `build_adapters`, the gemini branch builds `GeminiAdapter(name=, model_version=, params=, client=gemini_client_factory(api_key), grounded=target.grounded)`. Rename the factory param to `gemini_client_factory=_default_gemini_client`. Remove the old model_factory lambda.
- **Tests — `tests/adapters/test_gemini_adapter.py`** (REWRITE for the new shape). A fake client:
```python
from types import SimpleNamespace
class _FakeModels:
    def __init__(self, resp): self.resp=resp; self.kwargs=None
    def generate_content(self, **kwargs): self.kwargs=kwargs; return self.resp
class _FakeClient:
    def __init__(self, resp): self.models=_FakeModels(resp)
def _resp(text="answer", finish="STOP", chunks=None, model_version="gemini-2.5-pro"):
    cand = SimpleNamespace(
        finish_reason=SimpleNamespace(name=finish),
        grounding_metadata=SimpleNamespace(grounding_chunks=chunks or []),
    )
    return SimpleNamespace(text=text, candidates=[cand], prompt_feedback=None,
        usage_metadata=SimpleNamespace(prompt_token_count=8, candidates_token_count=4),
        model_version=model_version)
```
  Cases: ungrounded success (no tools in cfg → assert the `config` passed has no tools, or grounded=False adapter never sets tools — inspect `_FakeModels.kwargs["config"]`); SUCCESS normalization + tokens + actual_model; MAX_TOKENS → TRUNCATED; SAFETY → BLOCKED; grounded adapter passes a config WITH a google_search tool AND parses citations from a chunk `SimpleNamespace(web=SimpleNamespace(uri="https://x", title="X"))`. Construct GeminiAdapter with `client=_FakeClient(_resp(...))`, `grounded=True/False`.
  (To assert the config's tools: read `client.models.kwargs["config"]` — it's a real `types.GenerateContentConfig`; check `config.tools` is non-empty when grounded, None/empty when not.)
- **tests/adapters/test_registry.py**: update the gemini-related test(s) to the new `gemini_client_factory` param (pass a fake factory returning an object); assert a gemini target builds a GeminiAdapter with `.grounded` propagated. (The existing grounded-propagation test passes a gemini target — update its factory kwarg name.)

Run the full suite; fix any test referencing the old `gemini_model_factory`/model_factory.

### Task 3: Config swap to GPT-5.5

**Files:** `config/llm_targets.yaml`, `config_demo/llm_targets.yaml`.

- In BOTH files: rename `GPT-4o` → `GPT-5.5`, `model_version: gpt-5.5-2026-04-23`, `params: {max_completion_tokens: 4096}` (remove temperature + max_tokens). Rename `GPT-4o-Grounded` → `GPT-5.5-Grounded`, `model_version: gpt-5.5-2026-04-23`, `grounded: true`, `params: {max_completion_tokens: 4096}`. Leave the Gemini + Claude targets unchanged. (config_demo is a copy of config; keep them in sync.)
- Update the pinned-version comment to note IN-103. Pricing values can stay (not load-critical); optionally note GPT-5.5 pricing in a comment.
- Verify: `python -c "from ema_poc.config import load_config; print([(t.name,t.model_version,t.params) for t in load_config('config').targets])"` shows the GPT-5.5 targets with max_completion_tokens and no temperature.

Run FULL suite green after each task. Commit per task. Final whole-branch review, then the controller live-verifies with `ema healthcheck`.

---

## Self-Review Notes (author)
- OpenAI params now config-driven (temperature optional; max_completion_tokens vs max_tokens) — GPT-5.5 + GPT-4o both supported, no model-family hardcoding.
- Gemini fully on google-genai (client-injected, lazy import); grounding works; tests use a fake client (offline) though `google.genai.types` is imported (installed, harmless).
- Registry gemini factory renamed model_factory→client_factory; update its tests.
- Config swap in BOTH config dirs (config + config_demo) to keep the demo run consistent.
- Type consistency: `GeminiAdapter(*, name, model_version, params, client, grounded=False)`; `gemini_client_factory(api_key)->client`; OpenAI `_query_chat` kwargs config-driven.
