# Evidence Monitoring Agent — LLM Adapters Implementation Plan (Phase 3A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pluggable LLM adapter layer (FR-201, FR-203, FR-205, IN-1/2/3, IN-204, FR-211): a shared `LLMAdapter` interface, vendor adapters for OpenAI (GPT-4o), Google Gemini, and Anthropic Claude (queried as a monitored end-user target), and a config-driven registry that builds the enabled adapters. Each adapter normalizes its vendor's response into a common `LLMResponse` (text, normalized finish_reason, status SUCCESS/TRUNCATED/BLOCKED, token counts, raw audit dict).

**Architecture:** `ema_poc/adapters/` — one module per vendor behind `base.LLMAdapter`. Adapters hold their vendor client (or, for Gemini, a per-system-prompt model factory) injected at construction, so unit tests pass fakes and **no real network calls or vendor-SDK imports happen in the test suite**. Vendor SDKs are imported lazily inside registry factory functions (only invoked in production). Retry/backoff/rate-limiting are NOT here — they live in the executor (Phase 3B); adapters return an `LLMResponse` for any response received (including blocked/truncated) and raise on transport errors for the executor to retry.

**Tech Stack:** Python 3.11+, Pydantic config (Phase 1), `anthropic` / `openai` / `google-generativeai` SDKs (production deps; lazily imported), pytest with injected fakes.

**Spec:** `docs/superpowers/specs/2026-06-13-evidence-monitoring-agent-poc-design.md` (§3 adapters, IN-1/2/3). Model/API rules: Claude target uses `thinking={"type":"adaptive"}`, `max_tokens` from config, and **no temperature** (Opus 4.8 rejects `temperature`/`top_p`/`budget_tokens`); OpenAI/Gemini use `temperature` + max-tokens from config.

**Conventions:**
- `LLMResponse.status` strings match `ResponseStatus` values: `"SUCCESS" | "FAILED" | "TRUNCATED" | "BLOCKED"`.
- `LLMResponse.finish_reason` is normalized to `"stop" | "length" | "error" | "blocked"`.
- `raw` is a small JSON-serializable dict for the audit trail (not the raw SDK object).
- Activate the venv with `. .venv/bin/activate` before pytest.
- No top-level vendor-SDK imports anywhere in `ema_poc/adapters/` — SDK imports go inside registry factory functions only.

---

### Task 1: Adapter base interface

**Files:**
- Create: `ema_poc/adapters/__init__.py`
- Create: `ema_poc/adapters/base.py`
- Test: `tests/adapters/__init__.py`
- Test: `tests/adapters/test_base.py`

- [ ] **Step 1: Write the failing test**

`tests/adapters/__init__.py`:
```python
```

`tests/adapters/test_base.py`:
```python
import pytest

from ema_poc.adapters.base import LLMAdapter, LLMResponse


def test_llm_response_defaults():
    r = LLMResponse(text="hi", finish_reason="stop", status="SUCCESS")
    assert r.prompt_tokens is None
    assert r.completion_tokens is None
    assert r.raw == {}


def test_llm_adapter_is_abstract():
    with pytest.raises(TypeError):
        LLMAdapter()  # cannot instantiate an ABC with an abstract method


def test_subclass_must_implement_query():
    class Incomplete(LLMAdapter):
        pass

    with pytest.raises(TypeError):
        Incomplete()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/adapters/test_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.adapters'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/adapters/__init__.py`:
```python
"""LLM adapter layer — one module per vendor behind a shared interface (§3)."""
```

`ema_poc/adapters/base.py`:
```python
"""Shared LLM adapter interface and normalized response (§3, FR-201)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


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


class LLMAdapter(ABC):
    """A monitored LLM target. Subclasses own vendor request-shaping and
    response normalization only; retry/rate-limiting live in the executor."""

    name: str
    model_version: str

    @abstractmethod
    def query(self, system_prompt: str, question_text: str) -> LLMResponse:
        """Submit one question and return a normalized LLMResponse. May raise
        on transport errors (the executor retries those)."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/adapters/test_base.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/adapters/__init__.py ema_poc/adapters/base.py tests/adapters/__init__.py tests/adapters/test_base.py
git commit -m "feat: LLMAdapter interface and normalized LLMResponse"
```

---

### Task 2: OpenAI adapter

**Files:**
- Create: `ema_poc/adapters/openai_adapter.py`
- Test: `tests/adapters/test_openai_adapter.py`

