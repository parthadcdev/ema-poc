# Background Playground Jobs + Question History — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run each playground question as a DB-backed background job whose results persist and stay retrievable across navigation, reload, and redeploy.

**Architecture:** `POST /api/ask` creates a `RUNNING` row in `sandbox_queries` and runs `run_playground` on a background thread pool; the browser polls `GET /api/queries/{id}` until done and lists history via `GET /api/queries`. SSE is removed. A startup sweep marks restart-interrupted runs `FAILED`.

**Tech Stack:** Python 3.11+, FastAPI, sqlite3 (stdlib), `concurrent.futures.ThreadPoolExecutor`, vanilla JS. Tests offline with fakes (no SDKs/network).

**Spec:** `docs/superpowers/specs/2026-06-15-background-jobs-design.md`. **Branch:** `feature/background-jobs`.

**Run the suite with the project venv:** `.venv/bin/python -m pytest`. Baseline is **624 passing**.

---

### Task 1: Schema columns + busy_timeout

**Files:**
- Modify: `ema_poc/db.py` (`_ADDITIVE_COLUMNS` ~line 212, `connect` ~line 230)
- Test: `tests/test_schema_jobs.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema_jobs.py
from ema_poc.db import connect, init_schema


def test_sandbox_queries_has_job_columns(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sandbox_queries)")}
    assert {"status", "target_count", "started_at", "finished_at", "error_text"} <= cols


def test_job_columns_added_to_preexisting_db(tmp_path):
    # Simulate an old DB created before the job columns existed.
    import sqlite3
    p = str(tmp_path / "old.sqlite")
    raw = sqlite3.connect(p)
    raw.execute(
        "CREATE TABLE sandbox_queries (query_id TEXT PRIMARY KEY, timestamp_utc TEXT, "
        "question_text TEXT, persona TEXT, brand_focus TEXT)"
    )
    raw.commit(); raw.close()
    conn = connect(p)
    init_schema(conn)  # additive migration must add the new columns
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sandbox_queries)")}
    assert "status" in cols and "error_text" in cols


def test_connect_sets_busy_timeout(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_schema_jobs.py -v`
Expected: FAIL (columns missing / busy_timeout is 0).

- [ ] **Step 3: Implement**

In `ema_poc/db.py`, append to `_ADDITIVE_COLUMNS` (after the `("questions", "source", ...)` entry):

```python
    ("sandbox_queries", "status", "TEXT"),
    ("sandbox_queries", "target_count", "INTEGER"),
    ("sandbox_queries", "started_at", "TEXT"),
    ("sandbox_queries", "finished_at", "TEXT"),
    ("sandbox_queries", "error_text", "TEXT"),
```

In `connect`, add the busy_timeout pragma:

```python
def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn
```

> NOTE: the columns are also added to the `SCHEMA` `CREATE TABLE sandbox_queries`
> ONLY if you prefer; the additive migration already covers fresh + old DBs, so
> editing `_ADDITIVE_COLUMNS` alone is sufficient. Do NOT add a NOT NULL/DEFAULT —
> keep them nullable (legacy rows read as DONE in Task 2).

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_schema_jobs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ema_poc/db.py tests/test_schema_jobs.py
git commit -m "feat: add job-status columns to sandbox_queries + busy_timeout"
```

---

### Task 2: Repository — job status, summaries, sweep

**Files:**
- Modify: `ema_poc/repositories/sandbox.py`
- Test: `tests/repositories/test_sandbox_jobs.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/repositories/test_sandbox_jobs.py
from ema_poc.db import connect, init_schema
from ema_poc.repositories import sandbox as S


def _conn(tmp_path):
    c = connect(str(tmp_path / "s.sqlite")); init_schema(c); return c


def test_create_query_records_running_status(tmp_path):
    c = _conn(tmp_path)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None,
                         now="2026-06-15T00:00:00+00:00", status="RUNNING",
                         target_count=3, started_at="2026-06-15T00:00:00+00:00")
    q = S.get_query(c, qid)
    assert q.status == "RUNNING" and q.target_count == 3
    assert q.started_at == "2026-06-15T00:00:00+00:00"


def test_get_query_unknown_returns_none(tmp_path):
    assert S.get_query(_conn(tmp_path), "nope") is None


