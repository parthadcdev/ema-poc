# Real-Time Playground Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web app where a user types an arbitrary question and watches each model's answer stream in — with citations (grounded targets) and a live sentiment/competitive score — stored in an isolated sandbox separate from the approval-gated monitoring data.

**Architecture:** A small FastAPI app serves a self-contained HTML page and a Server-Sent-Events endpoint. The core fan-out logic lives in a framework-agnostic `playground` service (testable without FastAPI): it runs the selected adapters concurrently via the existing executor, scores each answer with the existing Claude scorer, persists results to new `sandbox_*` tables, and yields events (`answer`, `score`, `done`) in completion order. The FastAPI layer wraps that generator as SSE.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, stdlib `sqlite3`, existing adapters/scorer/executor. Vendor SDKs stay lazy. Tests use FastAPI `TestClient` + injected fake adapters/scorer — no network.

**Branch:** Build on `feature/grounded-targets` **after Plan 1 is merged to `develop`**, on a new branch `feature/playground-ui` off `develop`. (Plan 2 depends on `Citation`, the grounded adapters, and `LLMResponse.citations` from Plan 1.)

**Prerequisite:** Plan 1 (`2026-06-13-grounded-targets-and-citations.md`) is merged.

**Conventions to follow:**
- Vendor SDKs imported lazily only; the playground service receives already-built adapters + a scoring client (injected), exactly like the existing CLI `Deps` pattern.
- All DB writes in the main thread. Adapter calls run in worker threads (the existing `ThreadPoolExecutor`); results are marshaled back before writing.
- Frontend is one self-contained file (inline CSS/JS), consistent with the dashboard.
- Run tests: `source .venv/bin/activate && python -m pytest -q`

---

### Task 1: Sandbox schema + repository

**Files:**
- Modify: `ema_poc/db.py` (add three tables to `SCHEMA`)
- Create: `ema_poc/repositories/sandbox.py`
- Test: `tests/repositories/test_sandbox.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/repositories/test_sandbox.py`:

```python
import sqlite3
import pytest

from ema_poc.db import connect, init_schema
from ema_poc.adapters.base import Citation
from ema_poc.repositories import sandbox as S


def _conn(tmp_path):
    conn = connect(str(tmp_path / "s.sqlite"))
    init_schema(conn)
    return conn


def test_create_query_and_save_response_with_citations(tmp_path):
    conn = _conn(tmp_path)
    qid = S.create_query(
        conn, question_text="What treats psoriasis?", persona="Provider",
        brand_focus="Skyrizi", now="2026-01-01T00:00:00+00:00",
        id_factory=lambda: "q1",
    )
    assert qid == "q1"
    rid = S.save_response(
        conn, query_id=qid, llm_name="GPT-4o", llm_model_version="gpt-4o",
        grounded=False, answer_text="Biologics.", response_tokens=12,
        finish_reason="stop", status="SUCCESS", now="2026-01-01T00:00:00+00:00",
        id_factory=lambda: "sr1",
    )
    S.save_response_citations(
        conn, sandbox_response_id=rid,
        citations=[Citation(title="A", url="https://a", snippet="x")],
        now="2026-01-01T00:00:00+00:00", id_factory=iter(["sc1"]).__next__,
    )
    S.set_response_score(
        conn, sandbox_response_id=rid, sentiment_score=0.4,
        competitive_position="AMONG_OPTIONS", scoring_rationale="ok",
    )

    rows = S.list_query_responses(conn, qid)
    assert len(rows) == 1
    r = rows[0]
    assert r.llm_name == "GPT-4o"
    assert r.sentiment_score == 0.4
    assert r.competitive_position == "AMONG_OPTIONS"
    assert [(c.title, c.url, c.snippet) for c in r.citations] == [("A", "https://a", "x")]


def test_list_recent_queries_newest_first(tmp_path):
    conn = _conn(tmp_path)
    S.create_query(conn, question_text="q1", persona=None, brand_focus=None,
                   now="2026-01-01T00:00:00+00:00", id_factory=lambda: "a")
    S.create_query(conn, question_text="q2", persona=None, brand_focus=None,
                   now="2026-01-02T00:00:00+00:00", id_factory=lambda: "b")
    recent = S.list_recent_queries(conn, limit=10)
    assert [q.question_text for q in recent] == ["q2", "q1"]


def test_response_fk_requires_existing_query(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        S.save_response(
            conn, query_id="missing", llm_name="L", llm_model_version="m",
            grounded=False, answer_text="x", response_tokens=None,
            finish_reason="stop", status="SUCCESS",
            now="2026-01-01T00:00:00+00:00", id_factory=lambda: "sr1",
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/repositories/test_sandbox.py -q`
Expected: FAIL (`No module named 'ema_poc.repositories.sandbox'`)

- [ ] **Step 3: Add the sandbox tables to the schema**

In `ema_poc/db.py`, append to the `SCHEMA` string (after `audit_log`):