- [ ] **Step 1: Write the failing test**

`tests/adapters/test_openai_adapter.py`:
```python
from ema_poc.adapters.openai_adapter import OpenAIAdapter


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content, finish_reason):
        self.message = _Msg(content)
        self.finish_reason = finish_reason


class _Usage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c


class _Completion:
    def __init__(self, content, finish_reason, p=10, c=20):
        self.choices = [_Choice(content, finish_reason)]
        self.usage = _Usage(p, c)


class _FakeOpenAI:
    """Mimics client.chat.completions.create(...)."""

    def __init__(self, completion):
        self._completion = completion
        self.kwargs = None
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self._completion


def _adapter(completion):
    return OpenAIAdapter(
        name="GPT-4o",
        model_version="gpt-4o-2024-11-20",
        params={"temperature": 0.3, "max_tokens": 1024},
        client=_FakeOpenAI(completion),
    )


def test_success_response():
    adapter = _adapter(_Completion("Drug X is first-line.", "stop"))
    r = adapter.query("You are a clinician.", "Is drug X first-line?")
    assert r.status == "SUCCESS"
    assert r.finish_reason == "stop"
    assert r.text == "Drug X is first-line."
    assert r.prompt_tokens == 10
    assert r.completion_tokens == 20


def test_request_shape_includes_system_and_user_and_params():
    fake = _FakeOpenAI(_Completion("ok", "stop"))
    adapter = OpenAIAdapter(
        name="GPT-4o",
        model_version="gpt-4o-2024-11-20",
        params={"temperature": 0.3, "max_tokens": 1024},
        client=fake,
    )
    adapter.query("SYS", "USER")
    assert fake.kwargs["model"] == "gpt-4o-2024-11-20"
    assert fake.kwargs["temperature"] == 0.3
    assert fake.kwargs["max_tokens"] == 1024
    assert fake.kwargs["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]


def test_truncated_when_finish_reason_length():
    adapter = _adapter(_Completion("cut off mid-", "length"))
    r = adapter.query("s", "q")
    assert r.status == "TRUNCATED"
    assert r.finish_reason == "length"


def test_none_content_becomes_empty_string():
    adapter = _adapter(_Completion(None, "stop"))
    r = adapter.query("s", "q")
    assert r.text == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/adapters/test_openai_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.adapters.openai_adapter'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/adapters/openai_adapter.py`:
```python
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
        truncated = finish == "length"
        return LLMResponse(
            text=text,
            finish_reason="length" if truncated else "stop",
            status="TRUNCATED" if truncated else "SUCCESS",
            prompt_tokens=getattr(resp.usage, "prompt_tokens", None),
            completion_tokens=getattr(resp.usage, "completion_tokens", None),
            raw={"finish_reason": finish, "model": self.model_version},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/adapters/test_openai_adapter.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/adapters/openai_adapter.py tests/adapters/test_openai_adapter.py
git commit -m "feat: OpenAI GPT-4o adapter"
```

---

### Task 3: Gemini adapter

**Files:**
- Create: `ema_poc/adapters/gemini_adapter.py`
- Test: `tests/adapters/test_gemini_adapter.py`

- [ ] **Step 1: Write the failing test**