def test_mark_done_and_failed(tmp_path):
    c = _conn(tmp_path)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None,
                         now="t0", status="RUNNING", target_count=1, started_at="t0")
    S.mark_query_done(c, qid, finished_at="t1")
    assert S.get_query(c, qid).status == "DONE"
    qid2 = S.create_query(c, question_text="q2", persona=None, brand_focus=None,
                          now="t0", status="RUNNING", target_count=1, started_at="t0")
    S.mark_query_failed(c, qid2, finished_at="t1", error_text="boom")
    q2 = S.get_query(c, qid2)
    assert q2.status == "FAILED" and q2.error_text == "boom"


def test_sweep_stale_running_marks_failed(tmp_path):
    c = _conn(tmp_path)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None,
                         now="t0", status="RUNNING", target_count=1, started_at="t0")
    n = S.sweep_stale_running(c, finished_at="t9")
    assert n == 1
    q = S.get_query(c, qid)
    assert q.status == "FAILED" and q.error_text == "interrupted by restart"


def test_list_recent_queries_returns_status_and_counts(tmp_path):
    c = _conn(tmp_path)
    qid = S.create_query(c, question_text="q", persona="Provider", brand_focus="Skyrizi",
                         now="2026-06-15T00:00:00+00:00", status="RUNNING",
                         target_count=2, started_at="2026-06-15T00:00:00+00:00")
    S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v", grounded=False,
                    answer_text="a", response_tokens=1, finish_reason="stop",
                    status="SUCCESS", now="t1")
    rows = S.list_recent_queries(c)
    assert len(rows) == 1
    assert rows[0].status == "RUNNING"
    assert rows[0].done_count == 1 and rows[0].total_count == 2


def test_legacy_null_status_reads_as_done(tmp_path):
    c = _conn(tmp_path)
    # Insert a row with NULL status (legacy), bypassing create_query.
    c.execute("INSERT INTO sandbox_queries (query_id, timestamp_utc, question_text, "
              "persona, brand_focus) VALUES ('L','t','q',NULL,NULL)")
    c.commit()
    assert S.get_query(c, "L").status == "DONE"
    assert S.list_recent_queries(c)[0].status == "DONE"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/repositories/test_sandbox_jobs.py -v`
Expected: FAIL (`create_query` has no `status` kwarg; `get_query`/`mark_*`/`sweep_*` undefined; `list_recent_queries` rows have no `status`/`done_count`).

- [ ] **Step 3: Implement**

In `ema_poc/repositories/sandbox.py`:

Extend `SandboxQuery` and add `QuerySummary`:

```python
@dataclass
class SandboxQuery:
    query_id: str
    timestamp_utc: str
    question_text: str
    persona: str | None
    brand_focus: str | None
    status: str = "DONE"            # legacy NULL reads as DONE
    target_count: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error_text: str | None = None


@dataclass
class QuerySummary:
    query_id: str
    timestamp_utc: str
    question_text: str
    persona: str | None
    brand_focus: str | None
    status: str
    done_count: int
    total_count: int
