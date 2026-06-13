# Grounded Targets & Citations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add web-grounded variants of each LLM target that answer using live web search and return source citations, persisted append-only and shown in the daily run + dashboard.

**Architecture:** A `grounded: bool` flag on each target config switches that vendor's adapter into web-search mode (OpenAI Responses `web_search`, Gemini `google_search`, Claude server-side `web_search`). Each adapter normalizes provider citations into a shared `Citation` type carried on `LLMResponse`. The runner persists citations into a new insert-only `response_citations` table (responses stay immutable, FR-304).

**Tech Stack:** Python 3.11+, stdlib `sqlite3`, Pydantic v2, vendor SDKs (`openai`, `google-generativeai`, `anthropic`) imported lazily. Tests use fake SDK objects — no network, no real SDKs required.

**Branch:** Create `feature/grounded-targets` off `develop` before Task 1.

**Conventions to follow (already in this codebase):**
- Vendor SDKs are imported lazily inside factory functions only (`ema_poc/adapters/registry.py`). Never import a vendor SDK at module top level.
- Adapters own request-shaping + response normalization only.
- All DB writes happen in the main thread; the executor/runner never write from worker threads.
- Run tests with: `source .venv/bin/activate && python -m pytest -q`

---

### Task 1: Citation type, `grounded` config flag, and `LLMResponse.citations`

**Files:**
- Modify: `ema_poc/adapters/base.py`
- Modify: `ema_poc/config.py:27-35` (the `LLMTargetConfig` class)
- Test: `tests/adapters/test_base.py` (create), `tests/test_config.py` (existing — add a case)

- [ ] **Step 1: Write the failing test for the Citation type and citations default**

Create `tests/adapters/test_base.py`:

```python
from ema_poc.adapters.base import Citation, LLMResponse


def test_llmresponse_defaults_to_no_citations():
    r = LLMResponse(text="hi", finish_reason="stop", status="SUCCESS")
    assert r.citations == []


def test_citation_holds_title_url_snippet():
    c = Citation(title="A Study", url="https://example.com/a", snippet="excerpt")
    assert (c.title, c.url, c.snippet) == ("A Study", "https://example.com/a", "excerpt")


def test_citation_snippet_optional():
    c = Citation(title="t", url="https://x")
    assert c.snippet is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/adapters/test_base.py -q`
Expected: FAIL with `ImportError: cannot import name 'Citation'`

- [ ] **Step 3: Add the Citation dataclass and citations field**

In `ema_poc/adapters/base.py`, add `Citation` above `LLMResponse` and a `citations` field on `LLMResponse`:

```python
@dataclass
class Citation:
    """A web source backing a grounded answer, normalized across vendors."""

    title: str
    url: str
    snippet: str | None = None


@dataclass
class LLMResponse:
    # ... existing fields unchanged ...
    text: str
    finish_reason: str
    status: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    raw: dict = field(default_factory=dict)
    citations: list[Citation] = field(default_factory=list)
```

Keep the existing docstring. `Citation` must be declared before `LLMResponse`.

- [ ] **Step 4: Run it to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/adapters/test_base.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Add the `grounded` config flag with a failing test**

In `tests/test_config.py`, add (adjust imports if the file already imports `load_config`):

```python
def test_target_grounded_defaults_false_and_parses_true(tmp_path):
    from ema_poc.config import LLMTargetConfig

    t = LLMTargetConfig(
        name="X", adapter="openai", model_version="m", api_key_env="K",
        pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
        rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1},
    )
    assert t.grounded is False
    t2 = LLMTargetConfig(
        name="Xg", adapter="openai", model_version="m", api_key_env="K", grounded=True,
        pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
        rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1},
    )
    assert t2.grounded is True
```

- [ ] **Step 6: Run it to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_config.py -q -k grounded`
Expected: FAIL (`grounded` not a field / validation error)

- [ ] **Step 7: Add the field**

In `ema_poc/config.py`, in `LLMTargetConfig`, add after `enabled: bool = True`:

```python
    grounded: bool = False
```

- [ ] **Step 8: Run it to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_config.py -q -k grounded`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add ema_poc/adapters/base.py ema_poc/config.py tests/adapters/test_base.py tests/test_config.py
git commit -m "feat: Citation type, grounded config flag, LLMResponse.citations"
```

---

### Task 2: `response_citations` table + citations repository

**Files:**
- Modify: `ema_poc/db.py` (add table to `SCHEMA`)
- Create: `ema_poc/repositories/citations.py`
- Test: `tests/repositories/test_citations.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/repositories/test_citations.py`:

```python
import sqlite3
import pytest