`tests/adapters/test_gemini_adapter.py`:
```python
from ema_poc.adapters.gemini_adapter import GeminiAdapter


class _Enum:
    """Mimics a google enum value with a .name attribute."""

    def __init__(self, name):
        self.name = name


class _Usage:
    def __init__(self, p, c):
        self.prompt_token_count = p
        self.candidates_token_count = c


class _Candidate:
    def __init__(self, finish_reason_name):
        self.finish_reason = _Enum(finish_reason_name)


class _Feedback:
    def __init__(self, block_reason_name):
        self.block_reason = _Enum(block_reason_name) if block_reason_name else None


class _GeminiResp:
    def __init__(self, text, finish_reason_name, block_reason_name=None, p=5, c=7):
        self.text = text
        self.candidates = [_Candidate(finish_reason_name)]
        self.prompt_feedback = _Feedback(block_reason_name)
        self.usage_metadata = _Usage(p, c)


class _FakeModel:
    def __init__(self, resp):
        self._resp = resp
        self.gen_config = None

    def generate_content(self, text, generation_config=None):
        self.text = text
        self.gen_config = generation_config
        return self._resp


def _adapter(resp, capture=None):
    def factory(system_prompt):
        m = _FakeModel(resp)
        if capture is not None:
            capture["system"] = system_prompt
            capture["model"] = m
        return m

    return GeminiAdapter(
        name="Gemini-1.5-Pro",
        model_version="gemini-1.5-pro",
        params={"temperature": 0.3, "max_output_tokens": 1024},
        model_factory=factory,
    )


def test_success_response_and_tokens():
    adapter = _adapter(_GeminiResp("Drug X is second-line.", "STOP"))
    r = adapter.query("clinical context", "Is drug X first-line?")
    assert r.status == "SUCCESS"
    assert r.finish_reason == "stop"
    assert r.text == "Drug X is second-line."
    assert r.prompt_tokens == 5
    assert r.completion_tokens == 7


def test_factory_receives_system_prompt_and_config():
    capture = {}
    adapter = _adapter(_GeminiResp("ok", "STOP"), capture=capture)
    adapter.query("SYSTEM", "QUESTION")
    assert capture["system"] == "SYSTEM"
    assert capture["model"].text == "QUESTION"
    assert capture["model"].gen_config["temperature"] == 0.3
    assert capture["model"].gen_config["max_output_tokens"] == 1024


def test_safety_block_via_candidate_finish_reason():
    adapter = _adapter(_GeminiResp("", "SAFETY"))
    r = adapter.query("s", "q")
    assert r.status == "BLOCKED"
    assert r.finish_reason == "blocked"


def test_safety_block_via_prompt_feedback():
    adapter = _adapter(_GeminiResp("", "STOP", block_reason_name="SAFETY"))
    r = adapter.query("s", "q")
    assert r.status == "BLOCKED"


def test_truncated_when_max_tokens():
    adapter = _adapter(_GeminiResp("partial", "MAX_TOKENS"))
    r = adapter.query("s", "q")
    assert r.status == "TRUNCATED"
    assert r.finish_reason == "length"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/adapters/test_gemini_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.adapters.gemini_adapter'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/adapters/gemini_adapter.py`:
```python
"""Google Gemini adapter — system instruction + user content (IN-2, IN-204).

The Gemini SDK sets the system instruction at model construction, so this
adapter is given a `model_factory(system_prompt) -> model` callable and builds
a fresh model per query (system prompt varies per persona)."""

from __future__ import annotations

from typing import Callable

from ema_poc.adapters.base import LLMAdapter, LLMResponse


def _name(value) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", None) or str(value)


class GeminiAdapter(LLMAdapter):
    def __init__(
        self,
        *,
        name: str,
        model_version: str,
        params: dict,
        model_factory: Callable[[str], object],
    ):
        self.name = name
        self.model_version = model_version
        self.params = params
        self._model_factory = model_factory

    def query(self, system_prompt: str, question_text: str) -> LLMResponse:
        model = self._model_factory(system_prompt)
        resp = model.generate_content(
            question_text,
            generation_config={
                "temperature": self.params.get("temperature", 0.3),
                "max_output_tokens": self.params.get("max_output_tokens", 1024),
            },
        )

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
        return LLMResponse(
            text=getattr(resp, "text", "") or "",
            finish_reason="length" if truncated else "stop",
            status="TRUNCATED" if truncated else "SUCCESS",
            prompt_tokens=ptok,
            completion_tokens=ctok,
            raw={"finish_reason": finish_name, "model": self.model_version},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/adapters/test_gemini_adapter.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/adapters/gemini_adapter.py tests/adapters/test_gemini_adapter.py
git commit -m "feat: Gemini adapter with safety-block detection"
```

---

### Task 4: Claude target adapter

**Files:**
- Create: `ema_poc/adapters/claude_adapter.py`
- Test: `tests/adapters/test_claude_adapter.py`

- [ ] **Step 1: Write the failing test**

