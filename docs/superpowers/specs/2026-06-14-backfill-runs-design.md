# Backfill Runs — Design

**Date:** 2026-06-14
**Status:** Approved
**Addresses:** Stakeholder feedback #8 (Missing Operational Requirements) —
retroactively query for a missed monitoring window (e.g. after an API outage).

## Decision (from brainstorming)

A backfill run is a **normal run** with **truthful timestamps and provenance**,
simply **tagged** with the monitoring window it compensates for. Nothing about
capture is back-stamped (a backfilled response genuinely reflects today's model,
not the missed day's — falsifying its time would undermine the provenance work).

## Components

### Schema + model
- `runs` gains a nullable `backfill_for TEXT` column (additive migration; stores
  the missed date the run compensates for, e.g. `2026-06-10`).
- `Run` model gains `backfill_for: str | None = None`.

### Runs repository
- `create_run(conn, run_id, *, started_at, backfill_for=None)` — inserts the tag.
- `get_run` round-trips it (already `SELECT *` → `Run(**row)`).

### Runner
- `run(..., backfill_for: str | None = None)` threads it into `create_run` (only
  when creating a new run; a resumed run keeps its original tag).
- `RunSummary` gains `backfill_for: str | None = None` so the report can show it.

### CLI
- `ema run --backfill-for YYYY-MM-DD` — validates the date format (raises a clear
  `ConfigError`/argparse error before any LLM call on a malformed date), then runs
  normally with the tag. Credential validation unchanged (it's a real run).

### Reporting
- `format_run_report` appends a `backfill for <date>` line when set, so operator
  output makes the backfill explicit.

## Data flow

`ema run --backfill-for 2026-06-10` → runner creates the run with
`backfill_for="2026-06-10"` → responses captured at the real `timestamp_utc`
(today), scored/consensus'd normally → the run report shows the backfill tag.
The dashboard is response-level and already truthful; no change needed.

## Testing (offline)

- `create_run(..., backfill_for="2026-06-10")` persists; `get_run` returns it;
  a normal run leaves it `None`.
- additive migration adds `backfill_for` to an existing `runs` table.
- runner: `run(..., backfill_for="2026-06-10")` tags the created run and surfaces
  it on `RunSummary`; a resumed run (existing run_id) does not overwrite the tag.
- CLI: `--backfill-for 2026-06-10` passes the value through; an invalid date
  (`2026-13-40`, `notadate`) is rejected with a clear error and no run is started.
- `format_run_report` includes the backfill line when set, omits it when null.

## Out of scope (deferrable)

- **Gap detection** — automatically finding which dates have no completed run.
  Useful follow-up; for now the operator supplies the known outage date.
- Back-stamping / effective-date timeline attribution (we chose truthful times).
- Surfacing backfill runs as a distinct series in the dashboard.
