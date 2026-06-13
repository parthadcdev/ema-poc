"""Response Repository — immutable response writes, resumability, and the read
surface: query-by-any-combination, pagination, and change detection
(FR-3, FR-303/304/306/307, FR-504). CSV/JSON export lives in ema_poc/export.py
(FR-305)."""

from __future__ import annotations

import difflib
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from ema_poc.adapters.base import LLMResponse
from ema_poc.models import Question, Response


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def build_response(
    *,
    run_id: str,
    question: Question,
    adapter,
    llm_response: LLMResponse,
    now: str,
    response_id: str,
) -> Response:
    """Construct a Response row from a question, the adapter that answered, and
    the normalized LLMResponse. sentiment_score/competitive_position stay null
    (populated by the Phase 5 scoring pass)."""
    return Response(
        response_id=response_id,
        run_id=run_id,
        timestamp_utc=now,
        llm_name=adapter.name,
        llm_model_version=adapter.model_version,
        persona=question.persona,
        question_id=question.question_id,
        question_text=question.question_text,
        therapeutic_area=question.therapeutic_area,
        brand_focus=question.brand_focus,
        domain=question.domain,
        response_text=llm_response.text,
        response_tokens=llm_response.completion_tokens,
        finish_reason=llm_response.finish_reason,
        status=llm_response.status,
        alert_triggered=False,
        created_at=now,
    )


