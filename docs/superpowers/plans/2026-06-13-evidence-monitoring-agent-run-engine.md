# Evidence Monitoring Agent — Run Engine Implementation Plan (Phase 3B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the run engine (FR-2, FR-204/206/207, FR-501/503/504, NF-003/005): runs + responses write repositories (immutable response writes + resumability), a per-target rate limiter, an executor (retry with exponential backoff), and a runner that fans each approved question out to all configured adapters concurrently, writes every response immediately, records an audit entry per call, resumes without re-submitting completed work, and finishes with a run summary.

**Architecture:** Adapter network calls run concurrently in a `ThreadPoolExecutor`; **all SQLite writes happen serially in the runner's main thread** (sqlite3 connections are not shared across threads). The executor is pure (calls `adapter.query`, retries on exception, returns a normalized `LLMResponse` — never touches the DB). The runner reads `active_approved` (Phase 2), resolves a persona-keyed system prompt, dispatches per question across adapters (Phase 3A), and persists each result. Timestamps, ids, sleep, and rate limiters are injectable for deterministic tests.

**Tech Stack:** Python 3.11+, stdlib `sqlite3` + `concurrent.futures` + `threading`, Phase 1 models/db/audit, Phase 2 question repo, Phase 3A adapters. pytest with fake adapters and a real temp SQLite DB.

**Spec:** `docs/superpowers/specs/2026-06-13-evidence-monitoring-agent-poc-design.md` (§3 agent, §4, FR-2, FR-5, NF-003/005).

**Conventions:**
- `now` is an injectable ISO-8601 UTC string; ids via an injectable factory; `sleep` injectable (tests pass a no-op).
- Resumability: a `(question_id, llm_name)` pair is "completed" if it already has a stored response with status != FAILED; resume re-attempts only FAILED/missing pairs.
- The executor and runner never run real `time.sleep` in tests (injected no-op).
- Activate the venv with `. .venv/bin/activate` before pytest.

---

### Task 1: Runs repository

**Files:**
- Create: `ema_poc/repositories/runs.py`
- Test: `tests/repositories/test_runs.py`

- [ ] **Step 1: Write the failing test**

`tests/repositories/test_runs.py`:
```python
from ema_poc.db import connect, init_schema
from ema_poc.repositories.runs import create_run, finish_run, get_run

NOW = "2026-06-13T02:00:00+00:00"
LATER = "2026-06-13T03:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def test_create_and_get_run(tmp_path):
    conn = _conn(tmp_path)
    create_run(conn, "r1", started_at=NOW)
    run = get_run(conn, "r1")
    assert run.run_id == "r1"
    assert run.status == "RUNNING"
    assert run.responses_captured == 0
    assert get_run(conn, "missing") is None
    conn.close()


def test_finish_run_updates_summary_fields(tmp_path):
    conn = _conn(tmp_path)
    create_run(conn, "r1", started_at=NOW)
    finish_run(
        conn,
        "r1",
        ended_at=LATER,
        questions_attempted=10,
        responses_captured=28,
        failure_count=2,
        total_tokens=1234,
        est_cost=0.56,
    )
    run = get_run(conn, "r1")
    assert run.status == "COMPLETED"
    assert run.ended_at is not None
    assert run.questions_attempted == 10
    assert run.responses_captured == 28
    assert run.failure_count == 2
    assert run.total_tokens == 1234
    assert run.est_cost == 0.56
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/repositories/test_runs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.repositories.runs'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/repositories/runs.py`:
```python
"""Runs repository — one row per scheduled/ad-hoc execution batch (FR-503)."""

from __future__ import annotations

import sqlite3

from ema_poc.models import Run


def create_run(conn: sqlite3.Connection, run_id: str, *, started_at: str) -> None:
    conn.execute(
        "INSERT INTO runs (run_id, started_at, status) VALUES (?, ?, 'RUNNING')",
        (run_id, started_at),
    )
    conn.commit()


def get_run(conn: sqlite3.Connection, run_id: str) -> Run | None:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return Run(**dict(row)) if row else None


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    ended_at: str,
    questions_attempted: int,
    responses_captured: int,
    failure_count: int,
    total_tokens: int,
    est_cost: float,
    status: str = "COMPLETED",
) -> None:
    conn.execute(
        """
        UPDATE runs
        SET ended_at = ?, questions_attempted = ?, responses_captured = ?,
            failure_count = ?, total_tokens = ?, est_cost = ?, status = ?
        WHERE run_id = ?
        """,
        (
            ended_at,
            questions_attempted,
            responses_captured,
            failure_count,
            total_tokens,
            est_cost,
            status,
            run_id,
        ),
    )
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/repositories/test_runs.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/repositories/runs.py tests/repositories/test_runs.py
git commit -m "feat: runs repository (create/get/finish)"
```

---

### Task 2: Responses write repository + resumability