```

Replace `create_query` with (adds status/target_count/started_at):

```python
def create_query(
    conn, *, question_text, persona, brand_focus, now, id_factory=lambda: uuid4().hex,
    status: str = "RUNNING", target_count: int | None = None, started_at: str | None = None,
    commit: bool = True,
) -> str:
    query_id = id_factory()
    conn.execute(
        """INSERT INTO sandbox_queries
           (query_id, timestamp_utc, question_text, persona, brand_focus,
            status, target_count, started_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (query_id, now, question_text, persona, brand_focus, status, target_count, started_at),
    )
    if commit:
        conn.commit()
    return query_id
```

Add after `set_response_score`:

```python
def mark_query_done(conn, query_id, *, finished_at, commit: bool = True) -> None:
    conn.execute("UPDATE sandbox_queries SET status='DONE', finished_at=? WHERE query_id=?",
                 (finished_at, query_id))
    if commit:
        conn.commit()


def mark_query_failed(conn, query_id, *, finished_at, error_text, commit: bool = True) -> None:
    conn.execute("UPDATE sandbox_queries SET status='FAILED', finished_at=?, error_text=? "
                 "WHERE query_id=?", (finished_at, error_text, query_id))
    if commit:
        conn.commit()


def sweep_stale_running(conn, *, finished_at, commit: bool = True) -> int:
    cur = conn.execute(
        "UPDATE sandbox_queries SET status='FAILED', finished_at=?, "
        "error_text='interrupted by restart' WHERE status='RUNNING'", (finished_at,))
    if commit:
        conn.commit()
    return cur.rowcount


def get_query(conn, query_id) -> SandboxQuery | None:
    r = conn.execute(
        """SELECT query_id, timestamp_utc, question_text, persona, brand_focus,
                  COALESCE(status,'DONE') AS status, target_count, started_at,
                  finished_at, error_text
           FROM sandbox_queries WHERE query_id = ?""", (query_id,)).fetchone()
    return SandboxQuery(**dict(r)) if r else None
```

Replace `list_recent_queries` to return `QuerySummary` with counts:

```python
def list_recent_queries(conn, limit: int = 25) -> list[QuerySummary]:
    rows = conn.execute(
        """SELECT q.query_id, q.timestamp_utc, q.question_text, q.persona, q.brand_focus,
                  COALESCE(q.status,'DONE') AS status, q.target_count,
                  (SELECT COUNT(*) FROM sandbox_responses r WHERE r.query_id = q.query_id)
                      AS done_count
           FROM sandbox_queries q
           ORDER BY q.timestamp_utc DESC, q.query_id DESC LIMIT ?""", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        total = d["target_count"] if d["target_count"] is not None else d["done_count"]
        out.append(QuerySummary(
            query_id=d["query_id"], timestamp_utc=d["timestamp_utc"],
            question_text=d["question_text"], persona=d["persona"],
            brand_focus=d["brand_focus"], status=d["status"],
            done_count=d["done_count"], total_count=total))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/repositories/test_sandbox_jobs.py -v`
Expected: PASS.

- [ ] **Step 5: Check for callers broken by the `list_recent_queries` return-type change**

Run: `grep -rn "list_recent_queries" ema_poc tests`
If any existing test asserted `SandboxQuery` fields on the result, update it to `QuerySummary`. (As of writing only this feature consumes it.) Run the full suite:
Run: `.venv/bin/python -m pytest`
Expected: 624 + new tests passing (fix any fallout before committing).

- [ ] **Step 6: Commit**

```bash
git add ema_poc/repositories/sandbox.py tests/repositories/test_sandbox_jobs.py
git commit -m "feat: sandbox query job-status repo (create/mark/get/sweep/summaries)"
```

---

### Task 3: Service accepts a pre-created query_id

**Files:**
- Modify: `ema_poc/playground/service.py` (`run_playground`, lines 20-36)
- Test: `tests/playground/test_service_query_id.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/playground/test_service_query_id.py
from ema_poc.db import connect, init_schema
from ema_poc.playground.service import run_playground
from ema_poc.repositories import sandbox as S
from ema_poc.adapters.base import LLMResponse


class FakeAdapter:
    name = "A"; model_version = "v"; grounded = False
    def query(self, sp, q):
        return LLMResponse(text="ans", finish_reason="stop", status="SUCCESS",
                           completion_tokens=3)


class FakeScore:
    sentiment_score = 0.5; competitive_position = "AMONG_OPTIONS"; scoring_rationale = "r"


def test_run_playground_uses_provided_query_id(tmp_path):
    c = connect(str(tmp_path / "s.sqlite")); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None, now="t0",
                         status="RUNNING", target_count=1, started_at="t0")
    events = list(run_playground(
        c, query_id=qid, adapters=[FakeAdapter()], scoring_client=object(),
        scorer=lambda *a, **k: FakeScore(), abbvie_brands=[], competitor_brands=[],
        system_prompts={"default": "x"}, question_text="q", persona=None,
        brand_focus=None, model="m", id_factory=lambda: __import__("uuid").uuid4().hex,
        now="t1", max_retries=0, backoff=0))
    # No NEW query row created; the provided id is reused.
    assert events[0] == {"event": "query", "query_id": qid}
    assert len(S.list_query_responses(c, qid)) == 1
    assert c.execute("SELECT COUNT(*) FROM sandbox_queries").fetchone()[0] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/playground/test_service_query_id.py -v`
Expected: FAIL (`run_playground` has no `query_id` param).

- [ ] **Step 3: Implement**

In `ema_poc/playground/service.py`, change the signature and the create block:

```python
def run_playground(
    conn, *, adapters, scoring_client, scorer, abbvie_brands, competitor_brands,
    system_prompts, question_text, persona, brand_focus, model,
    id_factory, now, max_retries, backoff, query_id=None,
):
    if not adapters:
        yield {"event": "error", "message": "No targets selected."}
        return

    if query_id is None:
        query_id = S.create_query(
            conn, question_text=question_text, persona=persona, brand_focus=brand_focus,
            now=now, id_factory=id_factory, status="RUNNING",
            target_count=len(adapters), started_at=now,
        )
    yield {"event": "query", "query_id": query_id}
```

(The rest of the function is unchanged.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/playground/test_service_query_id.py -v`
Expected: PASS.

- [ ] **Step 5: Confirm existing service/web tests still pass**

Run: `.venv/bin/python -m pytest tests/playground -q`
Expected: PASS (the `query_id=None` default preserves prior behavior).

- [ ] **Step 6: Commit**

```bash
git add ema_poc/playground/service.py tests/playground/test_service_query_id.py
git commit -m "feat: run_playground accepts a pre-created query_id"
```

---

### Task 4: JobManager (background runner)

**Files:**
- Create: `ema_poc/playground/jobs.py`
- Test: `tests/playground/test_jobs.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/playground/test_jobs.py
from ema_poc.db import connect, init_schema
from ema_poc.playground.jobs import JobManager
from ema_poc.repositories import sandbox as S
from ema_poc.config import AppConfig, Settings, BrandConfig
from ema_poc.adapters.base import LLMResponse


class FakeAdapter:
    def __init__(self, name="A", boom=False):
        self.name = name; self.model_version = "v"; self.grounded = False; self._boom = boom
    def query(self, sp, q):
        if self._boom:
            raise RuntimeError("adapter down")
        return LLMResponse(text="ans", finish_reason="stop", status="SUCCESS",
                           completion_tokens=3)


class FakeScore:
    sentiment_score = 0.5; competitive_position = "AMONG_OPTIONS"; scoring_rationale = "r"


def _cfg():
    return AppConfig(settings=Settings(system_prompts={"default": "x"}),
                     brands=BrandConfig(), targets=[])


_INLINE = lambda fn, *a: fn(*a)   # run the job synchronously in tests


def _mgr(tmp_path, adapters):
    return JobManager(
        db_path=str(tmp_path / "j.sqlite"),
        build_adapters_for=lambda names: adapters,
        scoring_client=object(), scorer=lambda *a, **k: FakeScore(), config=_cfg(),
        id_factory=lambda: __import__("uuid").uuid4().hex,
        now_factory=lambda: "t", max_concurrent=2, submit_fn=_INLINE)


def test_submit_runs_to_done_and_persists(tmp_path):
    mgr = _mgr(tmp_path, [FakeAdapter("A")])
    qid = mgr.submit(question="q", persona=None, brand_focus=None, selected_targets=None)
    c = connect(str(tmp_path / "j.sqlite")); init_schema(c)
    assert S.get_query(c, qid).status == "DONE"
    assert S.get_query(c, qid).target_count == 1
    assert len(S.list_query_responses(c, qid)) == 1


def test_adapter_error_still_completes_job(tmp_path):
    # A per-target adapter failure surfaces as an error event inside run_playground,
    # not a crash — the job still completes DONE.
    mgr = _mgr(tmp_path, [FakeAdapter("A", boom=True)])
    qid = mgr.submit(question="q", persona=None, brand_focus=None, selected_targets=None)
    c = connect(str(tmp_path / "j.sqlite")); init_schema(c)
    assert S.get_query(c, qid).status == "DONE"


def test_job_marked_failed_when_runner_raises(tmp_path, monkeypatch):
    # A whole-job failure (run_playground itself raises) marks the query FAILED.
    import ema_poc.playground.jobs as jobs
    def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(jobs, "run_playground", boom)
    mgr = _mgr(tmp_path, [FakeAdapter("A")])
    qid = mgr.submit(question="q", persona=None, brand_focus=None, selected_targets=None)
    c = connect(str(tmp_path / "j.sqlite")); init_schema(c)
    q = S.get_query(c, qid)
    assert q.status == "FAILED" and "kaboom" in (q.error_text or "")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/playground/test_jobs.py -v`
Expected: FAIL (`ema_poc.playground.jobs` does not exist).

- [ ] **Step 3: Implement**

```python
# ema_poc/playground/jobs.py
"""Background runner for playground questions. submit() creates the RUNNING query
row and schedules run_playground on a thread pool; the DB is the source of truth.
The executor is injectable (submit_fn) so tests run inline and deterministically."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from ema_poc.db import connect, init_schema
from ema_poc.playground.service import run_playground
from ema_poc.repositories import sandbox as S


class JobManager:
    def __init__(self, *, db_path, build_adapters_for, scoring_client, scorer, config,
                 id_factory=lambda: uuid4().hex, now_factory, max_concurrent=2,
                 submit_fn=None):
        self.db_path = db_path
        self.build_adapters_for = build_adapters_for
        self.scoring_client = scoring_client
        self.scorer = scorer
        self.config = config
        self.id_factory = id_factory
        self.now_factory = now_factory
        if submit_fn is not None:
            self._submit = submit_fn
        else:
            self._pool = ThreadPoolExecutor(max_workers=max(1, max_concurrent))
            self._submit = lambda fn, *a: self._pool.submit(fn, *a)

    def submit(self, *, question, persona, brand_focus, selected_targets) -> str:
        adapters = self.build_adapters_for(selected_targets)
        now = self.now_factory()
        conn = connect(self.db_path)
        try:
            init_schema(conn)
            query_id = S.create_query(
                conn, question_text=question, persona=persona, brand_focus=brand_focus,
                now=now, id_factory=self.id_factory, status="RUNNING",
                target_count=len(adapters), started_at=now)
        finally:
            conn.close()
        self._submit(self._run, query_id, adapters, question, persona, brand_focus)
        return query_id

    def _run(self, query_id, adapters, question, persona, brand_focus):
        cfg = self.config
        conn = connect(self.db_path)
        try:
            init_schema(conn)
            gen = run_playground(
                conn, query_id=query_id, adapters=adapters,
                scoring_client=self.scoring_client, scorer=self.scorer,
                abbvie_brands=cfg.brands.abbvie_brands,
                competitor_brands=cfg.brands.competitor_brands,
                system_prompts=cfg.settings.system_prompts, question_text=question,
                persona=persona, brand_focus=brand_focus, model=cfg.settings.scoring_model,
                id_factory=self.id_factory, now=self.now_factory(),
                max_retries=cfg.settings.max_retries, backoff=cfg.settings.backoff_seconds)
            for _ in gen:
                pass
            S.mark_query_done(conn, query_id, finished_at=self.now_factory())
        except Exception as exc:  # whole-job failure
            S.mark_query_failed(conn, query_id, finished_at=self.now_factory(),
                                error_text=str(exc))
        finally:
            conn.close()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/playground/test_jobs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ema_poc/playground/jobs.py tests/playground/test_jobs.py
git commit -m "feat: JobManager runs playground questions in the background"
```

---

### Task 5: API — submit/list/detail endpoints, startup sweep

**Files:**
- Modify: `ema_poc/web/app.py` (remove `ask_stream`, add routes + manager + sweep; `WebDeps`)
- Test: `tests/web/test_jobs_api.py` (create); delete `tests/web/test_stream.py`
- Check: `tests/web/test_app.py` for any `/api/ask/stream` references

- [ ] **Step 1: Write the failing test**

```python
# tests/web/test_jobs_api.py
from fastapi.testclient import TestClient

from ema_poc.web.app import create_app, WebDeps
from ema_poc.config import AppConfig, Settings, BrandConfig, LLMTargetConfig
from ema_poc.adapters.base import LLMResponse


class FakeAdapter:
    def __init__(self, name="GPT-4o"):
        self.name = name; self.model_version = name + "-v"; self.grounded = False
    def query(self, sp, q):
        return LLMResponse(text=f"{self.name} ans", finish_reason="stop",
                           status="SUCCESS", completion_tokens=5)


class FakeScore:
    sentiment_score = 0.5; competitive_position = "AMONG_OPTIONS"; scoring_rationale = "r"


def _deps(tmp_path, env=None):
    cfg = AppConfig(settings=Settings(system_prompts={"default": "x"}),
                    brands=BrandConfig(),
                    targets=[LLMTargetConfig(
                        name="GPT-4o", adapter="openai", model_version="gpt-4o",
                        api_key_env="OPENAI_API_KEY",
                        pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
                        rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1})])
    d = WebDeps(config=cfg, build_adapters_for=lambda names: [FakeAdapter()],
                scoring_client=object(), scorer=lambda *a, **k: FakeScore(),
                db_path=str(tmp_path / "w.sqlite"), env=env)
    d.job_submit_fn = lambda fn, *a: fn(*a)   # run inline for deterministic tests
    return d


