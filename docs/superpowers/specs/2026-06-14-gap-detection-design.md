# Run Gap Detection — Design

**Date:** 2026-06-14
**Status:** Approved
**Addresses:** Operational follow-up to backfill (#8) — auto-find dates with no
completed run so operators know which windows to backfill.

## Decision (from brainstorming)

A date is **covered** when a COMPLETED run exists for it. A backfill run covers
its `backfill_for` date (not its actual run date). BUDGET_EXCEEDED / FAILED /
RUNNING runs contribute no coverage — a partial/failed day is still a gap.

## Components

### `ema_poc/run_gaps.py`
- `find_run_gaps(conn, *, start: str, end: str) -> list[str]`:
  - Build the **coverage set**: for each run with `status == "COMPLETED"`, add
    `run.backfill_for` if set, else `run.started_at.date().isoformat()`
    (`started_at` is a `datetime` on the `Run` model).
  - Return every `YYYY-MM-DD` date in `[start, end]` inclusive that is NOT in the
    coverage set, in ascending order.
- `format_gaps_report(gaps: list[str], start: str, end: str) -> str`:
  - If no gaps: `"No run gaps between <start> and <end>."`.
  - Else: a header (`"<n> uncovered date(s) between <start> and <end>:"`), one line
    per gap date, and a hint: `"Backfill each with: ema run --backfill-for <date>"`.

### Runs repository
- Add `list_runs(conn) -> list[Run]` (`SELECT * FROM runs ORDER BY started_at` →
  `Run(**dict(row))`). Generally useful; consumed by `find_run_gaps`.

### CLI
- **`ema run-gaps --since YYYY-MM-DD [--until YYYY-MM-DD]`** — `--since` required;
  `--until` defaults to today (UTC, `date.today().isoformat()` via an injectable
  now). Both validated with `date.fromisoformat` (reuse the backfill validation
  pattern; raise `ConfigError` on a bad date before any DB work). Local op — NOT
  in the credential-validation set. Prints `format_gaps_report(...)`.

## Data flow
`ema run-gaps --since 2026-06-01` → validate dates → `find_run_gaps(conn,
start=since, end=until)` → list uncovered dates → print report with backfill hint.

## Testing (offline)
- Seed runs: a COMPLETED run started on day A; a COMPLETED run with
  `backfill_for=B`; a BUDGET_EXCEEDED run started on day C. `find_run_gaps(conn,
  start=A, end=D)` → gaps == [C, D] (A and B covered; C partial → gap; D never
  run). Ascending order.
- All-covered window → []; a window before any run → all dates.
- `format_gaps_report`: empty → the "No run gaps" line; non-empty → count header +
  each date + the backfill hint.
- CLI: validates `--since` (bad date → ConfigError, no DB work); `--until`
  defaults to the injected today; prints the report; no credential validation.

## Out of scope (deferrable)
- Auto-triggering backfills.
- A distinct "partial (BUDGET_EXCEEDED)" category in the output (treated as a gap).
- Coverage at finer-than-daily granularity.
