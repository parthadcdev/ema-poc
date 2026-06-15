# Model Modernization (GPT-5.5 + google-genai Gemini) — Design

**Date:** 2026-06-15
**Status:** Approved
**Addresses:** Grounded Gemini failed live (legacy SDK can't do Gemini-2.5 search
grounding); operator wants GPT-5.5 instead of GPT-4o.

## Verified facts (live probes)
- `gpt-5.5` (reasoning model) **rejects** `max_tokens` (needs
  `max_completion_tokens`) and our `temperature=0.3`; its Responses-API
  `web_search` grounding works as-is.
- Gemini-2.5 native Google-Search grounding requires the **`google-genai`** SDK
  (`client.models.generate_content(config=GenerateContentConfig(tools=[Tool(
  google_search=GoogleSearch())]))`); response carries `.text`,
  `candidates[0].finish_reason.name`, `candidates[0].grounding_metadata.
  grounding_chunks[].web.{uri,title}`, `usage_metadata.{prompt_token_count,
  candidates_token_count}`, `model_version`. Verified working (5 citations).

## 1. OpenAI adapter — config-driven params (`openai_adapter.py`)
The ungrounded chat path must support both GPT-4o (temperature + max_tokens) and
GPT-5.5 (max_completion_tokens, no temperature). Make it pass through the target's
`params` instead of hardcoding:
- Include `temperature` in the request **only if** `"temperature"` is in
  `self.params`.
- For the output-token cap: if `"max_completion_tokens"` in params → send
  `max_completion_tokens=…`; elif `"max_tokens"` in params → send `max_tokens=…`;
  else default `max_tokens=1024`.
The grounded path (`_query_grounded`, Responses API, `max_output_tokens`) is
unchanged — already works for GPT-5.5.

## 2. Gemini adapter — migrate to `google-genai` (`gemini_adapter.py`, `registry.py`)
- Add `google-genai` to `pyproject.toml` deps.
- `GeminiAdapter` now holds an injected **client** (not a model_factory):
  `__init__(*, name, model_version, params, client, grounded=False)`.
- `query(system_prompt, question_text)`:
  - Build config via `from google.genai import types`:
    `types.GenerateContentConfig(system_instruction=system_prompt,
    max_output_tokens=params.get("max_output_tokens", 4096),
    temperature=params["temperature"] if "temperature" in params else None,
    tools=[types.Tool(google_search=types.GoogleSearch())] if grounded else None)`.
  - `resp = client.models.generate_content(model=model_version,
    contents=question_text, config=config)`.
  - Normalize: `finish = resp.candidates[0].finish_reason.name` (or None) →
    SAFETY/blocked → BLOCKED; MAX_TOKENS → TRUNCATED/"length"; else SUCCESS/"stop".
    Also treat `resp.prompt_feedback.block_reason` as BLOCKED. text = `resp.text or ""`.
  - citations (grounded): `grounding_metadata.grounding_chunks[].web.{uri,title}` →
    `Citation`, deduped by url.
  - tokens: `usage_metadata.prompt_token_count` / `.candidates_token_count`.
  - `actual_model`: `getattr(resp, "model_version", None)` (model-drift detection).
- `registry.build_adapters`: the gemini branch builds the adapter with a client
  from a `gemini_client_factory(api_key)` (default: lazy `from google import genai;
  genai.Client(api_key=api_key)`), replacing the old `gemini_model_factory`.
- The legacy `google-generativeai` import is removed from the registry/adapter.
- Lazy import preserved: `google.genai`/`types` imported only inside the default
  factory + inside the adapter's `query` (for `types`), never at module top.

## 3. Config swap (`config/llm_targets.yaml` + `config_demo/llm_targets.yaml`)
- `GPT-4o` → name **`GPT-5.5`**, `model_version: gpt-5.5-2026-04-23`,
  `params: {max_completion_tokens: 4096}` (no temperature).
- `GPT-4o-Grounded` → **`GPT-5.5-Grounded`**, same model, `grounded: true`,
  `params: {max_completion_tokens: 4096}`.
- Gemini targets unchanged (`gemini-2.5-pro`; grounding now works).
- Update pricing comments if desired (GPT-5.5 pricing differs; not load-critical).

## Testing (offline)
- OpenAI adapter: fake client captures kwargs — temperature omitted when not in
  params; `max_completion_tokens` sent when in params; GPT-4o-style params still
  send temperature + max_tokens; grounded path unchanged.
- Gemini adapter: fake google-genai client (`client.models.generate_content(...)
  -> fake response` with `.text`, `.candidates[0].finish_reason.name`,
  `.grounding_metadata.grounding_chunks[].web`, `.usage_metadata`, `.model_version`,
  `.prompt_feedback`); assert SUCCESS/TRUNCATED/BLOCKED normalization, grounded
  tool passed in config + citations parsed, ungrounded sends no tools, actual_model
  captured. All offline (no SDK/network — fakes).
- Registry: gemini branch builds an adapter with the injected client factory;
  grounded flag propagates.

## Verification (manual, post-build)
`ema healthcheck` → all 6 targets connect (GPT-5.5, GPT-5.5-Grounded, Gemini-2.5-Pro,
Gemini-2.5-Pro-Grounded, Claude-Opus-4.8, Claude-Opus-4.8-Grounded).

## Out of scope (deferrable)
- Removing the now-unused `google-generativeai` package from the environment.
- Migrating the scoring/hallucination Claude clients (unrelated; already correct).