def test_ask_submit_then_list_then_detail(tmp_path):
    client = TestClient(create_app(_deps(tmp_path)))
    r = client.post("/api/ask", json={"question": "What treats psoriasis?",
                                       "persona": "Provider", "brand_focus": "Skyrizi"})
    assert r.status_code == 202
    qid = r.json()["query_id"]

    lst = client.get("/api/queries").json()["queries"]
    assert any(q["query_id"] == qid and q["status"] == "DONE" for q in lst)

    detail = client.get(f"/api/queries/{qid}").json()
    assert detail["query"]["status"] == "DONE"
    assert len(detail["responses"]) == 1
    assert detail["responses"][0]["llm_name"] == "GPT-4o"
    assert detail["responses"][0]["sentiment_score"] == 0.5


def test_ask_requires_question(tmp_path):
    client = TestClient(create_app(_deps(tmp_path)))
    assert client.post("/api/ask", json={"question": "  "}).status_code == 400


def test_unknown_query_is_404(tmp_path):
    client = TestClient(create_app(_deps(tmp_path)))
    assert client.get("/api/queries/nope").status_code == 404


def test_ask_rate_limited(tmp_path):
    client = TestClient(create_app(_deps(tmp_path, env={"PLAYGROUND_MAX_QUERIES_PER_HOUR": "1"})))
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 202
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 429