**Files:**
- Create: `ema_poc/repositories/responses.py`
- Test: `tests/repositories/test_responses_write.py`

- [ ] **Step 1: Write the failing test**

`tests/repositories/test_responses_write.py`:
```python
from ema_poc.adapters.base import LLMResponse
from ema_poc.db import connect, init_schema
from ema_poc.models import Question, ResponseStatus
from ema_poc.repositories.responses import build_response, completed_keys, save_response
from ema_poc.repositories.runs import create_run

NOW = "2026-06-13T02:00:00+00:00"


class _FakeAdapter:
    def __init__(self, name="GPT-4o", model_version="gpt-4o-2024-11-20"):
        self.name = name
        self.model_version = model_version


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=NOW)
    return conn


def _q(qid="Q1"):
    return Question(
        question_id=qid, question_text="t", persona="Provider", domain="Safety",
        therapeutic_area="Immunology", brand_focus="Skyrizi",
    )


def test_build_response_maps_question_adapter_and_llm():
    llm = LLMResponse(
        text="ans", finish_reason="stop", status="SUCCESS",
        prompt_tokens=10, completion_tokens=20,
    )
    r = build_response(
        run_id="r1", question=_q(), adapter=_FakeAdapter(),
        llm_response=llm, now=NOW, response_id="resp-1",
    )
    assert r.run_id == "r1"
    assert r.llm_name == "GPT-4o"
    assert r.llm_model_version == "gpt-4o-2024-11-20"
    assert r.question_id == "Q1"
    assert r.question_text == "t"
    assert r.therapeutic_area == "Immunology"
    assert r.response_text == "ans"
    assert r.response_tokens == 20  # completion tokens
    assert r.status is ResponseStatus.SUCCESS
    assert r.sentiment_score is None  # scored later
    assert r.alert_triggered is False


def test_save_response_persists_and_is_queryable(tmp_path):
    conn = _conn(tmp_path)
    llm = LLMResponse(text="ans", finish_reason="stop", status="SUCCESS",
                      prompt_tokens=10, completion_tokens=20)
    r = build_response(run_id="r1", question=_q(), adapter=_FakeAdapter(),
                       llm_response=llm, now=NOW, response_id="resp-1")
    save_response(conn, r)
    row = conn.execute(
        "SELECT llm_name, status, response_text FROM responses WHERE response_id='resp-1'"
    ).fetchone()
    assert row["llm_name"] == "GPT-4o"
    assert row["status"] == "SUCCESS"
    assert row["response_text"] == "ans"
    conn.close()


def test_completed_keys_includes_non_failed_only(tmp_path):
    conn = _conn(tmp_path)
    ok = LLMResponse(text="a", finish_reason="stop", status="SUCCESS")
    failed = LLMResponse(text="", finish_reason="error", status="FAILED")
    blocked = LLMResponse(text="", finish_reason="blocked", status="BLOCKED")
    save_response(conn, build_response(run_id="r1", question=_q("Q1"),
                  adapter=_FakeAdapter("GPT-4o"), llm_response=ok, now=NOW, response_id="r-1"))
    save_response(conn, build_response(run_id="r1", question=_q("Q2"),
                  adapter=_FakeAdapter("GPT-4o"), llm_response=failed, now=NOW, response_id="r-2"))
    save_response(conn, build_response(run_id="r1", question=_q("Q3"),
                  adapter=_FakeAdapter("Gemini"), llm_response=blocked, now=NOW, response_id="r-3"))
    keys = completed_keys(conn, "r1")
    assert keys == {("Q1", "GPT-4o"), ("Q3", "Gemini")}  # FAILED Q2 excluded
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/repositories/test_responses_write.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.repositories.responses'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/repositories/responses.py`:
```python
"""Response Repository — immutable response writes + resumability (FR-3, FR-504).

This phase provides the WRITE path and the resumability query only; the rich
query-by-any-combination / export / diff surface is Phase 4."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ema_poc.adapters.base import LLMResponse
from ema_poc.models import Question, Response


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def build_response(
    *,
    run_id: str,
    question: Question,
    adapter,
    llm_response: LLMResponse,
    now: str,
    response_id: str,
) -> Response:
    """Construct a Response row from a question, the adapter that answered, and
    the normalized LLMResponse. sentiment_score/competitive_position stay null
    (populated by the Phase 5 scoring pass)."""
    return Response(
        response_id=response_id,
        run_id=run_id,
        timestamp_utc=now,
        llm_name=adapter.name,
        llm_model_version=adapter.model_version,
        persona=question.persona,
        question_id=question.question_id,
        question_text=question.question_text,
        therapeutic_area=question.therapeutic_area,
        brand_focus=question.brand_focus,
        domain=question.domain,
        response_text=llm_response.text,
        response_tokens=llm_response.completion_tokens,
        finish_reason=llm_response.finish_reason,
        status=llm_response.status,
        alert_triggered=False,
        created_at=now,
    )


def save_response(conn: sqlite3.Connection, response: Response) -> None:
    conn.execute(
        """
        INSERT INTO responses (
            response_id, run_id, timestamp_utc, llm_name, llm_model_version,
            persona, question_id, question_text, therapeutic_area, brand_focus,
            domain, response_text, response_tokens, finish_reason, status,
            sentiment_score, competitive_position, alert_triggered, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            response.response_id,
            response.run_id,
            _iso(response.timestamp_utc),
            response.llm_name,
            response.llm_model_version,
            response.persona.value,
            response.question_id,
            response.question_text,
            response.therapeutic_area,
            response.brand_focus,
            response.domain.value,
            response.response_text,
            response.response_tokens,
            response.finish_reason,
            response.status.value,
            response.sentiment_score,
            response.competitive_position.value
            if response.competitive_position is not None
            else None,
            int(response.alert_triggered),
            _iso(response.created_at),
        ),
    )
    conn.commit()


def completed_keys(conn: sqlite3.Connection, run_id: str) -> set[tuple[str, str]]:
    """(question_id, llm_name) pairs already captured for this run (status !=
    FAILED). Used to resume a run without re-submitting completed work."""
    rows = conn.execute(
        "SELECT DISTINCT question_id, llm_name FROM responses "
        "WHERE run_id = ? AND status != 'FAILED'",
        (run_id,),
    ).fetchall()
    return {(r["question_id"], r["llm_name"]) for r in rows}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/repositories/test_responses_write.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/repositories/responses.py tests/repositories/test_responses_write.py
git commit -m "feat: response write repository + resumability keys"
```

