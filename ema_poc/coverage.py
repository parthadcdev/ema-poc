"""Question effectiveness / coverage analysis (FR-107 expanded).

Flags questions whose target brand is chronically NOT_MENTIONED across scored
responses — low-value questions Medical Affairs should revise."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class QuestionEffectiveness:
    question_id: str
    question_text: str
    brand_focus: str | None
    total_scored: int
    not_mentioned: int
    not_mentioned_rate: float
    low_value: bool


def question_effectiveness(
    conn: sqlite3.Connection,
    *,
    min_responses: int = 3,
    not_mentioned_threshold: float = 0.8,
) -> list[QuestionEffectiveness]:
    """For each question with at least one SCORED response (competitive_position
    not null), compute how often its target brand was NOT_MENTIONED. A question
    is low_value when it has >= min_responses scored responses AND the
    NOT_MENTIONED rate is >= not_mentioned_threshold. Sorted low-value first,
    then by not_mentioned_rate desc."""
    rows = conn.execute(
        """
        SELECT question_id,
               MAX(question_text) AS question_text,
               MAX(brand_focus)   AS brand_focus,
               COUNT(*)           AS total_scored,
               SUM(CASE WHEN competitive_position = 'NOT_MENTIONED' THEN 1 ELSE 0 END) AS not_mentioned
        FROM responses
        WHERE competitive_position IS NOT NULL
        GROUP BY question_id
        """
    ).fetchall()
    out: list[QuestionEffectiveness] = []
    for r in rows:
        total = r["total_scored"]
        nm = r["not_mentioned"] or 0
        rate = nm / total if total else 0.0
        low = total >= min_responses and rate >= not_mentioned_threshold
        out.append(QuestionEffectiveness(
            question_id=r["question_id"], question_text=r["question_text"],
            brand_focus=r["brand_focus"], total_scored=total,
            not_mentioned=nm, not_mentioned_rate=rate, low_value=low,
        ))
    out.sort(key=lambda q: (not q.low_value, -q.not_mentioned_rate))
    return out


def format_coverage_report(items: list[QuestionEffectiveness]) -> str:
    if not items:
        return "No scored responses yet — run scoring first."
    flagged = [q for q in items if q.low_value]
    lines = [f"Question effectiveness ({len(items)} scored questions, {len(flagged)} flagged low-value):", ""]
    for q in items:
        mark = "LOW-VALUE" if q.low_value else "ok"
        lines.append(
            f"[{mark}] {q.question_id} ({q.brand_focus or 'n/a'}): "
            f"{q.not_mentioned}/{q.total_scored} NOT_MENTIONED "
            f"({q.not_mentioned_rate:.0%}) — {q.question_text[:60]}"
        )
    return "\n".join(lines)