`tests/adapters/test_claude_adapter.py`:
```python
from ema_poc.adapters.claude_adapter import ClaudeTargetAdapter


class _Block:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class _Usage:
    def __init__(self, i, o):
        self.input_tokens = i
        self.output_tokens = o


class _Message:
    def __init__(self, content, stop_reason, i=12, o=8):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _Usage(i, o)


class _FakeAnthropic:
    """Mimics client.messages.create(...)."""

    def __init__(self, message):
        self._message = message
        self.kwargs = None
        self.messages = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self._message


def _adapter(message, fake=None):
    client = fake or _FakeAnthropic(message)
    return ClaudeTargetAdapter(
        name="Claude-Opus-4.8",
        model_version="claude-opus-4-8",
        params={"max_tokens": 1024},
        client=client,
    )


def test_success_joins_text_blocks_and_maps_tokens():
    msg = _Message(
        [_Block("thinking", "..."), _Block("text", "First-line "), _Block("text", "use.")],
        "end_turn",
    )
    r = _adapter(msg).query("You are a patient.", "Is drug X first-line?")
    assert r.status == "SUCCESS"
    assert r.finish_reason == "stop"
    assert r.text == "First-line use."  # only text blocks, thinking excluded
    assert r.prompt_tokens == 12
    assert r.completion_tokens == 8


def test_request_uses_adaptive_thinking_and_no_temperature():
    fake = _FakeAnthropic(_Message([_Block("text", "ok")], "end_turn"))
    _adapter(None, fake=fake).query("SYS", "Q")
    assert fake.kwargs["model"] == "claude-opus-4-8"
    assert fake.kwargs["max_tokens"] == 1024
    assert fake.kwargs["thinking"] == {"type": "adaptive"}
    assert fake.kwargs["system"] == "SYS"
    assert fake.kwargs["messages"] == [{"role": "user", "content": "Q"}]
    assert "temperature" not in fake.kwargs  # Opus 4.8 rejects temperature


def test_max_tokens_stop_reason_is_truncated():
    r = _adapter(_Message([_Block("text", "partial")], "max_tokens")).query("s", "q")
    assert r.status == "TRUNCATED"
    assert r.finish_reason == "length"


def test_refusal_stop_reason_is_blocked():
    r = _adapter(_Message([], "refusal")).query("s", "q")
    assert r.status == "BLOCKED"
    assert r.finish_reason == "blocked"
    assert r.text == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/adapters/test_claude_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.adapters.claude_adapter'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/adapters/claude_adapter.py`:
```python
"""Anthropic Claude adapter — Claude queried as a monitored end-user target
(IN-3, IN-301/303). Adaptive thinking; max_tokens from config; NO temperature
(Opus 4.8 rejects temperature/top_p/budget_tokens). Distinct from the
orchestrator/scoring Claude client; the runner tags this role=TARGET."""

from __future__ import annotations

from ema_poc.adapters.base import LLMAdapter, LLMResponse

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


class ClaudeTargetAdapter(LLMAdapter):
    def __init__(self, *, name: str, model_version: str, params: dict, client):
        self.name = name
        self.model_version = model_version
        self.params = params
        self._client = client

    def query(self, system_prompt: str, question_text: str) -> LLMResponse:
        resp = self._client.messages.create(
            model=self.model_version,
            max_tokens=self.params.get("max_tokens", 1024),
            thinking={"type": "adaptive"},
            system=system_prompt,
            messages=[{"role": "user", "content": question_text}],
        )
        text = "".join(
            getattr(b, "text", "") for b in resp.content
            if getattr(b, "type", None) == "text"
        )
        stop = resp.stop_reason
        return LLMResponse(
            text=text,
            finish_reason=_FINISH_BY_STOP.get(stop, "stop"),
            status=_STATUS_BY_STOP.get(stop, "SUCCESS"),
            prompt_tokens=getattr(resp.usage, "input_tokens", None),
            completion_tokens=getattr(resp.usage, "output_tokens", None),
            raw={"stop_reason": stop, "model": self.model_version},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/adapters/test_claude_adapter.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/adapters/claude_adapter.py tests/adapters/test_claude_adapter.py
git commit -m "feat: Claude monitored-target adapter (adaptive thinking, no temperature)"
```

---

### Task 5: Adapter registry

**Files:**
- Create: `ema_poc/adapters/registry.py`
- Test: `tests/adapters/test_registry.py`

- [ ] **Step 1: Write the failing test**