```sql
CREATE TABLE IF NOT EXISTS sandbox_queries (
    query_id      TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    question_text TEXT NOT NULL,
    persona       TEXT,
    brand_focus   TEXT
);

CREATE TABLE IF NOT EXISTS sandbox_responses (
    sandbox_response_id  TEXT PRIMARY KEY,
    query_id             TEXT NOT NULL,
    llm_name             TEXT NOT NULL,
    llm_model_version    TEXT NOT NULL,
    grounded             INTEGER NOT NULL DEFAULT 0,
    answer_text          TEXT,
    response_tokens      INTEGER,
    finish_reason        TEXT,
    status               TEXT NOT NULL,
    sentiment_score      REAL,
    competitive_position TEXT,
    scoring_rationale    TEXT,
    created_at           TEXT NOT NULL,
    FOREIGN KEY (query_id) REFERENCES sandbox_queries(query_id)
);
CREATE INDEX IF NOT EXISTS idx_sandbox_resp_query ON sandbox_responses(query_id);

CREATE TABLE IF NOT EXISTS sandbox_citations (
    citation_id          TEXT PRIMARY KEY,
    sandbox_response_id  TEXT NOT NULL,
    title                TEXT NOT NULL,
    url                  TEXT NOT NULL,
    snippet              TEXT,
    created_at           TEXT NOT NULL,
    FOREIGN KEY (sandbox_response_id) REFERENCES sandbox_responses(sandbox_response_id)
);
CREATE INDEX IF NOT EXISTS idx_sandbox_cit_resp ON sandbox_citations(sandbox_response_id);
```

- [ ] **Step 4: Implement the repository**

Create `ema_poc/repositories/sandbox.py`:

```python
"""Sandbox storage for the real-time playground. Fully isolated from the
approval-gated monitoring tables (no SE-002 gate); insert-only writes plus a
single score-update per sandbox response."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from uuid import uuid4

from ema_poc.adapters.base import Citation


@dataclass
class SandboxQuery:
    query_id: str
    timestamp_utc: str
    question_text: str
    persona: str | None
    brand_focus: str | None


@dataclass
class SandboxResponse:
    sandbox_response_id: str
    query_id: str
    llm_name: str
    llm_model_version: str
    grounded: bool
    answer_text: str | None
    response_tokens: int | None
    finish_reason: str | None
    status: str
    sentiment_score: float | None
    competitive_position: str | None
    scoring_rationale: str | None
    created_at: str
    citations: list[Citation] = field(default_factory=list)


def create_query(
    conn, *, question_text, persona, brand_focus, now, id_factory=lambda: uuid4().hex,
    commit: bool = True,
) -> str:
    query_id = id_factory()
    conn.execute(
        """INSERT INTO sandbox_queries (query_id, timestamp_utc, question_text, persona, brand_focus)
           VALUES (?, ?, ?, ?, ?)""",
        (query_id, now, question_text, persona, brand_focus),
    )
    if commit:
        conn.commit()
    return query_id


def save_response(
    conn, *, query_id, llm_name, llm_model_version, grounded, answer_text,
    response_tokens, finish_reason, status, now, id_factory=lambda: uuid4().hex,
    commit: bool = True,
) -> str:
    rid = id_factory()
    conn.execute(
        """INSERT INTO sandbox_responses
           (sandbox_response_id, query_id, llm_name, llm_model_version, grounded,
            answer_text, response_tokens, finish_reason, status,
            sentiment_score, competitive_position, scoring_rationale, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)""",
        (rid, query_id, llm_name, llm_model_version, int(grounded),
         answer_text, response_tokens, finish_reason, status, now),
    )
    if commit:
        conn.commit()
    return rid


def save_response_citations(
    conn, *, sandbox_response_id, citations, now, id_factory=lambda: uuid4().hex,
    commit: bool = True,
) -> None:
    for c in citations:
        conn.execute(
            """INSERT INTO sandbox_citations
               (citation_id, sandbox_response_id, title, url, snippet, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (id_factory(), sandbox_response_id, c.title, c.url, c.snippet, now),
        )
    if commit:
        conn.commit()


def set_response_score(
    conn, *, sandbox_response_id, sentiment_score, competitive_position,
    scoring_rationale, commit: bool = True,
) -> None:
    conn.execute(
        """UPDATE sandbox_responses
           SET sentiment_score = ?, competitive_position = ?, scoring_rationale = ?
           WHERE sandbox_response_id = ?""",
        (sentiment_score, competitive_position, scoring_rationale, sandbox_response_id),
    )
    if commit:
        conn.commit()


def _citations_for(conn, sandbox_response_id) -> list[Citation]:
    rows = conn.execute(
        """SELECT title, url, snippet FROM sandbox_citations
           WHERE sandbox_response_id = ? ORDER BY created_at, citation_id""",
        (sandbox_response_id,),
    ).fetchall()
    return [Citation(title=r["title"], url=r["url"], snippet=r["snippet"]) for r in rows]


def list_query_responses(conn, query_id) -> list[SandboxResponse]:
    rows = conn.execute(
        """SELECT * FROM sandbox_responses WHERE query_id = ? ORDER BY created_at, sandbox_response_id""",
        (query_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        out.append(SandboxResponse(
            sandbox_response_id=d["sandbox_response_id"], query_id=d["query_id"],
            llm_name=d["llm_name"], llm_model_version=d["llm_model_version"],
            grounded=bool(d["grounded"]), answer_text=d["answer_text"],
            response_tokens=d["response_tokens"], finish_reason=d["finish_reason"],
            status=d["status"], sentiment_score=d["sentiment_score"],
            competitive_position=d["competitive_position"],
            scoring_rationale=d["scoring_rationale"], created_at=d["created_at"],
            citations=_citations_for(conn, d["sandbox_response_id"]),
        ))
    return out


def list_recent_queries(conn, limit: int = 25) -> list[SandboxQuery]:
    rows = conn.execute(
        """SELECT query_id, timestamp_utc, question_text, persona, brand_focus
           FROM sandbox_queries ORDER BY timestamp_utc DESC, query_id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [SandboxQuery(**dict(r)) for r in rows]
```

