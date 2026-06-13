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