`tests/adapters/test_registry.py`:
```python
import pytest

from ema_poc.adapters.claude_adapter import ClaudeTargetAdapter
from ema_poc.adapters.gemini_adapter import GeminiAdapter
from ema_poc.adapters.openai_adapter import OpenAIAdapter
from ema_poc.adapters.registry import build_adapters
from ema_poc.config import (
    AppConfig,
    BrandConfig,
    LLMTargetConfig,
    PricingConfig,
    RateLimitConfig,
    Settings,
)


def _target(name, adapter, enabled=True):
    return LLMTargetConfig(
        name=name,
        adapter=adapter,
        model_version="m",
        api_key_env=f"{adapter.upper()}_KEY",
        enabled=enabled,
        pricing=PricingConfig(input_per_1k=0.0, output_per_1k=0.0),
        rate_limit=RateLimitConfig(requests_per_minute=60, tokens_per_minute=1000),
    )


def _config(targets):
    return AppConfig(settings=Settings(), brands=BrandConfig(), targets=targets)


# Fake factories — capture the api key/model they would build with, return a sentinel
def _fake_factories():
    seen = {}

    def openai_factory(api_key):
        seen["openai"] = api_key
        return f"openai-client::{api_key}"

    def gemini_factory(api_key, model_version, system_instruction=None):
        seen.setdefault("gemini", []).append((api_key, model_version, system_instruction))
        return f"gemini-model::{system_instruction}"

    def anthropic_factory(api_key):
        seen["anthropic"] = api_key
        return f"anthropic-client::{api_key}"

    return seen, openai_factory, gemini_factory, anthropic_factory


def test_builds_one_adapter_per_enabled_target():
    cfg = _config([
        _target("GPT-4o", "openai"),
        _target("Gemini", "gemini"),
        _target("Claude", "claude"),
    ])
    env = {"OPENAI_KEY": "k-o", "GEMINI_KEY": "k-g", "CLAUDE_KEY": "k-c"}
    seen, of, gf, af = _fake_factories()
    adapters = build_adapters(
        cfg, env,
        openai_client_factory=of, gemini_model_factory=gf, anthropic_client_factory=af,
    )
    assert [type(a) for a in adapters] == [
        OpenAIAdapter, GeminiAdapter, ClaudeTargetAdapter
    ]
    assert seen["openai"] == "k-o"
    assert seen["anthropic"] == "k-c"


def test_skips_disabled_targets():
    cfg = _config([
        _target("GPT-4o", "openai"),
        _target("Gemini", "gemini", enabled=False),
    ])
    env = {"OPENAI_KEY": "k-o", "GEMINI_KEY": "k-g"}
    seen, of, gf, af = _fake_factories()
    adapters = build_adapters(
        cfg, env,
        openai_client_factory=of, gemini_model_factory=gf, anthropic_client_factory=af,
    )
    assert [a.name for a in adapters] == ["GPT-4o"]


def test_gemini_model_factory_binds_key_and_passes_system_per_query():
    cfg = _config([_target("Gemini", "gemini")])
    env = {"GEMINI_KEY": "k-g"}
    seen, of, gf, af = _fake_factories()
    [gemini] = build_adapters(
        cfg, env,
        openai_client_factory=of, gemini_model_factory=gf, anthropic_client_factory=af,
    )
    # The adapter's model_factory should call the gemini factory with the bound
    # key + model and the per-query system prompt.
    model = gemini._model_factory("PERSONA SYSTEM")
    assert model == "gemini-model::PERSONA SYSTEM"
    assert seen["gemini"][-1] == ("k-g", "m", "PERSONA SYSTEM")


def test_unknown_adapter_raises():
    cfg = _config([_target("Mystery", "mystery")])
    env = {"MYSTERY_KEY": "k"}
    seen, of, gf, af = _fake_factories()
    with pytest.raises(ValueError):
        build_adapters(
            cfg, env,
            openai_client_factory=of, gemini_model_factory=gf, anthropic_client_factory=af,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/adapters/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.adapters.registry'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/adapters/registry.py`:
