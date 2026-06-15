"""Flatten DB into one JSON-serializable dataset for client-side filtering + aggregation."""

from __future__ import annotations

import json
import sqlite3


def collect_dataset(
    conn: sqlite3.Connection,
    *,
    abbvie_brands: list[str] | tuple[str, ...],
    competitor_brands: list[str] | tuple[str, ...],
    now: str = "",
) -> dict:
    """Return a single JSON-serializable dict with all response data expanded.

    Efficient: uses four bulk queries (latest scores, hallucination checks,
    hallucination flags, alert reasons) keyed by response_id — no per-row N+1.
    """
    # ------------------------------------------------------------------ #
    # 1. Latest score per response                                         #
    # ------------------------------------------------------------------ #
    # We use a window-function approach: pick the row with max version per
    # response_id. SQLite 3.25+ supports window functions; fall back to a
    # correlated subquery form that works on all versions.
    score_rows = conn.execute(
        """
        SELECT s.*
        FROM scores s
        WHERE s.version = (
            SELECT MAX(s2.version) FROM scores s2
            WHERE s2.response_id = s.response_id
        )
        """
    ).fetchall()

    # keyed by response_id
    latest_scores: dict[str, dict] = {}
    for row in score_rows:
        d = dict(row)
        # parse brand_mentions JSON text -> list[str]
        raw_bm = d.get("brand_mentions") or ""
        try:
            bm = json.loads(raw_bm) if raw_bm.strip() else []
        except (json.JSONDecodeError, AttributeError):
            bm = []
        d["brand_mentions"] = bm
        latest_scores[d["response_id"]] = d

    # ------------------------------------------------------------------ #
    # 2. Hallucination checks (one per response)                           #
    # ------------------------------------------------------------------ #
    check_rows = conn.execute(
        "SELECT response_id, risk_level FROM hallucination_checks"
    ).fetchall()
    halluc_risk: dict[str, str] = {r["response_id"]: r["risk_level"] for r in check_rows}

    # ------------------------------------------------------------------ #
    # 3. Hallucination flags grouped by response_id                        #
    # ------------------------------------------------------------------ #
    flag_rows = conn.execute(
        """
        SELECT response_id, claim, conflicts_with, severity
        FROM hallucination_flags
        ORDER BY created_at ASC, flag_id ASC
        """
    ).fetchall()
    halluc_flags: dict[str, list[dict]] = {}
    for row in flag_rows:
        rid = row["response_id"]
        halluc_flags.setdefault(rid, []).append(
            {
                "claim": row["claim"],
                "conflicts_with": row["conflicts_with"],
                "severity": row["severity"],
            }
        )

    # ------------------------------------------------------------------ #
    # 4. Alert reasons grouped by response_id (via scores join)            #
    # ------------------------------------------------------------------ #
    alert_rows = conn.execute(
        """
        SELECT r.response_id AS response_id, a.reason AS reason
        FROM alerts a
        JOIN scores s ON a.score_id = s.score_id
        JOIN responses r ON s.response_id = r.response_id
        ORDER BY a.created_at ASC, a.alert_id ASC
        """
    ).fetchall()
    alert_reasons_map: dict[str, list[str]] = {}
    for row in alert_rows:
        rid = row["response_id"]
        alert_reasons_map.setdefault(rid, []).append(row["reason"])

    # ------------------------------------------------------------------ #
    # 5. Base response rows                                                #
    # ------------------------------------------------------------------ #
    response_rows = conn.execute(
        """
        SELECT response_id, timestamp_utc, llm_name, persona,
               question_id, question_text, therapeutic_area, brand_focus, domain,
               status, response_text
        FROM responses
        ORDER BY timestamp_utc ASC, response_id ASC
        """
    ).fetchall()

    # ------------------------------------------------------------------ #
    # 6. Assemble records                                                  #
    # ------------------------------------------------------------------ #
    records: list[dict] = []
    for row in response_rows:
        rid = row["response_id"]
        ts = row["timestamp_utc"] or ""
        llm_name = row["llm_name"]

        score = latest_scores.get(rid)
        if score is not None:
            sentiment_score = score.get("sentiment_score")
            # ensure float or None
            if sentiment_score is not None:
                sentiment_score = float(sentiment_score)
            competitive_position = score.get("competitive_position") or None
            confidence_level = score.get("confidence_level") or None
            citation_quality = score.get("citation_quality") or None
            brand_mentions: list[str] = score.get("brand_mentions") or []
            scoring_rationale = score.get("scoring_rationale") or None
        else:
            sentiment_score = None
            competitive_position = None
            confidence_level = None
            citation_quality = None
            brand_mentions = []
            scoring_rationale = None

        reasons = alert_reasons_map.get(rid, [])

        record: dict = {
            "response_id": rid,
            "source": "monitoring",
            "timestamp_utc": ts,
            "date": ts[:10],
            "llm_name": llm_name,
            "grounded": llm_name.endswith("-Grounded"),
            "persona": row["persona"],
            "question_id": row["question_id"],
            "question_text": row["question_text"],
            "therapeutic_area": row["therapeutic_area"],
            "brand_focus": row["brand_focus"],
            "domain": row["domain"],
            "status": row["status"],
            "response_text": row["response_text"],
            "sentiment_score": sentiment_score,
            "competitive_position": competitive_position,
            "confidence_level": confidence_level,
            "citation_quality": citation_quality,
            "brand_mentions": brand_mentions,
            "scoring_rationale": scoring_rationale,
            "hallucination_risk": halluc_risk.get(rid),
            "hallucination_flags": halluc_flags.get(rid, []),
            "alert_reasons": reasons,
            "alert_triggered": len(reasons) > 0,
        }
        records.append(record)

    # ------------------------------------------------------------------ #
    # 7. Realtime playground (sandbox) responses — folded in, tagged      #
    # ------------------------------------------------------------------ #
    sandbox_rows = conn.execute(
        """
        SELECT sr.sandbox_response_id, sr.query_id, sr.llm_name, sr.grounded,
               sr.answer_text, sr.status, sr.sentiment_score, sr.competitive_position,
               sr.scoring_rationale, sr.brand_mentions,
               q.timestamp_utc, q.question_text, q.persona, q.brand_focus
        FROM sandbox_responses sr
        JOIN sandbox_queries q ON sr.query_id = q.query_id
        ORDER BY q.timestamp_utc ASC, sr.sandbox_response_id ASC
        """
    ).fetchall()
    for row in sandbox_rows:
        d = dict(row)
        ts = d["timestamp_utc"] or ""
        sentiment_score = d["sentiment_score"]
        if sentiment_score is not None:
            sentiment_score = float(sentiment_score)
        raw_bm = d.get("brand_mentions") or ""
        try:
            bm = json.loads(raw_bm) if raw_bm.strip() else []
        except (json.JSONDecodeError, AttributeError):
            bm = []
        records.append({
            "response_id": "sb-" + d["sandbox_response_id"],
            "timestamp_utc": ts,
            "date": ts[:10],
            "llm_name": d["llm_name"],
            # sandbox stores an explicit grounded flag (the monitoring path instead
            # infers it from the "-Grounded" llm_name suffix) — keep this column read.
            "grounded": bool(d["grounded"]),
            "persona": d["persona"],
            "question_id": d["query_id"],
            "question_text": d["question_text"],
            "therapeutic_area": None,
            "brand_focus": d["brand_focus"],
            "domain": None,
            "status": d["status"],
            "response_text": d["answer_text"],
            "sentiment_score": sentiment_score,
            "competitive_position": d["competitive_position"] or None,
            "confidence_level": None,
            "citation_quality": None,
            "brand_mentions": bm,
            "scoring_rationale": d["scoring_rationale"] or None,
            "hallucination_risk": None,
            "hallucination_flags": [],
            "alert_reasons": [],
            "alert_triggered": False,
            "source": "realtime",
        })

    return {
        "generated_at": now,
        "abbvie_brands": list(abbvie_brands),
        "competitor_brands": list(competitor_brands),
        "records": records,
    }