---

### Task 3: Persona system-prompt resolver

**Files:**
- Modify: `ema_poc/config.py` (add `system_prompts` to `Settings`)
- Modify: `config/settings.yaml` (add `system_prompts` block)
- Create: `ema_poc/prompts.py`
- Test: `tests/test_prompts.py`

- [ ] **Step 1: Write the failing test**

`tests/test_prompts.py`:
```python
from ema_poc.config import Settings
from ema_poc.models import Persona
from ema_poc.prompts import resolve_system_prompt


def test_resolves_persona_specific_prompt():
    s = Settings(system_prompts={"Patient": "patient context", "default": "def"})
    assert resolve_system_prompt(Persona.PATIENT, s) == "patient context"


def test_falls_back_to_default_when_persona_absent():
    s = Settings(system_prompts={"default": "the default"})
    assert resolve_system_prompt(Persona.PROVIDER, s) == "the default"


def test_hardcoded_fallback_when_config_empty():
    s = Settings()  # no system_prompts configured
    out = resolve_system_prompt(Persona.PROSPECT, s)
    assert isinstance(out, str) and out  # non-empty fallback
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/test_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.prompts'`.

- [ ] **Step 3: Add `system_prompts` to `Settings` in `ema_poc/config.py`**

In the `Settings` class, add this field (after `anthropic_api_key_env`):
```python
    system_prompts: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 4: Write `ema_poc/prompts.py`**

```python
"""Resolve the persona-specific system prompt for a question (FR-205).

Prompt text lives in config (settings.yaml) so Medical Affairs can review/edit
it without touching code (SE-007). Keyed by persona value, with a `default`
fallback and a hardcoded last resort."""

from __future__ import annotations

from ema_poc.config import Settings

_FALLBACK = (
    "You are responding to a user's health-related question. "
    "Answer helpfully and factually."
)


def resolve_system_prompt(persona, settings: Settings) -> str:
    key = persona.value if hasattr(persona, "value") else str(persona)
    prompts = settings.system_prompts or {}
    return prompts.get(key) or prompts.get("default") or _FALLBACK
```

- [ ] **Step 5: Add the `system_prompts` block to `config/settings.yaml`**

Add this under the `settings:` mapping (these are placeholders for Medical Affairs to review — FR-205):
```yaml
  system_prompts:
    default: "You are a helpful assistant answering a user's health-related question. Answer factually and concisely."
    Patient: "You are a knowledgeable health assistant answering a patient who is asking about their treatment options. Use plain, supportive language."
    Provider: "You are a clinical decision-support assistant answering a healthcare provider's question. Use precise clinical language and cite treatment guidelines where relevant."
    Prospect: "You are a health information assistant answering a prospective patient researching treatment options. Be balanced and informative."
```

- [ ] **Step 6: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/test_prompts.py -v`
Expected: PASS (3 passed). Then `. .venv/bin/activate && pytest -q` to confirm the config change didn't break existing tests.

- [ ] **Step 7: Commit**

```bash
git add ema_poc/config.py ema_poc/prompts.py config/settings.yaml tests/test_prompts.py
git commit -m "feat: persona system-prompt resolver (config-driven)"
```

---

### Task 4: Per-target rate limiter