```python
"""Build the enabled LLM adapters from config (NF-010).

Vendor SDKs are imported lazily inside the default factory functions, so
importing this module (and the unit tests, which inject fake factories) never
requires the SDKs to be installed."""

from __future__ import annotations

from collections.abc import Mapping

from ema_poc.adapters.base import LLMAdapter
from ema_poc.adapters.claude_adapter import ClaudeTargetAdapter
from ema_poc.adapters.gemini_adapter import GeminiAdapter
from ema_poc.adapters.openai_adapter import OpenAIAdapter
from ema_poc.config import AppConfig


def _default_openai_client(api_key: str):
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def _default_gemini_model(api_key: str, model_version: str, system_instruction=None):
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_version, system_instruction=system_instruction)


def _default_anthropic_client(api_key: str):
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


def build_adapters(
    config: AppConfig,
    env: Mapping[str, str],
    *,
    openai_client_factory=_default_openai_client,
    gemini_model_factory=_default_gemini_model,
    anthropic_client_factory=_default_anthropic_client,
) -> list[LLMAdapter]:
    adapters: list[LLMAdapter] = []
    for target in config.targets:
        if not target.enabled:
            continue
        api_key = env[target.api_key_env]
        if target.adapter == "openai":
            adapters.append(
                OpenAIAdapter(
                    name=target.name,
                    model_version=target.model_version,
                    params=target.params,
                    client=openai_client_factory(api_key),
                )
            )
        elif target.adapter == "gemini":
            adapters.append(
                GeminiAdapter(
                    name=target.name,
                    model_version=target.model_version,
                    params=target.params,
                    model_factory=lambda system_prompt, _k=api_key, _m=target.model_version: (
                        gemini_model_factory(_k, _m, system_prompt)
                    ),
                )
            )
        elif target.adapter == "claude":
            adapters.append(
                ClaudeTargetAdapter(
                    name=target.name,
                    model_version=target.model_version,
                    params=target.params,
                    client=anthropic_client_factory(api_key),
                )
            )
        else:
            raise ValueError(f"Unknown adapter type: {target.adapter!r}")
    return adapters
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/adapters/test_registry.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/adapters/registry.py tests/adapters/test_registry.py
git commit -m "feat: config-driven adapter registry with injectable factories"
```

---

### Task 6: Vendor deps + adapter integration test

**Files:**
- Modify: `pyproject.toml` (add vendor SDK dependencies)
- Test: `tests/adapters/test_adapters_integration.py`

- [ ] **Step 1: Add vendor SDKs to dependencies**

In `pyproject.toml`, change:
```toml
dependencies = [
    "pydantic>=2",
    "pyyaml",
    "openpyxl",
]
```
to:
```toml
dependencies = [
    "pydantic>=2",
    "pyyaml",
    "openpyxl",
    "anthropic",
    "openai",
    "google-generativeai",
]
```
(Do NOT `pip install` these into the test venv — the unit/integration tests inject fakes and the adapter modules never import the SDKs at top level. They are runtime deps for production only.)

- [ ] **Step 2: Write the integration test**

`tests/adapters/test_adapters_integration.py`:
```python
"""Build all three adapters from a config via the registry (with fake vendor
clients) and run a query through each, asserting a normalized LLMResponse."""

from ema_poc.adapters.registry import build_adapters
from ema_poc.config import (
    AppConfig,
    BrandConfig,
    LLMTargetConfig,
    PricingConfig,
    RateLimitConfig,
    Settings,
)


# --- Minimal fakes for each vendor client shape ---
class _OAIMsg:
    def __init__(self, content):
        self.content = content


class _OAIChoice:
    def __init__(self, content, finish):
        self.message = _OAIMsg(content)
        self.finish_reason = finish


class _OAIUsage:
    prompt_tokens = 1
    completion_tokens = 2


class _OAICompletion:
    def __init__(self, content, finish):
        self.choices = [_OAIChoice(content, finish)]
        self.usage = _OAIUsage()


class _FakeOpenAI:
    def __init__(self):
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        return _OAICompletion("openai answer", "stop")


class _GEnum:
    def __init__(self, name):
        self.name = name


class _GUsage:
    prompt_token_count = 3
    candidates_token_count = 4


class _GCandidate:
    finish_reason = _GEnum("STOP")


class _GFeedback:
    block_reason = None


class _GResp:
    text = "gemini answer"
    candidates = [_GCandidate()]
    prompt_feedback = _GFeedback()
    usage_metadata = _GUsage()


class _FakeGeminiModel:
    def generate_content(self, text, generation_config=None):
        return _GResp()


class _CBlock:
    def __init__(self, type_, text):
        self.type = type_
        self.text = text


class _CUsage:
    input_tokens = 5
    output_tokens = 6


class _CMessage:
    content = [_CBlock("text", "claude answer")]
    stop_reason = "end_turn"
    usage = _CUsage()


class _FakeAnthropic:
    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        return _CMessage()


def _config():
    def t(name, adapter):
        return LLMTargetConfig(
            name=name, adapter=adapter, model_version="m",
            api_key_env=f"{adapter.upper()}_KEY",
            pricing=PricingConfig(input_per_1k=0.0, output_per_1k=0.0),
            rate_limit=RateLimitConfig(requests_per_minute=60, tokens_per_minute=1000),
        )

    return AppConfig(
        settings=Settings(),
        brands=BrandConfig(),
        targets=[t("GPT-4o", "openai"), t("Gemini", "gemini"), t("Claude", "claude")],
    )


def test_all_adapters_query_and_normalize():
    env = {"OPENAI_KEY": "k", "GEMINI_KEY": "k", "CLAUDE_KEY": "k"}
    adapters = build_adapters(
        _config(),
        env,
        openai_client_factory=lambda key: _FakeOpenAI(),
        gemini_model_factory=lambda key, model, system_instruction=None: _FakeGeminiModel(),
        anthropic_client_factory=lambda key: _FakeAnthropic(),
    )
    results = {a.name: a.query("system context", "Is drug X first-line?") for a in adapters}

    assert results["GPT-4o"].status == "SUCCESS"
    assert results["GPT-4o"].text == "openai answer"
    assert results["Gemini"].status == "SUCCESS"
    assert results["Gemini"].text == "gemini answer"
    assert results["Claude"].status == "SUCCESS"
    assert results["Claude"].text == "claude answer"
    # every result is a normalized response with token accounting
    for r in results.values():
        assert r.finish_reason in {"stop", "length", "blocked", "error"}
        assert r.prompt_tokens is not None
```

