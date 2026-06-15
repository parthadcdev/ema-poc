# Background Playground Jobs + Question History — Design

**Date:** 2026-06-15
**Status:** Approved
**Goal:** Make a playground question run as a server-side background job whose
results persist and stay retrievable, so navigating away, asking other questions,
reloading, or even a redeploy never loses the data.

## Problem

Today `GET /api/ask/stream` runs the question inside an SSE generator tied to the
HTTP request. Results ARE persisted to the `sandbox_*` tables as each target
completes, but:
- the run is welded to the live connection — leaving mid-answer can abort it;
- there is no UI or API to retrieve a past query's results — navigating away
  blanks the on-screen answer cards.

## Decisions (confirmed)

- **Full background jobs + live status** via **DB-backed jobs + polling** (not
  in-memory jobs, not SSE). The sandbox DB (now on the persistent Fly volume) is
  the source of truth, so jobs survive navigation, reload, and restart.
- **Drop SSE.** Replace EventSource with `POST /api/ask` (submit) + ~2 s polling.
- **Shared history.** One recent-questions list for the app (single login).

## Architecture

```
POST /api/ask ──> JobManager.submit() ──> creates sandbox_queries row (RUNNING)
                                       └─> background thread: run_playground(query_id)
                                            persists responses/scores as targets finish
                                            └─> mark query DONE (or FAILED on error)
UI polls GET /api/queries/{id} (~2s) until status != RUNNING
UI loads GET /api/queries on open  ──> Recent-questions panel (persists across nav)
App startup ──> sweep_stale_running(): any RUNNING row -> FAILED ("interrupted")
```

## Components

### 1. Schema (`ema_poc/db.py`)
Additive columns on `sandbox_queries` (via `_migrate_additive_columns` /
`_ADDITIVE_COLUMNS`, idempotent — matches the existing pattern):
- `status TEXT` — `RUNNING` | `DONE` | `FAILED`. **Legacy rows have NULL → read as
  `DONE`** (they predate jobs and were complete).
- `target_count INTEGER` — number of targets expected for the run.
- `started_at TEXT`, `finished_at TEXT` — ISO-8601 UTC.
- `error_text TEXT` — whole-job failure message (NULL otherwise).

`connect()` gains `PRAGMA busy_timeout = 5000` so a concurrent job-write and a
polling read wait briefly for the lock instead of raising "database is locked".
(No WAL change — busy_timeout is the minimal fix for the low concurrency here.)

### 2. Repository (`ema_poc/repositories/sandbox.py`)
- Extend `SandboxQuery` dataclass with `status`, `target_count`, `started_at`,
  `finished_at`, `error_text`.
- `create_query(...)` gains `status="RUNNING"`, `target_count`, `started_at` (keep
  `timestamp_utc` as the submit time).
- `mark_query_done(conn, query_id, *, finished_at)` → set status DONE + finished_at.
- `mark_query_failed(conn, query_id, *, finished_at, error_text)` → status FAILED.
- `get_query(conn, query_id) -> SandboxQuery | None`.
- `sweep_stale_running(conn, *, finished_at) -> int` — set every `status='RUNNING'`
  row to FAILED with `error_text="interrupted by restart"`; returns the count.
  Correct for a single-instance app: at process start no job thread is alive, so
  any RUNNING row is stale.
- Extend `list_recent_queries(...)` to return, per query: the status fields plus
  `done_count` (responses with a terminal status) and `total_count`
  (`COALESCE(target_count, count(responses))`). Reads treat NULL status as DONE.

### 3. Service (`ema_poc/playground/service.py`)
`run_playground(...)` gains an optional `query_id` param. When provided, it skips
`S.create_query` and uses the caller's id (the JobManager creates the row in
`submit` so the API can return the id immediately and the query shows as RUNNING).
When `query_id is None` it creates one as today (standalone/back-compat). The
`{"event": "query", ...}` yield is preserved.

### 4. Job manager (`ema_poc/playground/jobs.py`, new)
```python
class JobManager:
    def __init__(self, *, db_path, build_adapters_for, scoring_client, scorer,
                 config, id_factory, now_factory, max_concurrent, submit_fn=None):
        # submit_fn(callable) -> schedules work; default = ThreadPoolExecutor(
        #   max_workers=max_concurrent).submit. Tests inject an inline runner.
    def submit(self, *, question, persona, brand_focus, selected_targets) -> str:
        # build adapters for selected_targets; target_count = len(adapters)
        # open a short-lived conn: create_query(status=RUNNING, target_count, started_at)
        # schedule _run(query_id, adapters, ...); return query_id
    def _run(self, query_id, adapters, *, question, persona, brand_focus):
        # conn = connect(db_path); init_schema(conn)
        # try: drain run_playground(conn, query_id=query_id, adapters=adapters, ...)
        #      mark_query_done
        # except Exception as e: mark_query_failed(error_text=str(e))
        # finally: conn.close()
```
- Own DB connection per background thread (sqlite `check_same_thread` default; no
  cross-thread connection sharing).
