"""Append-only audit log (spec §7; BR-010, SE-003).

Insert-only by design: this module deliberately exposes no update or delete
helpers. The audit trail must be immutable for compliance review.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    role: str | None = None,
    question_id: str | None = None,
    llm_target: str | None = None,
    http_status: int | None = None,
    detail: str | None = None,
    timestamp: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log
            (timestamp, event_type, role, question_id, llm_target, http_status, detail)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            timestamp or _now_iso(),
            event_type,
            role,
            question_id,
            llm_target,
            http_status,
            detail,
        ),
    )
    conn.commit()


def list_events(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY id ASC"
    ).fetchall()
    return [dict(r) for r in rows]