**Files:**
- Create: `ema_poc/agent/__init__.py`
- Create: `ema_poc/agent/rate_limiter.py`
- Test: `tests/agent/__init__.py`
- Test: `tests/agent/test_rate_limiter.py`

- [ ] **Step 1: Write the failing test**

`tests/agent/__init__.py`:
```python
```

`tests/agent/test_rate_limiter.py`:
```python
from ema_poc.agent.rate_limiter import RateLimiter


def _fake_clock():
    """Returns (clock_fn, sleep_fn, state) with a controllable monotonic clock."""
    state = {"t": 0.0, "sleeps": []}

    def clock():
        return state["t"]

    def sleep(d):
        state["sleeps"].append(d)
        state["t"] += d

    return clock, sleep, state


def test_first_acquire_does_not_sleep():
    clock, sleep, state = _fake_clock()
    rl = RateLimiter(60, clock=clock, sleep=sleep)  # 60/min -> 1s min interval
    rl.acquire()
    assert state["sleeps"] == []


def test_second_acquire_waits_min_interval():
    clock, sleep, state = _fake_clock()
    rl = RateLimiter(60, clock=clock, sleep=sleep)  # 1s interval
    rl.acquire()
    rl.acquire()  # clock hasn't advanced -> must wait ~1s
    assert state["sleeps"] == [1.0]


def test_zero_rpm_disables_limiting():
    clock, sleep, state = _fake_clock()
    rl = RateLimiter(0, clock=clock, sleep=sleep)
    rl.acquire()
    rl.acquire()
    assert state["sleeps"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/agent/test_rate_limiter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.agent'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/agent/__init__.py`:
```python
"""Run engine — executor, rate limiting, and the run loop (§3, FR-2)."""
```

`ema_poc/agent/rate_limiter.py`:
```python
"""Thread-safe per-target rate limiter enforcing a minimum interval between
requests to honor a requests-per-minute cap (FR-207). clock/sleep are
injectable for deterministic tests."""

from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, requests_per_minute: int, *, clock=time.monotonic, sleep=time.sleep):
        self._min_interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = self._clock()
            wait = self._next_allowed - now
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
            self._next_allowed = max(now, self._next_allowed) + self._min_interval
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/agent/test_rate_limiter.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/agent/__init__.py ema_poc/agent/rate_limiter.py tests/agent/__init__.py tests/agent/test_rate_limiter.py
git commit -m "feat: thread-safe per-target rate limiter"
```

---

### Task 5: Executor (retry + backoff)

**Files:**
- Create: `ema_poc/agent/executor.py`
- Test: `tests/agent/test_executor.py`

- [ ] **Step 1: Write the failing test**

`tests/agent/test_executor.py`:
```python
from ema_poc.adapters.base import LLMResponse
from ema_poc.agent.executor import execute


class _Adapter:
    """Replays a list of behaviors: each is an LLMResponse to return or an
    Exception to raise on that call."""

    name = "X"
    model_version = "m"

    def __init__(self, behaviors):
        self._behaviors = behaviors
        self.calls = 0

    def query(self, system_prompt, question_text):
        self.calls += 1
        b = self._behaviors[min(self.calls - 1, len(self._behaviors) - 1)]
        if isinstance(b, Exception):
            raise b
        return b


def test_success_on_first_attempt():
    a = _Adapter([LLMResponse("ok", "stop", "SUCCESS")])
    r = execute(a, "s", "q", max_retries=3, backoff=[2, 4, 8], sleep=lambda d: None)
    assert r.status == "SUCCESS"
    assert a.calls == 1


def test_retries_then_succeeds():
    sleeps = []
    a = _Adapter([RuntimeError("boom"), LLMResponse("ok", "stop", "SUCCESS")])
    r = execute(a, "s", "q", max_retries=3, backoff=[2, 4, 8], sleep=sleeps.append)
    assert r.status == "SUCCESS"
    assert a.calls == 2
    assert sleeps == [2]  # one backoff before the retry


def test_exhausts_retries_then_returns_failed():
    sleeps = []
    a = _Adapter([RuntimeError("down")])
    r = execute(a, "s", "q", max_retries=3, backoff=[2, 4, 8], sleep=sleeps.append)
    assert r.status == "FAILED"
    assert r.finish_reason == "error"
    assert a.calls == 4  # initial + 3 retries
    assert sleeps == [2, 4, 8]
    assert "down" in r.raw["error"]


def test_rate_limiter_acquired_once_per_attempt():
    acquired = []

    class _RL:
        def acquire(self):
            acquired.append(1)

    a = _Adapter([RuntimeError("x"), LLMResponse("ok", "stop", "SUCCESS")])
    execute(a, "s", "q", max_retries=3, backoff=[2, 4, 8],
            rate_limiter=_RL(), sleep=lambda d: None)
    assert len(acquired) == 2  # acquired before each of the 2 attempts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/agent/test_executor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.agent.executor'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/agent/executor.py`:
