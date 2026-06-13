"""Question Repository: versioned, queryable question store (FR-1).

Every mutation writes a new version row; "current" is the highest-version row
per question_id. History is never destroyed (FR-103). Functions accept an
injectable `now` ISO-8601 UTC timestamp for deterministic tests.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from ema_poc.models import Question


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def _question_from_row(row: sqlite3.Row) -> Question:
    return Question(**dict(row))


def _insert_version(conn: sqlite3.Connection, q: Question) -> None:
    conn.execute(
        """
        INSERT INTO questions (
            question_id, version, question_text, persona, therapeutic_area,
            brand_focus, domain, active, approval_status, approver_name,
            created_at, updated_at, deleted_at, delete_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            q.question_id,
            q.version,
            q.question_text,
            q.persona.value,
            q.therapeutic_area,
            q.brand_focus,
            q.domain.value,
            int(q.active),
            q.approval_status.value,
            q.approver_name,
            _iso(q.created_at),
            _iso(q.updated_at),
            _iso(q.deleted_at),
            q.delete_reason,
        ),
    )
    conn.commit()


def get_version(
    conn: sqlite3.Connection, question_id: str, version: int
) -> Question | None:
    row = conn.execute(
        "SELECT * FROM questions WHERE question_id = ? AND version = ?",
        (question_id, version),
    ).fetchone()
    return _question_from_row(row) if row else None


def get_current(conn: sqlite3.Connection, question_id: str) -> Question | None:
    row = conn.execute(
        "SELECT * FROM questions WHERE question_id = ? ORDER BY version DESC LIMIT 1",
        (question_id,),
    ).fetchone()
    return _question_from_row(row) if row else None


def add_question(
    conn: sqlite3.Connection,
    *,
    question_id: str,
    question_text: str,
    persona: str,
    domain: str,
    therapeutic_area: str | None = None,
    brand_focus: str | None = None,
    now: str | None = None,
) -> Question:
    if get_current(conn, question_id) is not None:
        raise ValueError(f"Question already exists: {question_id}")
    now = now or _now_iso()
    q = Question(
        question_id=question_id,
        version=1,
        question_text=question_text,
        persona=persona,
        domain=domain,
        therapeutic_area=therapeutic_area,
        brand_focus=brand_focus,
        created_at=now,
        updated_at=now,
    )
    _insert_version(conn, q)
    return get_version(conn, question_id, 1)
