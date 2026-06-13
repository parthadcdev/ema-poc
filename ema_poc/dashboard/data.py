"""Query + aggregate repository data for the dashboard (FR-602)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass
class DashboardData:
    rows: list[dict] = field(default_factory=list)
    sentiment_by_llm: dict = field(default_factory=dict)
    sentiment_by_therapy: dict = field(default_factory=dict)
    position_by_llm: dict = field(default_factory=dict)
    volume_by_date: dict = field(default_factory=dict)
    alerts: list[dict] = field(default_factory=list)
    total_responses: int = 0
    total_alerts: int = 0


def _alert_reasons(conn: sqlite3.Connection) -> dict[str, str]:
    """Map response_id -> alert reason. If a response has multiple alert rows,
    the last one from the join wins (POC responses trigger at most one alert)."""
    rows = conn.execute(
        """
        SELECT r.response_id AS response_id, a.reason AS reason
        FROM alerts a
        JOIN scores s ON a.score_id = s.score_id
        JOIN responses r ON s.response_id = r.response_id
        """
    ).fetchall()
    return {r["response_id"]: r["reason"] for r in rows}


def collect_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT r.response_id, r.llm_name, r.persona, r.therapeutic_area,
               r.brand_focus, r.domain, r.timestamp_utc, r.status,
               r.sentiment_score, r.competitive_position, r.alert_triggered,
               r.response_text,
               (SELECT scoring_rationale FROM scores s
                WHERE s.response_id = r.response_id
                ORDER BY version DESC LIMIT 1) AS scoring_rationale
        FROM responses r
        ORDER BY r.timestamp_utc ASC, r.response_id ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_dashboard_data(conn: sqlite3.Connection) -> DashboardData:
    rows = collect_rows(conn)
    reasons = _alert_reasons(conn)

    by_llm: dict[str, list[float]] = {}
    by_therapy: dict[str, list[float]] = {}
    position_by_llm: dict[str, dict[str, int]] = {}
    volume_by_date: dict[str, int] = {}

    for r in rows:
        if r["sentiment_score"] is not None:
            by_llm.setdefault(r["llm_name"], []).append(r["sentiment_score"])
            by_therapy.setdefault(r["therapeutic_area"] or "Unknown", []).append(
                r["sentiment_score"]
            )
        if r["competitive_position"]:
            counts = position_by_llm.setdefault(r["llm_name"], {})
            counts[r["competitive_position"]] = (
                counts.get(r["competitive_position"], 0) + 1
            )
        date = (r["timestamp_utc"] or "")[:10] or "Unknown"
        volume_by_date[date] = volume_by_date.get(date, 0) + 1

    sentiment_by_llm = {k: round(_mean(v), 3) for k, v in by_llm.items()}
    sentiment_by_therapy = {k: round(_mean(v), 3) for k, v in by_therapy.items()}

    alerts = [
        {
            "response_id": r["response_id"],
            "llm_name": r["llm_name"],
            "reason": reasons.get(r["response_id"], "ALERT"),
            "rationale": r["scoring_rationale"],
        }
        for r in rows
        if r["alert_triggered"]
    ]

    return DashboardData(
        rows=rows,
        sentiment_by_llm=sentiment_by_llm,
        sentiment_by_therapy=sentiment_by_therapy,
        position_by_llm=position_by_llm,
        volume_by_date=volume_by_date,
        alerts=alerts,
        total_responses=len(rows),
        total_alerts=len(alerts),
    )