- [ ] **Step 3: Run the integration test**

Run: `. .venv/bin/activate && pytest tests/adapters/test_adapters_integration.py -v`
Expected: PASS (1 passed). If it fails, the failure points at a real adapter/registry wiring gap — fix the referenced module, do not weaken the test.

- [ ] **Step 4: Run the whole suite with coverage**

Run: `. .venv/bin/activate && pytest -q --cov`
Expected: PASS (all Phase 1 + 2 + 3A tests green); coverage report prints. Confirm the test suite does NOT import `anthropic`, `openai`, or `google.generativeai` (it must pass without those installed).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/adapters/test_adapters_integration.py
git commit -m "test: adapter registry integration; add vendor SDK runtime deps"
```

---

## Self-Review

**Spec coverage (Phase 3A scope):**
- FR-201/203 adapters per LLM target behind a shared interface → `base.LLMAdapter` + OpenAI/Gemini/Claude adapters → Tasks 1–4.
- FR-205 LLM-specific system prompt contextualizing the query → each adapter sends `system_prompt` (OpenAI system message, Gemini system instruction, Claude `system=`) → Tasks 2–4.
- IN-101/102/104 OpenAI Chat Completions, messages array, temperature/max_tokens from config → Task 2.
- IN-201/203/204 Gemini system instruction + content, params, safety-block → BLOCKED → Task 3.
- IN-301/303 Claude as monitored target, adaptive thinking, max_tokens, NO temperature → Task 4.
- FR-211 truncation detection (finish_reason length / max_tokens → TRUNCATED) → Tasks 2–4 (retry-with-adjusted-max_tokens is the executor's job in Phase 3B).
- NF-010 add a target via config + adapter module only → `registry.build_adapters` dispatches on `target.adapter` → Task 5.
- Token capture for cost/audit (NF-014) → `prompt_tokens`/`completion_tokens` on every `LLMResponse`.

Deferred to Phase 3B (correctly out of scope here): retry/backoff, per-target rate limiting, the truncation *retry* action, the run loop, response/run persistence, resumability, audit-log writes, run summary, dry-run/health-check CLI. Deferred to later phases: Open Evidence adapter (conditional, IN-4) — same interface, add when access is confirmed.

**Placeholder scan:** No "TBD"/"add error handling"/"similar to" placeholders — every code and test step is complete.

**Type/name consistency:** `LLMAdapter`, `LLMResponse` (fields text/finish_reason/status/prompt_tokens/completion_tokens/raw) are defined in Task 1 and used identically in Tasks 2–6. `OpenAIAdapter`/`GeminiAdapter`/`ClaudeTargetAdapter` constructor kwargs (`name`, `model_version`, `params`, and `client` or `model_factory`) match how `build_adapters` instantiates them in Task 5 and the integration test in Task 6. Status strings (`SUCCESS`/`TRUNCATED`/`BLOCKED`) match `ResponseStatus` values from Phase 1; normalized finish_reason strings (`stop`/`length`/`blocked`/`error`) are consistent across all adapters. The registry's `gemini_model_factory(api_key, model_version, system_instruction=None)` signature matches both the default factory and the fakes in Tasks 5–6.