```python
"""Execute one adapter query with retry + exponential backoff (FR-206/207).

Pure: calls adapter.query and retries on exception, returning a normalized
LLMResponse. Never touches the database (the runner persists results in the
main thread). After max_retries failed attempts, returns a FAILED LLMResponse.
TRUNCATED/BLOCKED responses are returned as-is (stored flagged); the
max_tokens-bump retry of FR-211 is a deferred SHOULD enhancement."""

from __future__ import annotations

import time

from ema_poc.adapters.base import LLMAdapter, LLMResponse


def execute(
    adapter: LLMAdapter,
    system_prompt: str,
    question_text: str,
    *,
    max_retries: int,
    backoff: list[int],
    rate_limiter=None,
    sleep=time.sleep,
) -> LLMResponse:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):  # initial attempt + max_retries retries
        if rate_limiter is not None:
            rate_limiter.acquire()
        try:
            return adapter.query(system_prompt, question_text)
        except Exception as exc:  # transport/transient error — retry
            last_exc = exc
            if attempt < max_retries:
                sleep(backoff[min(attempt, len(backoff) - 1)])
    return LLMResponse(
        text="",
        finish_reason="error",
        status="FAILED",
        raw={"error": str(last_exc)},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/agent/test_executor.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/agent/executor.py tests/agent/test_executor.py
git commit -m "feat: executor with retry and exponential backoff"
```

---

### Task 6: Runner (concurrent fan-out, resumable, run summary)

**Files:**
- Create: `ema_poc/agent/runner.py`
- Test: `tests/agent/test_runner.py`

- [ ] **Step 1: Write the failing test**

