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