def test_startup_sweeps_stale_running(tmp_path):
    # Pre-seed a RUNNING row, then build the app — startup sweep marks it FAILED.
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories import sandbox as S
    p = str(tmp_path / "w.sqlite")
    c = connect(p); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None, now="t0",
                         status="RUNNING", target_count=1, started_at="t0"); c.close()
    d = _deps(tmp_path); d.db_path = p
    create_app(d)
    c2 = connect(p); init_schema(c2)
    assert S.get_query(c2, qid).status == "FAILED"


def test_auth_enforced_on_jobs_routes(tmp_path):
    d = _deps(tmp_path, env={"APP_PASSWORD": "pw", "APP_USER": "abbvie"})
    client = TestClient(create_app(d))
    assert client.get("/api/queries").status_code == 401
    assert client.get("/api/queries", auth=("abbvie", "pw")).status_code == 200
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/web/test_jobs_api.py -v`
Expected: FAIL (`/api/ask` POST + `/api/queries` undefined; `job_submit_fn` not on `WebDeps`).

- [ ] **Step 3: Implement**

In `ema_poc/web/app.py`:

Add the import near the top:

```python
from pydantic import BaseModel
from ema_poc.playground.jobs import JobManager
from ema_poc.repositories import sandbox as S
```

Add `job_submit_fn` to `WebDeps`:

```python
@dataclass
class WebDeps:
    config: object
    build_adapters_for: Callable
    scoring_client: object
    scorer: Callable
    db_path: str
    env: object = None
    job_submit_fn: object = None   # inject inline executor in tests; None = real threads