`tests/agent/test_runner.py`:
```python
from ema_poc.adapters.base import LLMResponse
from ema_poc.agent.runner import run
from ema_poc.config import (
    AppConfig,
    BrandConfig,
    LLMTargetConfig,
    PricingConfig,
    RateLimitConfig,
    Settings,
)
from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import add_question, approve_question
from ema_poc.repositories.responses import completed_keys
from ema_poc.repositories.runs import get_run

NOW = "2026-06-13T02:00:00+00:00"


class _Adapter:
    """Fake adapter: returns a canned LLMResponse, or raises if behavior is an
    Exception. Records call count."""

    model_version = "m"

    def __init__(self, name, behavior):
        self.name = name
        self._behavior = behavior
        self.calls = 0

    def query(self, system_prompt, question_text):
        self.calls += 1
        if isinstance(self._behavior, Exception):
            raise self._behavior
        return self._behavior


def _config(names, *, in_price=0.001, out_price=0.002):
    targets = [
        LLMTargetConfig(
            name=n, adapter="openai", model_version="m", api_key_env="K",
            pricing=PricingConfig(input_per_1k=in_price, output_per_1k=out_price),
            rate_limit=RateLimitConfig(requests_per_minute=60, tokens_per_minute=1000),
        )
        for n in names
    ]
    return AppConfig(
        settings=Settings(system_prompts={"default": "ctx"}),
        brands=BrandConfig(),
        targets=targets,
    )


def _ids():
    counter = {"n": 0}

    def factory():
        counter["n"] += 1
        return f"id-{counter['n']}"

    return factory


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def _seed_two_approved(conn):
    add_question(conn, question_id="Q1", question_text="a", persona="Provider",
                 domain="Safety", now=NOW)
    approve_question(conn, "Q1", approver_name="R", now=NOW)
    add_question(conn, question_id="Q2", question_text="b", persona="Patient",
                 domain="Efficacy", now=NOW)
    approve_question(conn, "Q2", approver_name="R", now=NOW)


def test_run_fans_out_to_all_adapters_and_saves(tmp_path):
    conn = _conn(tmp_path)
    _seed_two_approved(conn)
    a1 = _Adapter("GPT-4o", LLMResponse("x", "stop", "SUCCESS", prompt_tokens=10, completion_tokens=20))
    a2 = _Adapter("Gemini", LLMResponse("y", "stop", "SUCCESS", prompt_tokens=5, completion_tokens=5))
    cfg = _config(["GPT-4o", "Gemini"])
    summary = run(conn, [a1, a2], cfg, run_id="run-1", id_factory=_ids(),
                  now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    assert summary.responses_captured == 4
    assert summary.by_status["SUCCESS"] == 4
    assert summary.failure_count == 0
    assert summary.questions_attempted == 2
    assert summary.total_tokens == (10 + 20 + 5 + 5) * 2  # both questions
    assert completed_keys(conn, "run-1") == {
        ("Q1", "GPT-4o"), ("Q1", "Gemini"), ("Q2", "GPT-4o"), ("Q2", "Gemini"),
    }
    row = get_run(conn, "run-1")
    assert row.status == "COMPLETED"
    assert row.responses_captured == 4
    conn.close()


def test_run_records_failed_responses(tmp_path):
    conn = _conn(tmp_path)
    _seed_two_approved(conn)
    good = _Adapter("GPT-4o", LLMResponse("x", "stop", "SUCCESS", prompt_tokens=1, completion_tokens=1))
    bad = _Adapter("Gemini", RuntimeError("down"))
    cfg = _config(["GPT-4o", "Gemini"])
    summary = run(conn, [good, bad], cfg, run_id="run-1", id_factory=_ids(),
                  now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    assert summary.by_status["SUCCESS"] == 2
    assert summary.by_status["FAILED"] == 2
    assert summary.failure_count == 2
    # FAILED pairs are NOT marked completed (so a resume retries them)
    assert completed_keys(conn, "run-1") == {("Q1", "GPT-4o"), ("Q2", "GPT-4o")}
    conn.close()


def test_resume_skips_completed_and_retries_failed(tmp_path):
    conn = _conn(tmp_path)
    _seed_two_approved(conn)
    # First run: GPT-4o succeeds, Gemini fails
    run(conn,
        [_Adapter("GPT-4o", LLMResponse("x", "stop", "SUCCESS", prompt_tokens=1, completion_tokens=1)),
         _Adapter("Gemini", RuntimeError("down"))],
        _config(["GPT-4o", "Gemini"]), run_id="run-1", id_factory=_ids(),
        now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    # Resume: GPT-4o should be skipped (already done both Qs); Gemini now healthy
    gpt = _Adapter("GPT-4o", LLMResponse("x2", "stop", "SUCCESS", prompt_tokens=1, completion_tokens=1))
    gem = _Adapter("Gemini", LLMResponse("y2", "stop", "SUCCESS", prompt_tokens=2, completion_tokens=2))
    run(conn, [gpt, gem], _config(["GPT-4o", "Gemini"]), run_id="run-1", id_factory=_ids(),
        now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    assert gpt.calls == 0   # already completed both questions -> skipped
    assert gem.calls == 2   # retried for both questions
    assert completed_keys(conn, "run-1") == {
        ("Q1", "GPT-4o"), ("Q1", "Gemini"), ("Q2", "GPT-4o"), ("Q2", "Gemini"),
    }
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/agent/test_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.agent.runner'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/agent/runner.py`:
```python
"""The run loop (FR-2, FR-204, FR-501/503/504, NF-003/005).

For each active+approved question, fan out to all configured adapters
concurrently (network I/O in a thread pool), then persist every result
serially in this (main) thread — sqlite3 connections are not shared across
threads. Each (question_id, llm_name) already captured (status != FAILED) is
skipped so a run resumes without re-submitting completed work."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from ema_poc.adapters.base import LLMAdapter
from ema_poc.agent.executor import execute
from ema_poc.agent.rate_limiter import RateLimiter
from ema_poc.audit import record_event
from ema_poc.config import AppConfig
from ema_poc.prompts import resolve_system_prompt
from ema_poc.repositories.questions import active_approved
from ema_poc.repositories.responses import build_response, completed_keys, save_response
from ema_poc.repositories.runs import create_run, finish_run, get_run

_STATUSES = ("SUCCESS", "FAILED", "TRUNCATED", "BLOCKED")


@dataclass
class RunSummary:
    run_id: str
    questions_attempted: int
    responses_captured: int
    by_status: dict
    failure_count: int
    total_tokens: int
    est_cost: float


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(
    conn,
    adapters: list[LLMAdapter],
    config: AppConfig,
    *,
    run_id: str | None = None,
    id_factory=lambda: uuid4().hex,
    now_factory=_now_iso,
    rate_limiters: dict | None = None,
    sleep=time.sleep,
    max_workers: int | None = None,
) -> RunSummary:
    started = now_factory()
    if run_id is None:
        run_id = id_factory()
        create_run(conn, run_id, started_at=started)
    elif get_run(conn, run_id) is None:
        create_run(conn, run_id, started_at=started)

    if rate_limiters is None:
        rate_limiters = {
            t.name: RateLimiter(t.rate_limit.requests_per_minute) for t in config.targets
        }
    pricing = {t.name: t.pricing for t in config.targets}

    questions = active_approved(conn)
    done = completed_keys(conn, run_id)

    by_status = {s: 0 for s in _STATUSES}
    questions_attempted = 0
    responses_captured = 0
    failure_count = 0
    total_tokens = 0
    est_cost = 0.0

    pool = ThreadPoolExecutor(max_workers=max_workers or max(1, len(adapters)))
    try:
        for question in questions:
            system_prompt = resolve_system_prompt(question.persona, config.settings)
            futures = {}
            for adapter in adapters:
                if (question.question_id, adapter.name) in done:
                    continue
                futures[
                    pool.submit(
                        execute,
                        adapter,
                        system_prompt,
                        question.question_text,
                        max_retries=config.settings.max_retries,
                        backoff=config.settings.backoff_seconds,
                        rate_limiter=rate_limiters.get(adapter.name),
                        sleep=sleep,
                    )
                ] = adapter

            if not futures:
                continue
            questions_attempted += 1

            for fut in as_completed(futures):
                adapter = futures[fut]
                llm_resp = fut.result()
                response = build_response(
                    run_id=run_id,
                    question=question,
                    adapter=adapter,
                    llm_response=llm_resp,
                    now=now_factory(),
                    response_id=id_factory(),
                )
                save_response(conn, response)
                record_event(
                    conn,
                    event_type="LLM_RESPONSE",
                    role="TARGET",
                    question_id=question.question_id,
                    llm_target=adapter.name,
                    detail=llm_resp.status,
                )
                responses_captured += 1
                by_status[llm_resp.status] = by_status.get(llm_resp.status, 0) + 1
                if llm_resp.status == "FAILED":
                    failure_count += 1
                ptok = llm_resp.prompt_tokens or 0
                ctok = llm_resp.completion_tokens or 0
                total_tokens += ptok + ctok
                price = pricing.get(adapter.name)
                if price is not None:
                    est_cost += (
                        ptok / 1000 * price.input_per_1k
                        + ctok / 1000 * price.output_per_1k
                    )
    finally:
        pool.shutdown(wait=True)

    finish_run(
        conn,
        run_id,
        ended_at=now_factory(),
        questions_attempted=questions_attempted,
        responses_captured=responses_captured,
        failure_count=failure_count,
        total_tokens=total_tokens,
        est_cost=est_cost,
    )
    return RunSummary(
        run_id=run_id,
        questions_attempted=questions_attempted,
        responses_captured=responses_captured,
        by_status=by_status,
        failure_count=failure_count,
        total_tokens=total_tokens,
        est_cost=est_cost,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/agent/test_runner.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/agent/runner.py tests/agent/test_runner.py
git commit -m "feat: runner with concurrent fan-out, resumability, and run summary"
```

