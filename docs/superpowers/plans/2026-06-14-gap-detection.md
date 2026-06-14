# Run Gap Detection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** `ema run-gaps --since DATE [--until DATE]` lists dates with no COMPLETED run (backfill runs credit their target date), so operators know what to backfill.

**Branch:** `feature/gap-detection`. **Spec:** `docs/superpowers/specs/2026-06-14-gap-detection-design.md`.

---

### Task 1: `list_runs` + `find_run_gaps` + report

**Files:** `ema_poc/repositories/runs.py`, `ema_poc/run_gaps.py` (create), `tests/repositories/test_runs.py`, `tests/test_run_gaps.py` (create).

- `runs.py`: add `list_runs(conn) -> list[Run]`:
```python
def list_runs(conn) -> list[Run]:
    rows = conn.execute("SELECT * FROM runs ORDER BY started_at").fetchall()
    return [Run(**dict(r)) for r in rows]
```
- `ema_poc/run_gaps.py`:
```python
"""Find dates in a window with no COMPLETED run (operators backfill these)."""

from __future__ import annotations

from datetime import date, timedelta

from ema_poc.repositories.runs import list_runs


def _date_range(start: str, end: str) -> list[str]:
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    out = []
    d = d0
    while d <= d1:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def find_run_gaps(conn, *, start: str, end: str) -> list[str]:
    covered = set()
    for run in list_runs(conn):
        if run.status != "COMPLETED":
            continue
        if run.backfill_for:
            covered.add(run.backfill_for)
        else:
            covered.add(run.started_at.date().isoformat())  # started_at is a datetime
    return [d for d in _date_range(start, end) if d not in covered]


def format_gaps_report(gaps: list[str], start: str, end: str) -> str:
    if not gaps:
        return f"No run gaps between {start} and {end}."
    lines = [f"{len(gaps)} uncovered date(s) between {start} and {end}:"]
    lines += [f"  {d}" for d in gaps]
    lines.append("Backfill each with: ema run --backfill-for <date>")
    return "\n".join(lines)
```
  (Confirm `Run.started_at` is a `datetime` — it is per the model; `.date().isoformat()` gives YYYY-MM-DD. If a run row somehow has a string started_at, guard with `str(run.started_at)[:10]` — but the model parses it to datetime, so `.date()` is correct.)
- Tests:
  - `list_runs`: after creating 2 runs, returns both ordered by started_at.
  - `find_run_gaps`: seed (via create_run + finish_run to set status/dates, OR direct INSERTs) a COMPLETED run started 2026-06-01; a COMPLETED run with backfill_for="2026-06-02" (started later); a BUDGET_EXCEEDED run started 2026-06-03. `find_run_gaps(conn, start="2026-06-01", end="2026-06-04")` → `["2026-06-03", "2026-06-04"]` (01 and 02 covered; 03 partial→gap; 04 never run). Ascending.
    - To set status/dates precisely, the simplest path is direct `conn.execute("INSERT INTO runs (run_id, started_at, status, backfill_for) VALUES (?,?,?,?)", ...)` with ISO started_at strings, then commit — avoids the runner. (Run(**row) parses started_at to datetime on read.)
  - all-covered window → []; window entirely before any run → every date returned.
  - `format_gaps_report`: empty list → "No run gaps between ..."; non-empty → count header + each date + the "Backfill each with" hint.

Commit:
```bash
git add ema_poc/repositories/runs.py ema_poc/run_gaps.py tests/repositories/test_runs.py tests/test_run_gaps.py
git commit -m "feat: find_run_gaps + list_runs (COMPLETED runs cover; backfill credits target date)"
```

### Task 2: CLI `ema run-gaps`

**Files:** `ema_poc/cli.py`, `tests/test_cli.py`.

- READ cli.py (Deps, default_deps, _open_db, _parse_args, main, the `from datetime import date` + `ConfigError` imports already present from backfill work).
- `Deps`: add `find_run_gaps: Callable | None = None`. Wire in `default_deps()` (`from ema_poc.run_gaps import find_run_gaps`).
- `_parse_args`:
```python
    p_gap = sub.add_parser("run-gaps", help="List dates with no completed run (to backfill)")
    p_gap.add_argument("--since", required=True, help="Window start (YYYY-MM-DD)")
    p_gap.add_argument("--until", default=None, help="Window end (YYYY-MM-DD, default today)")
```
- `main` branch (NOT credential-gated):
```python
    if args.command == "run-gaps":
        from datetime import date, timezone
        from ema_poc.run_gaps import format_gaps_report
        until = args.until or datetime.now(timezone.utc).date().isoformat()
        for label, value in (("--since", args.since), ("--until", until)):
            try:
                date.fromisoformat(value)
            except ValueError:
                raise ConfigError(f"Invalid {label} date: {value!r} (expected YYYY-MM-DD)")
        conn = _open_db(deps, config)
        gaps = deps.find_run_gaps(conn, start=args.since, end=until)
        deps.out(format_gaps_report(gaps, args.since, until))
        return 0
```
  (Match the actual `_open_db(deps, config)` usage; `datetime` is already imported in cli.py or import it. Validate dates BEFORE opening the DB.)
- Tests (fake Deps): 
  - `main(["run-gaps","--since","2026-06-01","--until","2026-06-03"], deps=...)` with `find_run_gaps=lambda conn, **k: ["2026-06-02"]` + out recorder → returns 0; output contains "2026-06-02" and the backfill hint; `find_run_gaps` received start/end.
  - invalid `--since` (`"nope"`) → raises ConfigError, `find_run_gaps` NOT called.
  - `--until` omitted → defaults to today (assert find_run_gaps received an `end` equal to today's date, or just that it was called with a valid ISO end — inject/monkeypatch is overkill; assert end matches `date.today().isoformat()` OR that it's a valid YYYY-MM-DD of length 10).
  - no credential validation for this command.

Run FULL suite until green after each task. Commit:
```bash
git add ema_poc/cli.py tests/test_cli.py
git commit -m "feat: ema run-gaps command (list uncovered dates to backfill)"
```

---

## Self-Review Notes (author)
- COMPLETED covers; backfill credits backfill_for; partial/failed = gap.
- started_at is a datetime → `.date().isoformat()`.
- Dates validated before DB work; local op, no credentials.
- list_runs added to runs repo (reused); find_run_gaps + report in run_gaps.py.