def save_response(conn: sqlite3.Connection, response: Response) -> None:
    conn.execute(
        """
        INSERT INTO responses (
            response_id, run_id, timestamp_utc, llm_name, llm_model_version,
            persona, question_id, question_text, therapeutic_area, brand_focus,
            domain, response_text, response_tokens, finish_reason, status,
            sentiment_score, competitive_position, alert_triggered, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            response.response_id,
            response.run_id,
            _iso(response.timestamp_utc),
            response.llm_name,
            response.llm_model_version,
            response.persona.value,
            response.question_id,
            response.question_text,
            response.therapeutic_area,
            response.brand_focus,
            response.domain.value,
            response.response_text,
            response.response_tokens,
            response.finish_reason,
            response.status.value,
            response.sentiment_score,
            response.competitive_position.value
            if response.competitive_position is not None
            else None,
            int(response.alert_triggered),
            _iso(response.created_at),
        ),
    )
    conn.commit()


def completed_keys(conn: sqlite3.Connection, run_id: str) -> set[tuple[str, str]]:
    """(question_id, llm_name) pairs already captured for this run (status !=
    FAILED). Used to resume a run without re-submitting completed work."""
    rows = conn.execute(
        "SELECT DISTINCT question_id, llm_name FROM responses "
        "WHERE run_id = ? AND status != 'FAILED'",
        (run_id,),
    ).fetchall()
    return {(r["question_id"], r["llm_name"]) for r in rows}


def _enum_value(x):
    return x.value if hasattr(x, "value") else x


def _response_filters(
    *,
    llm=None,
    persona=None,
    therapeutic_area: str | None = None,
    brand_focus: str | None = None,
    domain=None,
    date_from: str | None = None,
    date_to: str | None = None,
    sentiment_min: float | None = None,
    sentiment_max: float | None = None,
    alert_triggered: bool | None = None,
    status=None,
) -> tuple[str, list]:
    """Build a parameterized WHERE clause (FR-303). Returns (clause, params)
    where clause is '' or ' WHERE ...'."""
    where: list[str] = []
    params: list = []
    if llm is not None:
        where.append("llm_name = ?")
        params.append(llm)
    if persona is not None:
        where.append("persona = ?")
        params.append(_enum_value(persona))
    if therapeutic_area is not None:
        where.append("therapeutic_area = ?")
        params.append(therapeutic_area)
    if brand_focus is not None:
        where.append("brand_focus = ?")
        params.append(brand_focus)
    if domain is not None:
        where.append("domain = ?")
        params.append(_enum_value(domain))
    if date_from is not None:
        where.append("timestamp_utc >= ?")
        params.append(date_from)
    if date_to is not None:
        where.append("timestamp_utc <= ?")
        params.append(date_to)
    if sentiment_min is not None:
        where.append("sentiment_score >= ?")
        params.append(sentiment_min)
    if sentiment_max is not None:
        where.append("sentiment_score <= ?")
        params.append(sentiment_max)
    if alert_triggered is not None:
        where.append("alert_triggered = ?")
        params.append(int(alert_triggered))
    if status is not None:
        where.append("status = ?")
        params.append(_enum_value(status))
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params


def query_responses(
    conn: sqlite3.Connection,
    *,
    llm=None,
    persona=None,
    therapeutic_area: str | None = None,
    brand_focus: str | None = None,
    domain=None,
    date_from: str | None = None,
    date_to: str | None = None,
    sentiment_min: float | None = None,
    sentiment_max: float | None = None,
    alert_triggered: bool | None = None,
    status=None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Response]:
    """Query responses by any combination of filters, ordered by timestamp then
    id for stable pagination (FR-303, FR-307)."""
    clause, params = _response_filters(
        llm=llm, persona=persona, therapeutic_area=therapeutic_area,
        brand_focus=brand_focus, domain=domain, date_from=date_from,
        date_to=date_to, sentiment_min=sentiment_min, sentiment_max=sentiment_max,
        alert_triggered=alert_triggered, status=status,
    )
    sql = (
        f"SELECT * FROM responses{clause} "
        "ORDER BY timestamp_utc ASC, response_id ASC"
    )
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = params + [limit, offset]
    rows = conn.execute(sql, params).fetchall()
    return [Response(**dict(r)) for r in rows]


def count_responses(conn: sqlite3.Connection, **filters) -> int:
    """Count responses matching the same filters as query_responses (FR-307)."""
    clause, params = _response_filters(**filters)
    row = conn.execute(
        f"SELECT COUNT(*) AS c FROM responses{clause}", params
    ).fetchone()
    return row["c"]


@dataclass
class ResponseChange:
    """Change detection result for a (question_id, llm_name) pair (FR-306,
    BR-004). `changed` is False when there is no previous response; both
    `previous_text` and `current_text` are None when the pair has no responses
    at all."""

    question_id: str
    llm_name: str
    changed: bool
    previous_text: str | None
    current_text: str | None
    diff: str


def latest_responses(
    conn: sqlite3.Connection, question_id: str, llm_name: str, *, limit: int = 2
) -> list[Response]:
    """The most recent responses for a question/LLM pair, newest first."""
    rows = conn.execute(
        "SELECT * FROM responses WHERE question_id = ? AND llm_name = ? "
        "ORDER BY timestamp_utc DESC, response_id DESC LIMIT ?",
        (question_id, llm_name, limit),
    ).fetchall()
    return [Response(**dict(r)) for r in rows]


def detect_change(
    conn: sqlite3.Connection, question_id: str, llm_name: str
) -> ResponseChange:
    """Compare the current and previous response for a question/LLM pair and
    return a ResponseChange with a unified diff when the text differs."""
    recent = latest_responses(conn, question_id, llm_name, limit=2)
    current = recent[0] if recent else None
    previous = recent[1] if len(recent) > 1 else None
    current_text = current.response_text if current else None
    previous_text = previous.response_text if previous else None

    if previous is None:
        return ResponseChange(
            question_id, llm_name, False, None, current_text, ""
        )

    changed = current_text != previous_text
    diff = ""
    if changed:
        diff = "".join(
            difflib.unified_diff(
                previous_text.splitlines(keepends=True),
                current_text.splitlines(keepends=True),
                fromfile="previous",
                tofile="current",
            )
        )
    return ResponseChange(
        question_id, llm_name, changed, previous_text, current_text, diff
    )