---

### Task 7: Run engine integration test

**Files:**
- Test: `tests/agent/test_run_engine_integration.py`

- [ ] **Step 1: Write the integration test**

`tests/agent/test_run_engine_integration.py`:
```python
"""End-to-end run: one approved question fanned out to three adapters returning
SUCCESS / TRUNCATED / BLOCKED, asserting persisted statuses, the run summary,
cost/token accounting, and one audit entry per call."""

import pytest

from ema_poc.adapters.base import LLMResponse
from ema_poc.agent.runner import run
from ema_poc.audit import list_events
from ema_poc.config import (
    AppConfig,
    BrandConfig,
    LLMTargetConfig,
    PricingConfig,
    RateLimitConfig,
    Settings,
)
from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import add_question, approve_question
from ema_poc.repositories.runs import get_run

NOW = "2026-06-13T02:00:00+00:00"


class _Adapter:
    model_version = "m"

    def __init__(self, name, response):
        self.name = name
        self._response = response

    def query(self, system_prompt, question_text):
        return self._response


def _ids():
    counter = {"n": 0}

    def factory():
        counter["n"] += 1
        return f"id-{counter['n']}"

    return factory


def _config(names):
    targets = [
        LLMTargetConfig(
            name=n, adapter="openai", model_version="m", api_key_env="K",
            pricing=PricingConfig(input_per_1k=0.001, output_per_1k=0.002),
            rate_limit=RateLimitConfig(requests_per_minute=60, tokens_per_minute=1000),
        )
        for n in names
    ]
    return AppConfig(settings=Settings(system_prompts={"default": "ctx"}),
                     brands=BrandConfig(), targets=targets)


def test_full_run_persists_all_statuses_summary_and_audit(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    add_question(conn, question_id="Q1", question_text="Is drug X first-line?",
                 persona="Provider", domain="Comparative", now=NOW)
    approve_question(conn, "Q1", approver_name="Dr. A", now=NOW)

    adapters = [
        _Adapter("GPT-4o", LLMResponse("ok", "stop", "SUCCESS",
                                       prompt_tokens=100, completion_tokens=200)),
        _Adapter("Gemini", LLMResponse("cut", "length", "TRUNCATED",
                                       prompt_tokens=10, completion_tokens=1024)),
        _Adapter("Claude", LLMResponse("", "blocked", "BLOCKED",
                                       prompt_tokens=5, completion_tokens=0)),
    ]
    cfg = _config(["GPT-4o", "Gemini", "Claude"])

    summary = run(conn, adapters, cfg, run_id="run-1", id_factory=_ids(),
                  now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)

    # all three captured, one per status
    assert summary.responses_captured == 3
    assert summary.by_status == {"SUCCESS": 1, "TRUNCATED": 1, "BLOCKED": 1, "FAILED": 0}
    assert summary.failure_count == 0

    # token + cost accounting
    assert summary.total_tokens == 100 + 200 + 10 + 1024 + 5 + 0
    expected_cost = (
        (100 / 1000 * 0.001 + 200 / 1000 * 0.002)   # GPT-4o
        + (10 / 1000 * 0.001 + 1024 / 1000 * 0.002)  # Gemini
        + (5 / 1000 * 0.001 + 0 / 1000 * 0.002)      # Claude
    )
    assert summary.est_cost == pytest.approx(expected_cost)

    # persisted statuses on the response rows
    statuses = {
        row["llm_name"]: row["status"]
        for row in conn.execute("SELECT llm_name, status FROM responses").fetchall()
    }
    assert statuses == {"GPT-4o": "SUCCESS", "Gemini": "TRUNCATED", "Claude": "BLOCKED"}

    # run row finalized
    assert get_run(conn, "run-1").status == "COMPLETED"

    # one audit entry per LLM call
    llm_events = [e for e in list_events(conn) if e["event_type"] == "LLM_RESPONSE"]
    assert len(llm_events) == 3
    assert {e["llm_target"] for e in llm_events} == {"GPT-4o", "Gemini", "Claude"}

    conn.close()
```

