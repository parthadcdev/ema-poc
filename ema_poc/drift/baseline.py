"""Freeze the v0 baseline snapshot per (question, LLM) pair (the fixed reference
for drift comparison)."""

from __future__ import annotations

from ema_poc.repositories.baselines import get_baseline, set_baseline


def freeze_baseline(conn, *, now: str, force: bool = False) -> int:
    """For each (question_id, llm_name) that has at least one SCORED response
    (competitive_position not null), set its baseline to that pair's latest
    scored response. Skips pairs already frozen unless force=True. Returns the
    number of baselines written."""
    pairs = conn.execute(
        """SELECT question_id, llm_name,
                  (SELECT response_id FROM responses r2
                   WHERE r2.question_id = r.question_id AND r2.llm_name = r.llm_name
                     AND r2.competitive_position IS NOT NULL
                   ORDER BY r2.timestamp_utc DESC, r2.response_id DESC LIMIT 1) AS latest_scored,
                  (SELECT competitive_position FROM responses r2
                   WHERE r2.question_id = r.question_id AND r2.llm_name = r.llm_name
                     AND r2.competitive_position IS NOT NULL
                   ORDER BY r2.timestamp_utc DESC, r2.response_id DESC LIMIT 1) AS latest_position
           FROM responses r
           WHERE r.competitive_position IS NOT NULL
           GROUP BY r.question_id, r.llm_name""",
    ).fetchall()
    written = 0
    for p in pairs:
        if not force and get_baseline(conn, p["question_id"], p["llm_name"]) is not None:
            continue
        set_baseline(conn, question_id=p["question_id"], llm_name=p["llm_name"],
                     response_id=p["latest_scored"],
                     competitive_position=p["latest_position"],
                     now=now, commit=False)
        written += 1
    conn.commit()
    return written