```

Add the request body model above `create_app`:

```python
class AskBody(BaseModel):
    question: str
    persona: str | None = None
    brand_focus: str | None = None
    targets: list[str] | None = None
```

Inside `create_app`, after `app.state.rate_store = {}`, build the manager and run the
startup sweep, then **remove the entire `ask_stream` route** and add the three routes:

```python
    app.state.jobs = JobManager(
        db_path=deps.db_path, build_adapters_for=deps.build_adapters_for,
        scoring_client=deps.scoring_client, scorer=deps.scorer, config=deps.config,
        id_factory=lambda: uuid4().hex,
        now_factory=lambda: datetime.now(timezone.utc).isoformat(),
        max_concurrent=int((deps.env or {}).get("PLAYGROUND_MAX_CONCURRENT_JOBS", "2") or "2"),
        submit_fn=deps.job_submit_fn)

    # Startup sweep: any RUNNING row is from a process that is no longer alive.
    _sweep_conn = connect(deps.db_path)
    try:
        init_schema(_sweep_conn)
        S.sweep_stale_running(_sweep_conn, finished_at=datetime.now(timezone.utc).isoformat())
    finally:
        _sweep_conn.close()

    @app.post("/api/ask", status_code=status.HTTP_202_ACCEPTED)
    def ask(request: Request, body: AskBody):
        if not body.question or not body.question.strip():
            raise HTTPException(status_code=400, detail="question is required")
        cap = int((deps.env or {}).get("PLAYGROUND_MAX_QUERIES_PER_HOUR", "60") or "60")
        ip = request.client.host if request.client else "unknown"
        if not _check_rate(app.state.rate_store, ip, cap, time.time()):
            raise HTTPException(status_code=429, detail="Query limit reached — try again later.")
        query_id = app.state.jobs.submit(
            question=body.question.strip(), persona=body.persona,
            brand_focus=body.brand_focus, selected_targets=body.targets)
        return {"query_id": query_id}

    @app.get("/api/queries")
    def list_queries():
        conn = connect(deps.db_path)
        try:
            init_schema(conn)
            rows = S.list_recent_queries(conn)
        finally:
            conn.close()
        return {"queries": [
            {"query_id": q.query_id, "question_text": q.question_text, "persona": q.persona,
             "brand_focus": q.brand_focus, "timestamp_utc": q.timestamp_utc,
             "status": q.status, "done_count": q.done_count, "total_count": q.total_count}
            for q in rows]}

    @app.get("/api/queries/{query_id}")
    def query_detail(query_id: str):
        conn = connect(deps.db_path)
        try:
            init_schema(conn)
            q = S.get_query(conn, query_id)
            if q is None:
                raise HTTPException(status_code=404, detail="query not found")
            responses = S.list_query_responses(conn, query_id)
        finally:
            conn.close()
        return {
            "query": {"query_id": q.query_id, "question_text": q.question_text,
                      "persona": q.persona, "brand_focus": q.brand_focus,
                      "status": q.status, "target_count": q.target_count,
                      "timestamp_utc": q.timestamp_utc, "error_text": q.error_text},
            "responses": [
                {"llm_name": r.llm_name, "grounded": r.grounded, "status": r.status,
                 "answer_text": r.answer_text, "tokens": r.response_tokens,
                 "finish_reason": r.finish_reason, "sentiment_score": r.sentiment_score,
                 "competitive_position": r.competitive_position,
                 "scoring_rationale": r.scoring_rationale,
                 "citations": [{"title": c.title, "url": c.url, "snippet": c.snippet}
                               for c in r.citations]}
                for r in responses]}