- [ ] **Step 2: Run the integration test**

Run: `. .venv/bin/activate && pytest tests/agent/test_run_engine_integration.py -v`
Expected: PASS (1 passed). If it fails, the failure points at a real wiring gap — fix the referenced module, do not weaken the test.

- [ ] **Step 3: Run the whole suite with coverage**

Run: `. .venv/bin/activate && pytest -q --cov`
Expected: PASS (all Phase 1 + 2 + 3A + 3B tests green); coverage report prints. Confirm no ResourceWarning: `. .venv/bin/activate && pytest -q -W error::ResourceWarning`.

- [ ] **Step 4: Commit**

```bash
git add tests/agent/test_run_engine_integration.py
git commit -m "test: run engine end-to-end (statuses, summary, cost, audit)"
```

---

## Self-Review

**Spec coverage (Phase 3B scope):**
- FR-201/204 agent retrieves questions and submits to each target, storing all responses for a question before the next → `runner.run` over `active_approved`, per-question fan-out then persist → Task 6.
- FR-206/207 retry up to 3× with 2/4/8s backoff, mark FAILED after; rate limits externalised in config → `executor.execute` + `RateLimiter` from `config.rate_limit` → Tasks 4, 5.
- FR-205 LLM contextualizing system prompt by persona → `resolve_system_prompt` (config-driven) → Task 3.
- FR-208 log every dispatched query/response with target, question id, status → `record_event` audit entry per call → Task 6.
- FR-302/304 immutable structured response records → `build_response` + `save_response` (insert-only) → Task 2.
- FR-501/503 run with unique run_id + run record (counts, tokens, cost) → runs repo + `finish_run` + `RunSummary` → Tasks 1, 6.
- FR-504 / NF-005 resumable without re-submitting completed work, no data loss → immediate per-response write + `completed_keys` skip → Tasks 2, 6.
- NF-003 parallel execution across targets → `ThreadPoolExecutor` fan-out (DB writes serial in main thread) → Task 6.
- NF-014 token + estimated cost per run → token/cost accumulation in the runner → Task 6.

Deferred (correctly out of scope): the FR-211 max_tokens-bump truncation *retry* (TRUNCATED is detected/stored/flagged here; the bump is a documented SHOULD enhancement); FR-209 dry-run, FR-505 notification, FR-506 ad-hoc CLI, NF-009 health-check (the Scheduling/CLI phase); the Response Repository query/export/diff surface (Phase 4); scoring/alerts (Phase 5). Known tracked items: Gemini empty-candidates guard (from Phase 3A review) and the `gemini-1.5-pro` pin.

**Placeholder scan:** No "TBD"/"add error handling"/"similar to" placeholders — every code and test step is complete.

**Type/name consistency:** `create_run`/`get_run`/`finish_run` (runs.py) used identically across Tasks 1, 6. `build_response`/`save_response`/`completed_keys` (responses.py) consistent across Tasks 2, 6, 7. `execute(adapter, system_prompt, question_text, *, max_retries, backoff, rate_limiter, sleep)` matches how the runner submits it (Task 6) and the executor test (Task 5). `RateLimiter(requests_per_minute, *, clock, sleep).acquire()` matches the runner's construction and the executor's `rate_limiter.acquire()`. `resolve_system_prompt(persona, settings)` matches the runner call. `RunSummary` fields (run_id, questions_attempted, responses_captured, by_status, failure_count, total_tokens, est_cost) match the assertions in Tasks 6–7. Status strings (SUCCESS/FAILED/TRUNCATED/BLOCKED) and the responses schema columns match Phase 1 + Phase 3A.