- [ ] **Step 5: Run it to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/repositories/test_sandbox.py -q`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add ema_poc/db.py ema_poc/repositories/sandbox.py tests/repositories/test_sandbox.py
git commit -m "feat: isolated sandbox tables + repository for the playground"
```

---

### Task 2: Playground service (framework-agnostic event generator)

**Files:**
- Create: `ema_poc/playground/__init__.py` (empty)
- Create: `ema_poc/playground/service.py`
- Test: `tests/playground/test_service.py` (create), plus `tests/playground/__init__.py` if the suite needs package dirs

**Design:** `run_playground(...)` is a **generator** yielding plain dict events. It takes already-built adapters, a scoring client, brand lists, a DB connection, and the question/persona/brand_focus. It fans out across adapters concurrently using the existing executor, and as each finishes it yields an `answer` event, scores the answer, yields a `score` event, and persists to the sandbox. The persona maps to a system prompt via the config's `system_prompts`. Because everything is injected, the test uses fake adapters + a fake scorer — no FastAPI, no network.

Event shapes (all JSON-serializable dicts):
- `{"event": "query", "query_id": "..."}`
- `{"event": "answer", "llm_name": "...", "grounded": bool, "status": "...", "finish_reason": "...", "answer_text": "...", "tokens": int|None, "citations": [{"title","url","snippet"}]}`
- `{"event": "score", "llm_name": "...", "sentiment_score": float, "competitive_position": "...", "scoring_rationale": "..."}`
- `{"event": "done"}`
- `{"event": "error", "message": "..."}`

- [ ] **Step 1: Write the failing test**

Create `tests/playground/__init__.py` (empty) and `tests/playground/test_service.py`:

```python
from ema_poc.db import connect, init_schema
from ema_poc.adapters.base import Citation, LLMResponse
from ema_poc.playground.service import run_playground
from ema_poc.repositories import sandbox as S


class FakeAdapter:
    def __init__(self, name, grounded=False, citations=None):
        self.name = name
        self.model_version = name + "-v"
        self.grounded = grounded
        self._citations = citations or []

    def query(self, system_prompt, question_text):
        return LLMResponse(
            text=f"{self.name} answer", finish_reason="stop", status="SUCCESS",
            completion_tokens=7, citations=self._citations,
        )


class FakeScoreResult:
    def __init__(self):
        self.sentiment_score = 0.5
        self.competitive_position = "AMONG_OPTIONS"
        self.brand_mentions = ["Skyrizi"]
        self.key_claims = []
        self.scoring_rationale = "because"


def fake_scorer(client, *, response_text, brand_focus, abbvie_brands,
                competitor_brands, model):
    return FakeScoreResult()


def test_run_playground_emits_answer_then_score_per_target_and_persists(tmp_path):
    conn = connect(str(tmp_path / "p.sqlite"))
    init_schema(conn)
    adapters = [
        FakeAdapter("GPT-4o"),
        FakeAdapter("Claude-Grounded", grounded=True,
                    citations=[Citation(title="Src", url="https://s")]),
    ]
    events = list(run_playground(
        conn, adapters=adapters, scoring_client=object(), scorer=fake_scorer,
        abbvie_brands=["Skyrizi"], competitor_brands=["Stelara"],
        system_prompts={"default": "You are helpful."},
        question_text="What treats psoriasis?", persona="Provider",
        brand_focus="Skyrizi", model="claude-opus-4-8",
        id_factory=iter([f"id{i}" for i in range(50)]).__next__,
        now="2026-01-01T00:00:00+00:00",
        max_retries=0, backoff=[1],
    ))
    kinds = [e["event"] for e in events]
    assert kinds[0] == "query"
    assert kinds.count("answer") == 2
    assert kinds.count("score") == 2
    assert kinds[-1] == "done"

    # grounded target's answer event carries citations
    grounded_answer = next(e for e in events if e["event"] == "answer" and e["grounded"])
    assert grounded_answer["citations"] == [{"title": "Src", "url": "https://s", "snippet": None}]

    # persisted to sandbox
    query_id = events[0]["query_id"]
    rows = S.list_query_responses(conn, query_id)
    assert {r.llm_name for r in rows} == {"GPT-4o", "Claude-Grounded"}
    assert all(r.sentiment_score == 0.5 for r in rows)
    grounded_row = next(r for r in rows if r.grounded)
    assert [c.url for c in grounded_row.citations] == ["https://s"]


def test_run_playground_emits_error_on_no_adapters(tmp_path):
    conn = connect(str(tmp_path / "p.sqlite"))
    init_schema(conn)
    events = list(run_playground(
        conn, adapters=[], scoring_client=object(), scorer=fake_scorer,
        abbvie_brands=[], competitor_brands=[], system_prompts={"default": "x"},
        question_text="q", persona=None, brand_focus=None, model="m",
        id_factory=iter(["id0"]).__next__, now="2026-01-01T00:00:00+00:00",
        max_retries=0, backoff=[1],
    ))
    assert events[-1]["event"] == "error"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/playground/test_service.py -q`
Expected: FAIL (`No module named 'ema_poc.playground'`)

- [ ] **Step 3: Implement the service**

Create `ema_poc/playground/__init__.py` (empty file) and `ema_poc/playground/service.py`:

