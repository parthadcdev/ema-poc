"""Storage for frozen v0 drift baselines (one per question/LLM pair)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BaselineRow:
    question_id: str
    llm_name: str
    response_id: str
    competitive_position: str | None
    frozen_at: str


def set_baseline(conn, *, question_id, llm_name, response_id, now,
                 competitive_position=None, commit=True) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO drift_baselines
           (question_id, llm_name, response_id, competitive_position, frozen_at)
           VALUES (?, ?, ?, ?, ?)""",
        (question_id, llm_name, response_id, competitive_position, now),
    )
    if commit:
        conn.commit()


def get_baseline(conn, question_id, llm_name) -> BaselineRow | None:
    row = conn.execute(
        """SELECT question_id, llm_name, response_id, competitive_position, frozen_at
           FROM drift_baselines
           WHERE question_id = ? AND llm_name = ?""",
        (question_id, llm_name),
    ).fetchone()
    return BaselineRow(**dict(row)) if row else None


def list_baselines(conn) -> list[BaselineRow]:
    rows = conn.execute(
        "SELECT question_id, llm_name, response_id, competitive_position, frozen_at "
        "FROM drift_baselines "
        "ORDER BY question_id, llm_name"
    ).fetchall()
    return [BaselineRow(**dict(r)) for r in rows]