from ema_poc.db import connect, init_schema
from ema_poc.adapters.base import Citation
from ema_poc.repositories import citations as C


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    # response_citations has an FK to responses; insert a minimal parent run+response.
    conn.execute(
        "INSERT INTO runs (run_id, started_at) VALUES ('r1', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        """INSERT INTO responses (response_id, run_id, timestamp_utc, llm_name,
           llm_model_version, persona, question_id, question_text, domain,
           response_text, status, created_at)
           VALUES ('resp1','r1','2026-01-01T00:00:00+00:00','L','m','Provider',
           'Q1','q','General','ans','SUCCESS','2026-01-01T00:00:00+00:00')"""
    )
    conn.commit()
    return conn


def test_save_and_list_citations(tmp_path):
    conn = _conn(tmp_path)
    C.save_citations(
        conn, response_id="resp1",
        citations=[
            Citation(title="A", url="https://a", snippet="sa"),
            Citation(title="B", url="https://b"),
        ],
        now="2026-01-01T00:00:00+00:00",
        id_factory=iter(["c1", "c2"]).__next__,
    )
    rows = C.list_citations(conn, "resp1")
    assert [(r.title, r.url, r.snippet) for r in rows] == [
        ("A", "https://a", "sa"), ("B", "https://b", None)
    ]


def test_save_empty_citations_is_noop(tmp_path):
    conn = _conn(tmp_path)
    C.save_citations(conn, response_id="resp1", citations=[], now="2026-01-01T00:00:00+00:00")
    assert C.list_citations(conn, "resp1") == []


def test_citation_fk_rejects_unknown_response(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        C.save_citations(
            conn, response_id="nope", citations=[Citation(title="A", url="https://a")],
            now="2026-01-01T00:00:00+00:00", id_factory=iter(["c1"]).__next__,
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/repositories/test_citations.py -q`
Expected: FAIL (`No module named 'ema_poc.repositories.citations'`)

- [ ] **Step 3: Add the table to the schema**

In `ema_poc/db.py`, inside the `SCHEMA` string, add after the `scores` table block (before `alerts`):

```sql
CREATE TABLE IF NOT EXISTS response_citations (
    citation_id  TEXT PRIMARY KEY,
    response_id  TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    snippet      TEXT,
    created_at   TEXT NOT NULL,
    FOREIGN KEY (response_id) REFERENCES responses(response_id)
);
CREATE INDEX IF NOT EXISTS idx_citations_response ON response_citations(response_id);
```

- [ ] **Step 4: Implement the repository**

Create `ema_poc/repositories/citations.py`:

```python
"""Append-only citation storage for grounded responses (FR-304 safe).

Citations are child rows of an immutable response; insert-only, never updated."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from uuid import uuid4

from ema_poc.adapters.base import Citation


@dataclass
class CitationRow:
    citation_id: str
    response_id: str
    title: str
    url: str
    snippet: str | None
    created_at: str


def save_citations(
    conn: sqlite3.Connection,
    *,
    response_id: str,
    citations: list[Citation],
    now: str,
    id_factory=lambda: uuid4().hex,
    commit: bool = True,
) -> None:
    """Insert one row per citation. No-op for an empty list."""
    for c in citations:
        conn.execute(
            """INSERT INTO response_citations
               (citation_id, response_id, title, url, snippet, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (id_factory(), response_id, c.title, c.url, c.snippet, now),
        )
    if commit:
        conn.commit()


def list_citations(conn: sqlite3.Connection, response_id: str) -> list[CitationRow]:
    rows = conn.execute(
        """SELECT citation_id, response_id, title, url, snippet, created_at
           FROM response_citations WHERE response_id = ? ORDER BY created_at, citation_id""",
        (response_id,),
    ).fetchall()
    return [CitationRow(**dict(r)) for r in rows]
```

Note: `id_factory` accepts either a zero-arg callable or `iter([...]).__next__` (both are zero-arg callables), matching the test.

- [ ] **Step 5: Run it to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/repositories/test_citations.py -q`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add ema_poc/db.py ema_poc/repositories/citations.py tests/repositories/test_citations.py
git commit -m "feat: response_citations table + append-only citations repository"
```

---

### Task 3: OpenAI grounded adapter (Responses API web_search)

**Files:**
- Modify: `ema_poc/adapters/openai_adapter.py`
- Test: `tests/adapters/test_openai_adapter.py` (existing — add grounded cases; if absent, create)

**Design:** Add a `grounded: bool = False` constructor arg. When `grounded` is False, keep the existing `chat.completions.create` path unchanged. When True, call the Responses API with a web-search tool and parse `url_citation` annotations.

The OpenAI Responses web-search tool type and annotation shape must be confirmed against the installed SDK (`openai==2.41.1`): the tool is `{"type": "web_search_preview"}` and citations arrive as output-text annotations with `type == "url_citation"`, fields `url` and `title`. The adapter reads `resp.output_text` for text and walks `resp.output` blocks collecting annotations. Because tests inject a fake client, they pin this contract regardless of live API.

- [ ] **Step 1: Write the failing grounded test**

In `tests/adapters/test_openai_adapter.py` add:

```python
from types import SimpleNamespace
from ema_poc.adapters.openai_adapter import OpenAIAdapter


class _FakeResponses:
    def __init__(self, resp):
        self._resp = resp
        self.called_with = None

    def create(self, **kwargs):
        self.called_with = kwargs
        return self._resp


class _FakeOpenAIGrounded:
    def __init__(self, resp):
        self.responses = _FakeResponses(resp)


def _grounded_resp():
    annotation = SimpleNamespace(type="url_citation", url="https://src/a", title="Source A")
    content = SimpleNamespace(type="output_text", text="Grounded answer.", annotations=[annotation])
    message = SimpleNamespace(type="message", content=[content])
    return SimpleNamespace(
        output=[message],
        output_text="Grounded answer.",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def test_openai_grounded_enables_web_search_and_parses_citations():
    fake = _FakeOpenAIGrounded(_grounded_resp())
    adapter = OpenAIAdapter(
        name="GPT-4o-Grounded", model_version="gpt-4o", params={}, client=fake, grounded=True
    )
    out = adapter.query("sys", "question?")
    # web search tool declared
    tools = fake.responses.called_with["tools"]
    assert any(t.get("type", "").startswith("web_search") for t in tools)
    assert out.status == "SUCCESS"
    assert out.text == "Grounded answer."
    assert [(c.title, c.url) for c in out.citations] == [("Source A", "https://src/a")]


def test_openai_ungrounded_path_unchanged_no_responses_call():
    # The existing chat.completions fake from this file should still work and
    # produce zero citations. (Reuse the existing fake client used by other tests.)
    pass  # implement using the existing chat-completions fake in this file
```

If `tests/adapters/test_openai_adapter.py` does not exist, create it and also port the existing ungrounded behavior test using a fake exposing `chat.completions.create`.

- [ ] **Step 2: Run it to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/adapters/test_openai_adapter.py -q -k grounded`
Expected: FAIL (`OpenAIAdapter() got an unexpected keyword argument 'grounded'`)

- [ ] **Step 3: Implement the grounded path**

Replace `ema_poc/adapters/openai_adapter.py` with:

```python
"""OpenAI (GPT-4o) adapter. Ungrounded: Chat Completions (IN-1). Grounded:
Responses API with the web_search tool, returning url_citation annotations."""

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
            raw={"model": self.model_version, "grounded": True},
            citations=citations,
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
```

- [ ] **Step 4: Run the tests**

Run: `source .venv/bin/activate && python -m pytest tests/adapters/test_openai_adapter.py -q`
Expected: PASS (grounded + ungrounded)

- [ ] **Step 5: Commit**

```bash
git add ema_poc/adapters/openai_adapter.py tests/adapters/test_openai_adapter.py
git commit -m "feat: OpenAI grounded adapter (Responses web_search + citations)"
```

---

### Task 4: Gemini grounded adapter (google_search grounding)

**Files:**
- Modify: `ema_poc/adapters/gemini_adapter.py`
- Test: `tests/adapters/test_gemini_adapter.py` (existing — add grounded cases)

**Design:** Add `grounded: bool = False`. When True, pass `tools=[{"google_search": {}}]` to `generate_content` and parse `candidate.grounding_metadata.grounding_chunks[].web.{uri,title}` into citations. Ungrounded path unchanged.

- [ ] **Step 1: Write the failing grounded test**

Add to `tests/adapters/test_gemini_adapter.py`:

```python
from types import SimpleNamespace
from ema_poc.adapters.gemini_adapter import GeminiAdapter


def _grounded_gemini_resp():
    web = SimpleNamespace(uri="https://src/g", title="Gemini Source")
    chunk = SimpleNamespace(web=web)
    gm = SimpleNamespace(grounding_chunks=[chunk])
    cand = SimpleNamespace(finish_reason="STOP", grounding_metadata=gm)
    return SimpleNamespace(
        candidates=[cand],
        text="Grounded gemini answer.",
        prompt_feedback=None,
        usage_metadata=SimpleNamespace(prompt_token_count=8, candidates_token_count=4),
    )


def test_gemini_grounded_passes_search_tool_and_parses_citations():
    captured = {}

    class _Model:
        def generate_content(self, content, **kwargs):
            captured.update(kwargs)
            return _grounded_gemini_resp()

    adapter = GeminiAdapter(
        name="Gemini-2.5-Pro-Grounded", model_version="gemini-2.5-pro",
        params={}, model_factory=lambda sp: _Model(), grounded=True,
    )
    out = adapter.query("sys", "q?")
    assert captured.get("tools") == [{"google_search": {}}]
    assert out.status == "SUCCESS"
    assert [(c.title, c.url) for c in out.citations] == [("Gemini Source", "https://src/g")]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/adapters/test_gemini_adapter.py -q -k grounded`
Expected: FAIL (`unexpected keyword argument 'grounded'`)

- [ ] **Step 3: Implement**

In `ema_poc/adapters/gemini_adapter.py`: add `grounded: bool = False` to `__init__` (store `self.grounded`), import `Citation`, pass tools when grounded, and extract citations. Concretely:

Update the constructor signature and body:

```python
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
```

Update `generate_content` call to pass tools when grounded:

```python
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
```

Before the final `return LLMResponse(...)` (the SUCCESS/TRUNCATED branch), build citations:

```python
        citations = _extract_gemini_citations(candidates[0]) if candidates else []
```

and add `citations=citations` to that final `LLMResponse(...)`. Add the import `from ema_poc.adapters.base import Citation, LLMAdapter, LLMResponse` and the helper:

```python
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
```

(Leave the BLOCKED branch returning `citations=[]` by default — no change needed.)

- [ ] **Step 4: Run the tests**

Run: `source .venv/bin/activate && python -m pytest tests/adapters/test_gemini_adapter.py -q`
Expected: PASS (grounded + existing ungrounded/blocked cases)

- [ ] **Step 5: Commit**

```bash
git add ema_poc/adapters/gemini_adapter.py tests/adapters/test_gemini_adapter.py
git commit -m "feat: Gemini grounded adapter (google_search + citations)"
```

---

### Task 5: Claude grounded adapter (server-side web_search)

**Files:**
- Modify: `ema_poc/adapters/claude_adapter.py`
- Test: `tests/adapters/test_claude_adapter.py` (existing — add grounded cases)

**Design:** Add `grounded: bool = False`. When True, pass `tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]` to `messages.create`. Parse citations from text blocks' `citations` attribute (each citation has `url`, `title`, `cited_text`). Ungrounded path unchanged.

- [ ] **Step 1: Write the failing grounded test**

Add to `tests/adapters/test_claude_adapter.py`:

```python
from types import SimpleNamespace
from ema_poc.adapters.claude_adapter import ClaudeTargetAdapter


def _grounded_claude_resp():
    cite = SimpleNamespace(url="https://src/c", title="Claude Source", cited_text="snippet text")
    text_block = SimpleNamespace(type="text", text="Grounded claude answer.", citations=[cite])
    return SimpleNamespace(
        content=[text_block],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=12, output_tokens=6),
    )


def test_claude_grounded_declares_web_search_tool_and_parses_citations():
    captured = {}

    class _Msgs:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _grounded_claude_resp()

    class _Client:
        messages = _Msgs()

    adapter = ClaudeTargetAdapter(
        name="Claude-Opus-4.8-Grounded", model_version="claude-opus-4-8",
        params={"max_tokens": 4096}, client=_Client(), grounded=True,
    )
    out = adapter.query("sys", "q?")
    tools = captured.get("tools") or []
    assert any(t.get("type", "").startswith("web_search") for t in tools)
    assert out.status == "SUCCESS"
    assert out.text == "Grounded claude answer."
    assert [(c.title, c.url, c.snippet) for c in out.citations] == [
        ("Claude Source", "https://src/c", "snippet text")
    ]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/adapters/test_claude_adapter.py -q -k grounded`
Expected: FAIL (`unexpected keyword argument 'grounded'`)

- [ ] **Step 3: Implement**

In `ema_poc/adapters/claude_adapter.py`: import `Citation`, add `grounded: bool = False` to `__init__` (store it), conditionally add `tools`, and extract citations. Update the `query` method:

```python
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
        )
```

Add `grounded` to `__init__` and the helper:

```python
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
```

Update the import line to `from ema_poc.adapters.base import Citation, LLMAdapter, LLMResponse` and add `self.grounded = grounded` in `__init__`.

- [ ] **Step 4: Run the tests**

Run: `source .venv/bin/activate && python -m pytest tests/adapters/test_claude_adapter.py -q`
Expected: PASS (grounded + existing ungrounded cases)

- [ ] **Step 5: Commit**

```bash
git add ema_poc/adapters/claude_adapter.py tests/adapters/test_claude_adapter.py
git commit -m "feat: Claude grounded adapter (server-side web_search + citations)"
```

---

### Task 6: Registry passes `grounded`; runner persists citations

**Files:**
- Modify: `ema_poc/adapters/registry.py`
- Modify: `ema_poc/agent/runner.py`
- Test: `tests/adapters/test_registry.py` (existing — add a case), `tests/agent/test_runner.py` (existing — add a case)

- [ ] **Step 1: Write the failing registry test**

Add to `tests/adapters/test_registry.py` a case asserting a grounded target produces an adapter with `.grounded is True`. Build an `AppConfig` (or reuse the test's config loader) containing one `openai` target with `grounded: true`, call `build_adapters`, and assert `adapters[0].grounded is True`. Pass fake factories as the existing tests do.

```python
def test_build_adapters_propagates_grounded_flag(monkeypatch):
    from ema_poc.config import AppConfig, Settings, BrandConfig, LLMTargetConfig
    cfg = AppConfig(
        settings=Settings(),
        brands=BrandConfig(),
        targets=[LLMTargetConfig(
            name="GPT-4o-Grounded", adapter="openai", model_version="gpt-4o",
            api_key_env="OPENAI_API_KEY", grounded=True,
            pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
            rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1},
        )],
    )
    adapters = build_adapters(
        cfg, {"OPENAI_API_KEY": "k"},
        openai_client_factory=lambda key: object(),
    )
    assert adapters[0].grounded is True
```

(Add `from ema_poc.adapters.registry import build_adapters` if not present.)

- [ ] **Step 2: Run it to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/adapters/test_registry.py -q -k grounded`
Expected: FAIL (`grounded` not set on the adapter → AttributeError or False)

- [ ] **Step 3: Pass `grounded` in the registry**

In `ema_poc/adapters/registry.py`, add `grounded=target.grounded,` to each adapter constructor call (`OpenAIAdapter`, `GeminiAdapter`, `ClaudeTargetAdapter`).

- [ ] **Step 4: Run it to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/adapters/test_registry.py -q -k grounded`
Expected: PASS

- [ ] **Step 5: Write the failing runner-citations test**

First read `ema_poc/agent/runner.py` to find where a response is saved (the `save_response` call). Add a test to `tests/agent/test_runner.py` that uses a fake adapter returning an `LLMResponse` with `citations=[Citation(...)]`, runs a one-question run, and asserts `list_citations(conn, <response_id>)` returns that citation. Use the existing runner-test fixtures/fakes as a template (look at how the file builds a runner with fake adapters, ids, and a question). The assertion:

```python
from ema_poc.repositories.citations import list_citations
# ... after run completes and one SUCCESS response was saved with response_id rid:
cites = list_citations(conn, rid)
assert [c.url for c in cites] == ["https://src/x"]
```

(Construct the fake adapter's returned `LLMResponse` with `citations=[Citation(title="X", url="https://src/x")]`.)

- [ ] **Step 6: Run it to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/agent/test_runner.py -q -k citation`
Expected: FAIL (no citations persisted)

- [ ] **Step 7: Persist citations in the runner**

In `ema_poc/agent/runner.py`, immediately after the `save_response(conn, response)` call (only for non-failed saves where citations may exist), call:

```python
from ema_poc.repositories.citations import save_citations
# ... after save_response(conn, response):
if llm_response.citations:
    save_citations(
        conn,
        response_id=response.response_id,
        citations=llm_response.citations,
        now=now,
        id_factory=id_factory,
    )
```

Use the runner's existing `now` value and `id_factory` (the same ones used to build the response). If the runner's id factory yields response ids, ensure citation ids don't collide — if the runner uses a single shared `id_factory`, that is fine (unique hex). Match the variable names already in `runner.py` (read the file; the normalized response object may be named `response` and the adapter result `llm_response` or similar — adapt accordingly).

- [ ] **Step 8: Run it to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/agent/test_runner.py -q`
Expected: PASS (all runner tests, including the new citations case)

- [ ] **Step 9: Commit**

```bash
git add ema_poc/adapters/registry.py ema_poc/agent/runner.py tests/adapters/test_registry.py tests/agent/test_runner.py
git commit -m "feat: registry propagates grounded flag; runner persists citations"
```

---

### Task 7: Add grounded targets to config + full-suite verification

**Files:**
- Modify: `config/llm_targets.yaml`
- Test: full suite

- [ ] **Step 1: Add three grounded targets**

Append to `config/llm_targets.yaml` under `targets:`:

```yaml
  - name: GPT-4o-Grounded
    adapter: openai
    model_version: gpt-4o-2024-11-20
    api_key_env: OPENAI_API_KEY
    grounded: true
    params: {temperature: 0.3, max_tokens: 4096}
    pricing: {input_per_1k: 0.0025, output_per_1k: 0.01}   # NOTE: web_search billed separately
    rate_limit: {requests_per_minute: 60, tokens_per_minute: 90000}

  - name: Gemini-2.5-Pro-Grounded
    adapter: gemini
    model_version: gemini-2.5-pro
    api_key_env: GOOGLE_API_KEY
    grounded: true
    params: {temperature: 0.3, max_output_tokens: 4096}
    pricing: {input_per_1k: 0.00125, output_per_1k: 0.01}  # NOTE: grounding billed separately
    rate_limit: {requests_per_minute: 60, tokens_per_minute: 90000}

  - name: Claude-Opus-4.8-Grounded
    adapter: claude
    model_version: claude-opus-4-8
    api_key_env: ANTHROPIC_API_KEY
    grounded: true
    params: {max_tokens: 4096}
    pricing: {input_per_1k: 0.005, output_per_1k: 0.025}   # NOTE: web_search billed separately
    rate_limit: {requests_per_minute: 50, tokens_per_minute: 80000}
```

- [ ] **Step 2: Verify config loads with 6 targets**

Run:
```bash
source .venv/bin/activate && python -c "from ema_poc.config import load_config; c=load_config('config'); print([(t.name,t.grounded) for t in c.targets])"
```
Expected: prints 6 targets, the three `-Grounded` ones with `True`.

- [ ] **Step 3: Run the full suite + coverage**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: all tests pass (the pre-existing ~149 plus the new grounded/citation tests).

- [ ] **Step 4: Commit**

```bash
git add config/llm_targets.yaml
git commit -m "feat: add three web-grounded targets to the daily run"
```

---

## Self-Review Notes (author)

- **Spec coverage:** Citation type (Task 1), grounded flag + 3 adapters (1,3,4,5), append-only citation storage (Task 2,6), config targets in daily run + dashboard-by-name (Task 7), tests with fakes/no network (every task). ✅
- **Type consistency:** `Citation(title, url, snippet=None)` used identically across base, citations repo, and all three adapters. `grounded` kwarg added to all three adapter constructors and propagated by the registry. `save_citations(conn, *, response_id, citations, now, id_factory, commit)` / `list_citations(conn, response_id)` signatures stable.
- **Provider API confirmation:** OpenAI `web_search_preview` tool + `url_citation` annotations, Gemini `google_search` tool + `grounding_chunks[].web`, Claude `web_search_20250305` tool + text-block `citations`. Tests pin these via fakes; the implementer confirms live shapes against installed SDKs during Task 3–5 and adjusts the parser only (tests stay valid).