```

Then delete the old SSE route and its now-unused imports if any (`StreamingResponse`,
`Query`, `json` may still be used elsewhere — only remove an import if `grep` shows no
other use in the file).

- [ ] **Step 4: Delete the obsolete stream test and run the suite**

```bash
git rm tests/web/test_stream.py
grep -rn "ask/stream" tests ema_poc   # update any stragglers in tests/web/test_app.py
```
Run: `.venv/bin/python -m pytest tests/web -v`
Expected: PASS. Then full suite:
Run: `.venv/bin/python -m pytest`
Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add ema_poc/web/app.py tests/web/test_jobs_api.py
git add -u tests/web   # records the test_stream.py deletion
git commit -m "feat: background-job API (POST /api/ask, GET /api/queries[/{id}]) + startup sweep"
```

---

### Task 6: UI — submit + poll + Recent questions panel

**Files:**
- Modify: `ema_poc/web/static/index.html`
- Test: `tests/web/test_index_jobs.py` (create)

- [ ] **Step 1: Write the failing test (structural — no JS runtime in CI)**

```python
# tests/web/test_index_jobs.py
from pathlib import Path

HTML = Path("ema_poc/web/static/index.html").read_text()


def test_index_uses_submit_and_poll_not_sse():
    assert "EventSource" not in HTML            # SSE removed
    assert "/api/ask" in HTML                   # POST submit
    assert "/api/queries" in HTML               # poll + history list


def test_index_has_recent_questions_panel():
    assert 'id="recent-list"' in HTML           # history container


def test_index_keeps_markdown_and_xss_helpers():
    assert "function renderMarkdown" in HTML
    assert "function esc" in HTML and "function safeUrl" in HTML


def test_index_is_self_contained():
    # no external resource references (allow the SVG xmlns only)
    for marker in ["http://", "https://"]:
        for line in HTML.splitlines():
            if marker in line:
                assert "www.w3.org/2000/svg" in line, f"external resource: {line.strip()}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/web/test_index_jobs.py -v`
Expected: FAIL (`EventSource` still present; no `recent-list`).

- [ ] **Step 3: Implement the UI changes**

In `ema_poc/web/static/index.html`:

(a) Add a **Recent questions** panel in the markup (place it in the existing
results/sidebar area; follow the existing class/theme names). Minimum required markup:

```html
<aside class="recent-panel">
  <h3 class="recent-title">Recent questions</h3>
  <ul id="recent-list"></ul>
</aside>
```

(b) Replace the `EventSource`-based submit handler with submit + poll. Remove the
`new EventSource(...)` block entirely and add:

