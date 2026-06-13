"""Response Repository — immutable response writes + resumability (FR-3, FR-504).

This phase provides the WRITE path and the resumability query only; the rich
query-by-any-combination / export / diff surface is Phase 4."""

from __future__ import annotations

import sqlite3
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