- Concurrency cap = `max_concurrent` (env `PLAYGROUND_MAX_CONCURRENT_JOBS`, default
  **2**) — guards the 512 MB machine and cost; extra submits queue on the pool.
- Adapters built in `submit` (fail fast on a bad target selection; pass the built
  list into the thread).

### 5. API (`ema_poc/web/app.py`)
Remove `GET /api/ask/stream`. Add (all under existing auth):
- `POST /api/ask` — JSON body `{question, persona?, brand_focus?, targets?}`.
  Validates non-empty question (400) and the per-IP hourly cap (429, before
  submit). Returns `{"query_id": "..."}` (202).
- `GET /api/queries` — `{"queries": [{query_id, question_text, persona,
  brand_focus, timestamp_utc, status, done_count, total_count}]}` (recent first).
- `GET /api/queries/{query_id}` — `{"query": {...status fields...},
  "responses": [ {llm_name, grounded, status, answer_text, tokens, finish_reason,
  sentiment_score, competitive_position, scoring_rationale, citations:[...]} ]}`.
  404 if unknown.
- On app startup (FastAPI startup hook in `create_app`): open a conn, `init_schema`,
  `sweep_stale_running`. Wrap the `JobManager` into `create_app`, built from
  `WebDeps` (config, build_adapters_for, scoring_client, scorer, db_path, env for
  the concurrency cap). `WebDeps` gains nothing required beyond what exists; the
  manager reads `max_concurrent` from `env` (default 2). Tests inject a manager
  with an inline `submit_fn` so submit completes synchronously.

### 6. UI (`ema_poc/web/static/index.html`)
- Replace the EventSource flow with: submit via `fetch('/api/ask', {method:POST})`
  → get `query_id` → poll `GET /api/queries/{id}` every ~2 s, re-rendering the
  answer cards from the response list; stop when `status` is DONE/FAILED.
- Add a **Recent questions** panel populated from `GET /api/queries` on page load
  and refreshed after each submit/poll. Each entry shows the question, persona,
  and a status chip (Running / Done / Failed) with done/total. Clicking an entry
  loads that query's detail into the answer area — so results persist across
  navigation, reload, and asking new questions.
- Keep `renderMarkdown`, `esc`, `safeUrl`; keep the app bar + AbbVie theme.
  Self-contained (no external resources).

## Error handling
- Empty question → 400; over per-IP cap → 429 (before any work).
- Per-target failure → persisted as a FAILED `sandbox_responses` row (existing
  behavior) and shown in detail; the job still completes.
- Whole-job exception → `mark_query_failed` with `error_text`; detail surfaces it.
- Process restart mid-run → startup `sweep_stale_running` marks RUNNING → FAILED
  "interrupted by restart".
- Unknown `query_id` → 404.

## Testing (offline, fakes — no SDKs/network, per project norm)
- **jobs** (`tests/playground/test_jobs.py`): with an inline `submit_fn` and fake
  adapters/scorer, `submit` creates a RUNNING row then completes → DONE with
  responses persisted; an adapter/scorer-raising-everything path → job still DONE
  with FAILED responses; a `run_playground` that raises → job FAILED + error_text;
  concurrency cap passed through.
- **repo** (`tests/repositories/test_sandbox.py`): create_query writes status/
  target_count/started_at; mark_done/mark_failed transition; get_query; sweep marks
  RUNNING→FAILED and returns count; list_recent_queries returns status + done/total
  and reads NULL status as DONE.
- **db** (`tests/test_*` as fits): additive columns present after `init_schema` on a
  pre-existing DB; `busy_timeout` set on connect.
- **app** (`tests/web/test_app.py` + replace `tests/web/test_stream.py` with
  `tests/web/test_jobs_api.py`): `POST /api/ask` returns a query_id and the query is
  listed; with an inline manager the run completes → detail shows responses/scores;
  empty question → 400; cap=1 second submit → 429; `GET /api/queries/{unknown}` →
  404; auth still enforced when `APP_PASSWORD` set; startup sweep runs.
- **index** (`tests/web/test_app.py` structural): no `EventSource`; uses
  `/api/ask` + polling of `/api/queries/`; a recent-questions container is present;
  `renderMarkdown` still used; self-contained.

## Out of scope (deferrable)
- Cross-device/per-user history, auth-per-user.
- Cancel/delete a running job.
- WebSocket/SSE live push (polling is sufficient at this scale).
- Showing sandbox/playground queries inside the monitoring dashboard (separate).