```javascript
let pollTimer = null;

async function refreshRecent() {
  const res = await fetch('/api/queries');
  if (!res.ok) return;
  const { queries } = await res.json();
  const ul = document.getElementById('recent-list');
  ul.innerHTML = '';
  for (const q of queries) {
    const li = document.createElement('li');
    li.className = 'recent-item';
    const chip = `<span class="chip chip-${q.status.toLowerCase()}">${q.status}` +
                 ` ${q.done_count}/${q.total_count}</span>`;
    li.innerHTML = chip + ' ' + esc(q.question_text);
    li.onclick = () => openQuery(q.query_id);
    ul.appendChild(li);
  }
}

async function openQuery(queryId) {
  const res = await fetch('/api/queries/' + encodeURIComponent(queryId));
  if (!res.ok) return;
  const data = await res.json();
  renderAnswers(data.responses);          // reuse the existing card renderer
  if (data.query.status === 'RUNNING') {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(() => openQuery(queryId), 2000);   // ~2s polling
  } else {
    refreshRecent();
  }
}

async function submitQuestion() {
  const body = {
    question: questionInput.value,         // existing input element ref
    persona: personaValue(),               // existing helpers for the controls
    brand_focus: brandValue(),
    targets: selectedTargets(),            // array of names, or null
  };
  const res = await fetch('/api/ask', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res.status === 400) { showError('Please enter a question.'); return; }
  if (res.status === 429) { showError('Query limit reached — try again later.'); return; }
  const { query_id } = await res.json();
  refreshRecent();
  openQuery(query_id);                     // starts polling until DONE/FAILED
}

document.addEventListener('DOMContentLoaded', refreshRecent);   // history on load
```

> The exact element references (`questionInput`, `personaValue`, `brandValue`,
> `selectedTargets`, `renderAnswers`, `showError`) must be wired to the **existing**
> controls and the existing answer-card renderer in this file — READ the current
> `index.html` first and reuse what's there. `renderAnswers(responses)` must render each
> response's `answer_text` via the existing `renderMarkdown` inside the existing card
> markup, show its `status`/`sentiment_score`/`competitive_position`, and render
> `citations` via the existing `safeUrl` link helper. Keep `esc`, `safeUrl`,
> `renderMarkdown` intact.

(c) Add minimal CSS for `.recent-panel`, `.recent-item`, `.chip` (running/done/failed
states) in the existing `<style>` block, in the AbbVie theme (navy/magenta), consistent
with the current design. No external fonts/resources.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/web/test_index_jobs.py -v`
Expected: PASS.

- [ ] **Step 5: Manual smoke (document, do not automate)**

```bash
.venv/bin/ema --config-dir config serve --port 8123   # or a tmp config with a writable db_path
# Open http://127.0.0.1:8123 — ask a question; it appears under Recent questions as
# RUNNING then DONE; navigate to /dashboard and back; the Recent list persists and the
# result reopens on click.
```

- [ ] **Step 6: Commit**

```bash
git add ema_poc/web/static/index.html tests/web/test_index_jobs.py
git commit -m "feat: playground submit+poll UI with persistent Recent questions panel"
```

---

### Task 7: Full-suite green + docs touch-up

**Files:**
- Modify: `DEPLOY.md` (note the new `PLAYGROUND_MAX_CONCURRENT_JOBS` env, optional)

- [ ] **Step 1: Run the entire suite**

Run: `.venv/bin/python -m pytest`
Expected: all green (624 baseline minus the removed stream tests, plus the new tests).

- [ ] **Step 2: Document the new env knob**

In `DEPLOY.md`, under the "Cost guard" note, add one line:

```markdown
`PLAYGROUND_MAX_CONCURRENT_JOBS` (default 2) bounds how many background questions run at once.
```

- [ ] **Step 3: Commit**

```bash
git add DEPLOY.md
git commit -m "docs: note PLAYGROUND_MAX_CONCURRENT_JOBS env knob"
```

---

## Self-Review Notes (author)

- **Spec coverage:** schema (T1), repo incl. sweep/summaries (T2), service query_id (T3), JobManager + concurrency cap (T4), API submit/list/detail + startup sweep + auth + rate-limit (T5), UI submit/poll/history (T6), env knob + green suite (T7). All spec sections mapped.
- **Type consistency:** `create_query(..., status, target_count, started_at)`, `mark_query_done(finished_at)`, `mark_query_failed(finished_at, error_text)`, `sweep_stale_running(finished_at)->int`, `get_query->SandboxQuery|None`, `list_recent_queries->list[QuerySummary]` (fields `status,done_count,total_count`), `run_playground(..., query_id=None)`, `JobManager(submit_fn=...).submit(question,persona,brand_focus,selected_targets)->str`, `WebDeps.job_submit_fn`, `POST /api/ask`→`{query_id}` 202, `GET /api/queries`→`{queries:[...]}`, `GET /api/queries/{id}`→`{query,responses}`. Names consistent across tasks.
- **Legacy safety:** NULL status reads as DONE (T2 query + summary); additive columns nullable (T1); `query_id=None` keeps standalone `run_playground` behavior (T3).
- **Failure coverage:** per-target adapter error → job DONE (graceful); whole-job `run_playground` raise → job FAILED with `error_text` (T4); restart-interrupted RUNNING → FAILED (T2 sweep, invoked at startup in T5).