```python
"""Framework-agnostic playground fan-out. Yields JSON-serializable events as
each target completes; persists to the sandbox. Injected adapters + scorer keep
it testable with no network."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict

from ema_poc.agent.executor import execute
from ema_poc.repositories import sandbox as S


def _system_prompt_for(system_prompts, persona) -> str:
    if persona and persona in system_prompts:
        return system_prompts[persona]
    return system_prompts.get("default", "You are a helpful assistant.")


def run_playground(
    conn, *, adapters, scoring_client, scorer, abbvie_brands, competitor_brands,
    system_prompts, question_text, persona, brand_focus, model,
    id_factory, now, max_retries, backoff,
):
    if not adapters:
        yield {"event": "error", "message": "No targets selected."}
        return

    query_id = S.create_query(
        conn, question_text=question_text, persona=persona, brand_focus=brand_focus,
        now=now, id_factory=id_factory,
    )
    yield {"event": "query", "query_id": query_id}

    system_prompt = _system_prompt_for(system_prompts, persona)

    # Fan out adapter.query calls across threads (no DB access inside threads).
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, len(adapters))) as pool:
        futures = {
            pool.submit(
                execute, a, system_prompt, question_text,
                max_retries=max_retries, backoff=backoff,
            ): a
            for a in adapters
        }
        for fut in as_completed(futures):
            adapter = futures[fut]
            llm_response = fut.result()
            results[adapter.name] = (adapter, llm_response)

            # Persist the response row (main thread).
            rid = S.save_response(
                conn, query_id=query_id, llm_name=adapter.name,
                llm_model_version=adapter.model_version,
                grounded=getattr(adapter, "grounded", False),
                answer_text=llm_response.text, response_tokens=llm_response.completion_tokens,
                finish_reason=llm_response.finish_reason, status=llm_response.status,
                now=now, id_factory=id_factory,
            )
            citations = list(llm_response.citations)
            if citations:
                S.save_response_citations(
                    conn, sandbox_response_id=rid, citations=citations,
                    now=now, id_factory=id_factory,
                )

            yield {
                "event": "answer",
                "llm_name": adapter.name,
                "grounded": getattr(adapter, "grounded", False),
                "status": llm_response.status,
                "finish_reason": llm_response.finish_reason,
                "answer_text": llm_response.text,
                "tokens": llm_response.completion_tokens,
                "citations": [asdict(c) for c in citations],
            }

            # Score successful answers; skip empty/failed.
            if llm_response.status == "SUCCESS" and llm_response.text.strip():
                try:
                    result = scorer(
                        scoring_client, response_text=llm_response.text,
                        brand_focus=brand_focus, abbvie_brands=abbvie_brands,
                        competitor_brands=competitor_brands, model=model,
                    )
                    S.set_response_score(
                        conn, sandbox_response_id=rid,
                        sentiment_score=result.sentiment_score,
                        competitive_position=result.competitive_position,
                        scoring_rationale=result.scoring_rationale,
                    )
                    yield {
                        "event": "score",
                        "llm_name": adapter.name,
                        "sentiment_score": result.sentiment_score,
                        "competitive_position": result.competitive_position,
                        "scoring_rationale": result.scoring_rationale,
                    }
                except Exception as exc:  # scoring failure shouldn't kill the stream
                    yield {"event": "score_error", "llm_name": adapter.name, "message": str(exc)}

    yield {"event": "done"}
```

Note on ids: a single `id_factory` is shared across query, responses, and citations. With the default `uuid4().hex` factory each id is unique; tests pass an iterator yielding distinct ids. `competitive_position` from the scorer is an enum value or string — `set_response_score` stores it as-is (the fake returns a plain string; the real `ScoreResult.competitive_position` is a `Literal[str]`, also a plain string).

- [ ] **Step 4: Run it to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/playground/test_service.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add ema_poc/playground/ tests/playground/
git commit -m "feat: playground fan-out service (answer/score events + sandbox persistence)"
```

---

### Task 3: FastAPI app — `/` page, `/api/targets`, and dependency wiring

**Files:**
- Create: `ema_poc/web/__init__.py` (empty)
- Create: `ema_poc/web/app.py`
- Create: `ema_poc/web/static/index.html` (minimal placeholder now; full UI in Task 5)
- Modify: `pyproject.toml` (add deps)
- Test: `tests/web/test_app.py` (create), `tests/web/__init__.py` (empty)

**Design:** `create_app(deps)` builds a FastAPI app from an injectable `WebDeps` bundle (mirroring CLI `Deps`): a `config`, a function to open a DB connection, a function to build adapters from selected target names, a scoring client factory, and the scorer. Tests construct a `WebDeps` with fakes and use `TestClient`.

- [ ] **Step 1: Add dependencies to pyproject.toml**

In `pyproject.toml`, add to the dependencies list: `"fastapi>=0.110"`, `"uvicorn>=0.29"`. Add `"httpx>=0.27"` to dev/test dependencies (FastAPI `TestClient` needs it). Then:

```bash
source .venv/bin/activate && pip install -e . && pip install fastapi uvicorn httpx
```

Expected: installs cleanly.

- [ ] **Step 2: Write the failing test**

Create `tests/web/__init__.py` (empty) and `tests/web/test_app.py`:

```python
from fastapi.testclient import TestClient

from ema_poc.web.app import create_app, WebDeps
from ema_poc.config import AppConfig, Settings, BrandConfig, LLMTargetConfig


def _config():
    targets = [
        LLMTargetConfig(name="GPT-4o", adapter="openai", model_version="gpt-4o",
                        api_key_env="OPENAI_API_KEY",
                        pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
                        rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1}),
        LLMTargetConfig(name="Claude-Grounded", adapter="claude", model_version="claude-opus-4-8",
                        api_key_env="ANTHROPIC_API_KEY", grounded=True,
                        pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
                        rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1}),
    ]
    return AppConfig(settings=Settings(), brands=BrandConfig(), targets=targets)


