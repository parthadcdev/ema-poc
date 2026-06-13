"""Scores repository — append-only, versioned scoring records (FR-304/407)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from ema_poc.models import Response, Score


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def _score_from_row(row: sqlite3.Row) -> Score:
    data = dict(row)
    data["brand_mentions"] = json.loads(data["brand_mentions"]) if data["brand_mentions"] else []
    data["key_claims"] = json.loads(data["key_claims"]) if data["key_claims"] else []
    data["human_override"] = bool(data["human_override"])
    return Score(**data)


def save_score(conn: sqlite3.Connection, score: Score) -> None:
    conn.execute(
        """
        INSERT INTO scores (
            score_id, response_id, version, sentiment_score, competitive_position,
            brand_mentions, key_claims, scoring_rationale, scoring_model,
            human_override, override_rationale, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            score.score_id,
            score.response_id,
            score.version,
            score.sentiment_score,
            score.competitive_position.value,
            json.dumps(score.brand_mentions),
            json.dumps(score.key_claims),
            score.scoring_rationale,
            score.scoring_model,
            int(score.human_override),
            score.override_rationale,
            _iso(score.created_at),
        ),
    )
    conn.commit()


def latest_score(conn: sqlite3.Connection, response_id: str) -> Score | None:
    row = conn.execute(
        "SELECT * FROM scores WHERE response_id = ? ORDER BY version DESC LIMIT 1",
        (response_id,),
    ).fetchone()
    return _score_from_row(row) if row else None


def next_score_version(conn: sqlite3.Connection, response_id: str) -> int:
    row = conn.execute(
        "SELECT MAX(version) AS v FROM scores WHERE response_id = ?", (response_id,)
    ).fetchone()
    return (row["v"] or 0) + 1


def unscored_success_responses(conn: sqlite3.Connection) -> list[Response]:
    """SUCCESS responses that have no score row yet (FR-401)."""
    rows = conn.execute(
        """
        SELECT r.* FROM responses r
        LEFT JOIN scores s ON r.response_id = s.response_id
        WHERE r.status = 'SUCCESS' AND s.score_id IS NULL
        ORDER BY r.timestamp_utc ASC, r.response_id ASC
        """
    ).fetchall()
    return [Response(**dict(r)) for r in rows]
