# Backfill Runs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Tag a run with the missed monitoring window it compensates for (`backfill_for`), with truthful timestamps; surface it via `ema run --backfill-for DATE` and the run report.

**Branch:** `feature/backfill-runs`. **Spec:** `docs/superpowers/specs/2026-06-14-backfill-runs-design.md`.

---

### Task 1: Schema + Run model + runs repo

**Files:** `ema_poc/db.py`, `ema_poc/models.py`, `ema_poc/repositories/runs.py`, tests `tests/test_db.py`, `tests/repositories/test_runs.py` (create if absent; else the existing runs test).

- `db.py`: add `backfill_for TEXT` (nullable) to the `runs` CREATE TABLE; add `("runs", "backfill_for", "TEXT")` to `_ADDITIVE_COLUMNS`.
- `models.py`: add `backfill_for: str | None = None` to the `Run` model.
- `runs.py`: `create_run(conn, run_id, *, started_at, backfill_for=None)` — change the INSERT to include `backfill_for`:
  ```python
  conn.execute(
      "INSERT INTO runs (run_id, started_at, status, backfill_for) VALUES (?, ?, 'RUNNING', ?)",
      (run_id, started_at, backfill_for),
  )
  ```
  (`get_run` already `SELECT *` → `Run(**dict(row))`, so it round-trips with the new model field.)
- Tests: `create_run(..., backfill_for="2026-06-10")` then `get_run` returns a Run with `backfill_for == "2026-06-10"`; `create_run` without it → `backfill_for is None`; migration test (tests/test_db.py) asserts `backfill_for` is added to an old `runs` table.

### Task 2: Runner threads backfill_for + report label

**Files:** `ema_poc/agent/runner.py`, `ema_poc/reporting.py`, tests `tests/agent/test_runner.py`, `tests/test_reporting.py` (or the existing reporting test).

- `runner.run(...)`: add a keyword param `backfill_for: str | None = None`. Pass it to `create_run(...)` in BOTH places it's called (the `run_id is None` branch and the `get_run(...) is None` branch). Do NOT pass it on the resume path where the run already exists (a resumed run keeps its original tag).
- Add `backfill_for: str | None = None` to the `RunSummary` dataclass and set it on the returned `RunSummary(...)` (use the value the run was created/tagged with — for a resumed run, read it back from `get_run(conn, run_id).backfill_for` so the summary reflects the actual stored tag; simplest: after the run, `backfill_for=get_run(conn, run_id).backfill_for`).
- `reporting.format_run_report`: when `summary.backfill_for` is set, append a line e.g. `f"  backfill for:        {summary.backfill_for}"` (place it near the top, after the run id line).
- Tests:
  - `run(..., backfill_for="2026-06-10")` with a fake adapter + one approved question → the created run has `backfill_for == "2026-06-10"` (assert via get_run) and `summary.backfill_for == "2026-06-10"`.
  - a normal run → `summary.backfill_for is None` and the report omits the backfill line.
  - `format_run_report` with a summary having `backfill_for="2026-06-10"` includes "backfill for" and the date.

### Task 3: CLI `ema run --backfill-for` with date validation

**Files:** `ema_poc/cli.py`, tests `tests/test_cli.py`.

- READ the `run` subparser in `_parse_args` and the `run` branch in `main` (how it builds adapters and calls `deps.run(...)`).
- `_parse_args`: add `p_run.add_argument("--backfill-for", dest="backfill_for", default=None, help="Tag this run as a backfill for a missed date (YYYY-MM-DD)")`.
- In `main`, in the `run` branch: if `args.backfill_for` is set, VALIDATE it is a real ISO date `YYYY-MM-DD` using `datetime.date.fromisoformat(args.backfill_for)` inside a try/except; on failure raise a clear error (mirror how the CLI surfaces config errors — e.g. raise `ConfigError(f"Invalid --backfill-for date: {args.backfill_for!r} (expected YYYY-MM-DD)")` or print to stderr and return a non-zero exit). Do the validation BEFORE building adapters / making any LLM call. Pass `backfill_for=args.backfill_for` into the `deps.run(...)` call.
- Tests (fake Deps, reuse the cli-test helpers):
  - `main(["run", "--backfill-for", "2026-06-10"], deps=...)` → `deps.run` receives `backfill_for="2026-06-10"` (capture kwargs on the fake run).
  - `main(["run", "--backfill-for", "not-a-date"], deps=...)` → raises the clear error (or returns non-zero) and `deps.run` is NOT called (no LLM work). Assert the run fake was not invoked.
  - a normal `main(["run"], ...)` passes `backfill_for=None`.

---

## Self-Review Notes (author)
- Truthful timestamps preserved (no back-stamping); only run-level `backfill_for` tag added.
- Additive migration for `runs.backfill_for`.
- Resumed runs keep their original tag (don't overwrite); summary reflects the stored tag via get_run.
- Date validated before any LLM call (fail fast).
- Type consistency: `create_run(..., backfill_for=None)`; `run(..., backfill_for=None)`; `RunSummary.backfill_for`; `Run.backfill_for`.