def _deps(tmp_path):
    return WebDeps(
        config=_config(),
        build_adapters_for=lambda names: [],
        scoring_client=object(),
        scorer=lambda *a, **k: None,
        db_path=str(tmp_path / "w.sqlite"),
    )


def test_index_served(tmp_path):
    app = create_app(_deps(tmp_path))
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_targets_endpoint_lists_all_targets(tmp_path):
    app = create_app(_deps(tmp_path))
    client = TestClient(app)
    r = client.get("/api/targets")
    assert r.status_code == 200
    data = r.json()
    names = {t["name"]: t for t in data["targets"]}
    assert names["GPT-4o"]["grounded"] is False
    assert names["Claude-Grounded"]["grounded"] is True
```

- [ ] **Step 3: Implement the app skeleton**

Create `ema_poc/web/__init__.py` (empty). Create `ema_poc/web/static/index.html` with a minimal valid page (replaced in Task 5):

```html
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>EMA Playground</title></head>
<body><h1>EMA Playground</h1><p id="placeholder">UI loads here.</p></body></html>
```

Create `ema_poc/web/app.py`:

```python
"""FastAPI playground app. All collaborators are injected via WebDeps so the
app is testable with fakes and no network."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

_STATIC = Path(__file__).parent / "static"


@dataclass
class WebDeps:
    config: object                 # AppConfig
    build_adapters_for: Callable   # (selected_names: list[str]|None) -> list[adapter]
    scoring_client: object         # Anthropic client (or fake)
    scorer: Callable               # score_response-compatible callable
    db_path: str


def create_app(deps: WebDeps) -> FastAPI:
    app = FastAPI(title="EMA Playground")

    @app.get("/")
    def index():
        return FileResponse(str(_STATIC / "index.html"))

    @app.get("/api/targets")
    def targets():
        return JSONResponse({
            "targets": [
                {"name": t.name, "adapter": t.adapter, "grounded": t.grounded}
                for t in deps.config.targets if t.enabled
            ]
        })

    app.state.deps = deps
    return app
```

(The SSE endpoint is added in Task 4; `open_conn` will be replaced by a concrete `connect`/`init_schema` opener there — for now the targets/index tests don't touch the DB.)

- [ ] **Step 4: Run it to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/web/test_app.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml ema_poc/web/ tests/web/
git commit -m "feat: FastAPI playground app skeleton (index + /api/targets)"
```

---

### Task 4: SSE endpoint `/api/ask/stream`

**Files:**
- Modify: `ema_poc/web/app.py`
- Test: `tests/web/test_stream.py` (create)

**Design:** A `GET /api/ask/stream` endpoint that opens a DB connection, validates credentials are present for the selected targets (emit `error` event if not), builds the adapters via `deps.build_adapters_for`, and streams `run_playground(...)` events as SSE (`data: <json>\n\n` per event). Uses `StreamingResponse` with `media_type="text/event-stream"`. Each SSE line is `data: {json}\n\n`.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_stream.py`:

```python
import json
from fastapi.testclient import TestClient

from ema_poc.web.app import create_app, WebDeps
from ema_poc.config import AppConfig, Settings, BrandConfig, LLMTargetConfig
from ema_poc.adapters.base import LLMResponse


class FakeAdapter:
    def __init__(self, name, grounded=False):
        self.name = name
        self.model_version = name + "-v"
        self.grounded = grounded

    def query(self, system_prompt, question_text):
        return LLMResponse(text=f"{self.name} ans", finish_reason="stop",
                           status="SUCCESS", completion_tokens=5)


class FakeScore:
    sentiment_score = 0.5
    competitive_position = "AMONG_OPTIONS"
    brand_mentions: list = []
    key_claims: list = []
    scoring_rationale = "r"


def _deps(tmp_path):
    cfg = AppConfig(
        settings=Settings(system_prompts={"default": "x"}),
        brands=BrandConfig(),
        targets=[LLMTargetConfig(
            name="GPT-4o", adapter="openai", model_version="gpt-4o",
            api_key_env="OPENAI_API_KEY",
            pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
            rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1})],
    )
    return WebDeps(
        config=cfg,
        build_adapters_for=lambda names: [FakeAdapter("GPT-4o")],
        scoring_client=object(),
        scorer=lambda *a, **k: FakeScore(),
        db_path=str(tmp_path / "w.sqlite"),
    )


def _parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        line = block.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:"):].strip()))
    return events


def test_ask_stream_emits_answer_score_done(tmp_path):
    app = create_app(_deps(tmp_path))
    client = TestClient(app)
    with client.stream("GET", "/api/ask/stream",
                       params={"question": "What treats psoriasis?",
                               "persona": "Provider", "brand_focus": "Skyrizi"}) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        body = "".join(chunk for chunk in r.iter_text())
    events = _parse_sse(body)
    kinds = [e["event"] for e in events]
    assert kinds[0] == "query"
    assert "answer" in kinds and "score" in kinds
    assert kinds[-1] == "done"


def test_ask_stream_requires_question(tmp_path):
    app = create_app(_deps(tmp_path))
    client = TestClient(app)
    r = client.get("/api/ask/stream", params={"question": "  "})
    # empty question -> 400
    assert r.status_code == 400
```

- [ ] **Step 2: Run it to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/web/test_stream.py -q`
Expected: FAIL (404 — endpoint missing)

- [ ] **Step 3: Implement the SSE endpoint**

In `ema_poc/web/app.py`, add imports and the endpoint. Add at top:

```python
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Query, HTTPException
from fastapi.responses import StreamingResponse

from ema_poc.db import connect, init_schema
from ema_poc.playground.service import run_playground
```

Then inside `create_app`, add:

```python
    @app.get("/api/ask/stream")
    def ask_stream(
        question: str = Query(...),
        persona: str | None = Query(None),
        brand_focus: str | None = Query(None),
        targets: str | None = Query(None),
    ):
        if not question or not question.strip():
            raise HTTPException(status_code=400, detail="question is required")

        selected = [t.strip() for t in targets.split(",")] if targets else None
        cfg = deps.config

        def event_stream():
            conn = connect(deps.db_path)
            init_schema(conn)
            try:
                adapters = deps.build_adapters_for(selected)
                gen = run_playground(
                    conn, adapters=adapters, scoring_client=deps.scoring_client,
                    scorer=deps.scorer,
                    abbvie_brands=cfg.brands.abbvie_brands,
                    competitor_brands=cfg.brands.competitor_brands,
                    system_prompts=cfg.settings.system_prompts,
                    question_text=question.strip(), persona=persona, brand_focus=brand_focus,
                    model=cfg.settings.scoring_model,
                    id_factory=lambda: uuid4().hex,
                    now=datetime.now(timezone.utc).isoformat(),
                    max_retries=cfg.settings.max_retries,
                    backoff=cfg.settings.backoff_seconds,
                )
                for event in gen:
                    yield "data: " + json.dumps(event) + "\n\n"
            finally:
                conn.close()

        return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 4: Run it to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/web/test_stream.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add ema_poc/web/app.py tests/web/test_stream.py
git commit -m "feat: SSE /api/ask/stream endpoint streaming playground events"
```

---

### Task 5: Self-contained frontend (`index.html`)

**Files:**
- Modify: `ema_poc/web/static/index.html` (full UI)
- Test: `tests/web/test_app.py` (add an assertion that key UI markers are served)

**Design:** A single self-contained page (inline CSS + vanilla JS). It loads `/api/targets` to render target checkboxes (grounded badged 🌐), has a question textarea + persona `<select>` + brand_focus `<input>`, a Run button, and a results grid. On Run it opens an `EventSource("/api/ask/stream?...")` and renders cards: an `answer` event creates/fills a card (answer text + citations list); a `score` event adds a sentiment/position chip to that card; `done` closes the stream; `error` shows a banner. A "Recent queries" link is out of scope for the MVP unless trivial.

- [ ] **Step 1: Write the failing assertion**

Add to `tests/web/test_app.py`:

```python
def test_index_contains_playground_markers(tmp_path):
    from fastapi.testclient import TestClient
    app = create_app(_deps(tmp_path))
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="question"' in html
    assert "EventSource" in html
    assert "/api/ask/stream" in html
    assert "/api/targets" in html
```

- [ ] **Step 2: Run it to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/web/test_app.py -q -k markers`
Expected: FAIL (placeholder html lacks these markers)

- [ ] **Step 3: Write the full self-contained page**

Replace `ema_poc/web/static/index.html` with:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EMA Playground</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; background: #f6f7f9; color: #1a1a1a; }
  header { background: #1f2a44; color: #fff; padding: 1rem 1.5rem; }
  header h1 { margin: 0; font-size: 1.15rem; }
  main { max-width: 1100px; margin: 1.5rem auto; padding: 0 1rem; }
  .panel { background: #fff; border: 1px solid #e3e6eb; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1.25rem; }
  textarea { width: 100%; box-sizing: border-box; min-height: 64px; font: inherit; padding: .5rem; }
  .row { display: flex; gap: 1rem; flex-wrap: wrap; align-items: center; margin-top: .75rem; }
  label { font-size: .85rem; }
  .targets label { margin-right: 1rem; white-space: nowrap; }
  button { background: #2d6cdf; color: #fff; border: 0; border-radius: 6px; padding: .55rem 1.1rem; font: inherit; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  .note { font-size: .78rem; color: #6b7280; margin-top: .5rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1rem; }
  .card { background: #fff; border: 1px solid #e3e6eb; border-radius: 8px; padding: 1rem; }
  .card h3 { margin: 0 0 .25rem; font-size: 1rem; }
  .badge { font-size: .7rem; background: #eef2ff; color: #3949ab; border-radius: 10px; padding: .1rem .5rem; margin-left: .4rem; }
  .chip { display: inline-block; font-size: .78rem; border-radius: 12px; padding: .15rem .6rem; margin-right: .4rem; }
  .answer { white-space: pre-wrap; font-size: .9rem; margin: .5rem 0; }
  .citations { font-size: .8rem; border-top: 1px solid #eee; padding-top: .5rem; }
  .citations a { color: #2d6cdf; }
  .err { background: #fdecea; color: #8a1c1c; padding: .6rem .9rem; border-radius: 6px; }
  .spinner { font-size: .8rem; color: #6b7280; }
</style>
</head>
<body>
<header><h1>Evidence Monitoring — Real-Time Playground</h1></header>
<main>
  <div class="panel">
    <textarea id="question" placeholder="Ask any question (do NOT enter PII/PHI)…"></textarea>
    <div class="row">
      <label>Persona:
        <select id="persona">
          <option value="">(default)</option>
          <option>Prospect</option><option>Provider</option><option>Patient</option>
        </select>
      </label>
      <label>Brand focus: <input id="brand" type="text" placeholder="e.g. Skyrizi" size="14"></label>
    </div>
    <div class="row targets" id="targets"></div>
    <div class="row">
      <button id="run">Run</button>
      <span id="status" class="spinner"></span>
    </div>
    <div class="note">Sandbox mode — results are stored separately from the approval-gated monitoring data and never feed the official dashboard. Do not enter PII/PHI (SE-001).</div>
  </div>
  <div id="banner"></div>
  <div class="grid" id="results"></div>
</main>
<script>
const POSCOLOR = {
  FIRST_LINE_RECOMMENDED: "#d6f5d6", AMONG_OPTIONS: "#e6f0ff",
  SECOND_LINE: "#fff2cc", NOT_RECOMMENDED: "#fdd", NOT_MENTIONED: "#eee"
};
let targetsData = [];

async function loadTargets() {
  const res = await fetch("/api/targets");
  const data = await res.json();
  targetsData = data.targets;
  const box = document.getElementById("targets");
  box.innerHTML = targetsData.map(t =>
    `<label><input type="checkbox" class="tgt" value="${t.name}" checked> ${t.name}` +
    (t.grounded ? ' <span class="badge">🌐 web</span>' : '') + `</label>`
  ).join("");
}

function cardId(name){ return "card-" + name.replace(/[^a-zA-Z0-9]/g, "_"); }

function ensureCard(name, grounded) {
  let el = document.getElementById(cardId(name));
  if (!el) {
    el = document.createElement("div");
    el.className = "card";
    el.id = cardId(name);
    el.innerHTML = `<h3>${name}${grounded ? ' <span class="badge">🌐</span>' : ''}</h3>` +
                   `<div class="score"></div><div class="answer"></div><div class="citations"></div>`;
    document.getElementById("results").appendChild(el);
  }
  return el;
}

function run() {
  const q = document.getElementById("question").value.trim();
  const banner = document.getElementById("banner");
  banner.innerHTML = "";
  if (!q) { banner.innerHTML = '<div class="err">Please enter a question.</div>'; return; }
  document.getElementById("results").innerHTML = "";
  const persona = document.getElementById("persona").value;
  const brand = document.getElementById("brand").value.trim();
  const chosen = Array.from(document.querySelectorAll(".tgt:checked")).map(c => c.value);
  if (!chosen.length) { banner.innerHTML = '<div class="err">Select at least one target.</div>'; return; }

  const params = new URLSearchParams({ question: q, targets: chosen.join(",") });
  if (persona) params.set("persona", persona);
  if (brand) params.set("brand_focus", brand);

  const runBtn = document.getElementById("run");
  const status = document.getElementById("status");
  runBtn.disabled = true; status.textContent = "Running…";

  const es = new EventSource("/api/ask/stream?" + params.toString());
  const groundedByName = Object.fromEntries(targetsData.map(t => [t.name, t.grounded]));

  es.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.event === "answer") {
      const card = ensureCard(ev.llm_name, ev.grounded || groundedByName[ev.llm_name]);
      card.querySelector(".answer").textContent = ev.answer_text || "(no answer — " + ev.status + ")";
      if (ev.citations && ev.citations.length) {
        card.querySelector(".citations").innerHTML = "<strong>Sources:</strong><ul>" +
          ev.citations.map(c => `<li><a href="${c.url}" target="_blank" rel="noopener">${c.title || c.url}</a></li>`).join("") + "</ul>";
      }
    } else if (ev.event === "score") {
      const card = ensureCard(ev.llm_name, groundedByName[ev.llm_name]);
      const color = POSCOLOR[ev.competitive_position] || "#eee";
      card.querySelector(".score").innerHTML =
        `<span class="chip" style="background:${color}">${ev.competitive_position}</span>` +
        `<span class="chip" style="background:#f0f0f0">sentiment ${ev.sentiment_score}</span>`;
    } else if (ev.event === "error") {
      banner.innerHTML = `<div class="err">${ev.message}</div>`;
    } else if (ev.event === "done") {
      es.close(); runBtn.disabled = false; status.textContent = "Done.";
    }
  };
  es.onerror = () => { es.close(); runBtn.disabled = false; status.textContent = "Connection closed."; };
}

document.getElementById("run").addEventListener("click", run);
loadTargets();
</script>
</body>
</html>
```

- [ ] **Step 4: Run it to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/web/test_app.py -q`
Expected: PASS (all, including the markers test)

- [ ] **Step 5: Commit**

```bash
git add ema_poc/web/static/index.html tests/web/test_app.py
git commit -m "feat: self-contained playground frontend (SSE cards + citations + score chips)"
```

---

### Task 6: `ema serve` CLI command

**Files:**
- Modify: `ema_poc/cli.py`
- Test: `tests/test_cli.py` (existing — add a case)

**Design:** Add a `serve` subcommand that builds a `WebDeps` from the real config + a `build_adapters_for(names)` helper (filters config targets by name, builds adapters via the registry) + the scoring client, then runs uvicorn bound to `127.0.0.1`. The uvicorn import and run are lazy and guarded so the test can assert wiring without starting a server (inject a fake `serve_app` into `Deps`).

- [ ] **Step 1: Add a `serve_app` hook to Deps and a failing test**

In `tests/test_cli.py`, add a test that calls `main(["serve", "--port", "9999"], deps=...)` with a fake `serve_app` recording that it was called with a FastAPI app + host/port, asserting `127.0.0.1` and `9999`:

```python
def test_serve_builds_app_and_binds_localhost(monkeypatch, tmp_path):
    from ema_poc.cli import main, Deps
    recorded = {}

    def fake_serve_app(app, *, host, port):
        recorded["host"] = host
        recorded["port"] = port
        recorded["has_routes"] = any(r.path == "/api/ask/stream" for r in app.routes)

    deps = _make_test_deps(tmp_path)  # reuse the existing helper that builds a Deps with fakes
    deps.serve_app = fake_serve_app
    rc = main(["serve", "--port", "9999"], deps=deps)
    assert rc == 0
    assert recorded["host"] == "127.0.0.1"
    assert recorded["port"] == 9999
    assert recorded["has_routes"] is True
```

If `tests/test_cli.py` has no reusable deps helper, construct a `Deps` inline with the same fakes the other CLI tests use (config loader returning an `AppConfig`, `build_adapters` returning `[]`, etc.), and set `serve_app`.

- [ ] **Step 2: Run it to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py -q -k serve`
Expected: FAIL (`serve` subcommand / `serve_app` field missing)

- [ ] **Step 3: Implement**

In `ema_poc/cli.py`:

1. Add `serve_app: Callable | None = None` to the `Deps` dataclass.
2. In `default_deps()`, add a default `serve_app`:

```python
    def _serve_app(app, *, host, port):
        import uvicorn
        uvicorn.run(app, host=host, port=port)
```

and pass `serve_app=_serve_app` in the returned `Deps(...)`.

3. In `_parse_args`, add the subcommand:

```python
    p_serve = sub.add_parser("serve", help="Launch the real-time playground web UI")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
```

4. In `main`, after config load and before/after the existing command branches, handle `serve`:

```python
    if args.command == "serve":
        from ema_poc.web.app import create_app, WebDeps
        from ema_poc.adapters.registry import build_adapters

        deps.validate_credentials(config, deps.env)

        def build_adapters_for(names):
            cfg = config
            if names:
                selected = {n for n in names}
                filtered = [t for t in cfg.targets if t.name in selected and t.enabled]
            else:
                filtered = [t for t in cfg.targets if t.enabled]
            from ema_poc.config import AppConfig
            sub_cfg = AppConfig(settings=cfg.settings, brands=cfg.brands, targets=filtered)
            return deps.build_adapters(sub_cfg, deps.env)

        web_deps = WebDeps(
            config=config,
            build_adapters_for=build_adapters_for,
            scoring_client=deps.make_scoring_client(deps.env),
            scorer=__import__("ema_poc.scoring.scorer", fromlist=["score_response"]).score_response,
            db_path=config.settings.db_path,
        )
        app = create_app(web_deps)
        deps.out(f"Playground on http://{args.host}:{args.port} (Ctrl-C to stop)")
        deps.serve_app(app, host=args.host, port=args.port)
        return 0
```

Place the `serve` branch alongside the other `if args.command == ...` branches. Keep credential validation (so the UI fails fast if keys are missing, IN-502). Note `serve` is added to the set of commands that validate credentials — either include it in the existing tuple check or validate inline as shown.

- [ ] **Step 4: Run it to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py -q -k serve`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add ema_poc/cli.py tests/test_cli.py
git commit -m "feat: ema serve command launches the playground (localhost-bound)"
```

---

### Task 7: Manual smoke test + README

**Files:**
- Modify: `README.md` (document `ema serve`)
- Test: manual

- [ ] **Step 1: Document the command**

In `README.md`, add a "Playground" section:

```markdown
## Real-time playground

Launch a local web UI to ask ad-hoc questions across all targets (including
web-grounded variants), with live per-model answers, citations, and scoring:

    set -a; . ./.env; set +a
    ema serve            # http://127.0.0.1:8000

Results are stored in the isolated `sandbox_*` tables, separate from the
approval-gated monitoring data. Do not enter PII/PHI.
```

- [ ] **Step 2: Manual smoke test (requires real keys)**

```bash
source .venv/bin/activate
set -a; . ./.env; set +a
ema serve --port 8000
```

Open `http://127.0.0.1:8000`, ask a question (e.g. "What are first-line treatments for plaque psoriasis?"), confirm:
- target checkboxes render (grounded ones badged 🌐),
- cards stream in per model,
- grounded targets show a Sources list,
- each card gets a sentiment/position chip.

Stop with Ctrl-C. (This step is manual; CI relies on the fake-based tests.)

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document the ema serve playground"
```

---

## Self-Review Notes (author)

- **Spec coverage:** sandbox tables isolated from monitoring (Task 1) ✅; live fan-out + answer/citations/score events (Task 2) ✅; FastAPI app + /api/targets (Task 3) ✅; SSE stream-per-model (Task 4) ✅; self-contained UI with citations + score chips + PII/PHI note (Task 5) ✅; `ema serve` localhost-bound + credential validation (Task 6) ✅; docs (Task 7) ✅. Tests use fakes/TestClient — no network ✅.
- **Type consistency:** `run_playground(conn, *, adapters, scoring_client, scorer, abbvie_brands, competitor_brands, system_prompts, question_text, persona, brand_focus, model, id_factory, now, max_retries, backoff)` used identically in Task 2 test, Task 2 impl, and Task 4 endpoint. `WebDeps(config, build_adapters_for, scoring_client, scorer, db_path)` consistent across Tasks 3/4/6. Sandbox repo signatures (`create_query`, `save_response`, `save_response_citations`, `set_response_score`, `list_query_responses`, `list_recent_queries`) stable across Task 1 and Task 2. Event `event` keys (`query`/`answer`/`score`/`done`/`error`) consistent between service, endpoint, and frontend.
- **Dependency on Plan 1:** `Citation` and `LLMResponse.citations` come from Plan 1; the playground's grounded behavior and citation persistence assume Plan 1 is merged. Do not start Plan 2 until Plan 1 is on `develop`.
