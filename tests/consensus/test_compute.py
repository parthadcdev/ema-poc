"""Tests for ema_poc.consensus.compute — triple-run consensus computation."""

from __future__ import annotations

import pytest

from ema_poc.consensus.compute import compute_consensus
from ema_poc.db import connect, init_schema
from ema_poc.models import CompetitivePosition, Response, Score
from ema_poc.repositories.alerts import list_alerts
from ema_poc.repositories.consensus import list_consensus
from ema_poc.repositories.responses import save_response
from ema_poc.repositories.runs import create_run
from ema_poc.repositories.scores import save_score

# ── Fixed-determinism helpers ────────────────────────────────────────────────

NOW = "2026-06-14T00:00:00+00:00"
_id_counter = 0


def _fresh_id():
    global _id_counter
    _id_counter += 1
    return f"id{_id_counter:04d}"


def _reset_ids():
    global _id_counter
    _id_counter = 0


# ── DB setup ─────────────────────────────────────────────────────────────────


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "run1", started_at=NOW)
    return conn


# ── Seed helpers ──────────────────────────────────────────────────────────────


def _add_response(conn, *, run_id="run1", question_id="q1", llm_name="gpt-4",
                  sample_index: int, resp_id: str) -> str:
    """Insert a SUCCESS response row and return its response_id."""
    save_response(
        conn,
        Response(
            response_id=resp_id,
            run_id=run_id,
            timestamp_utc=NOW,
            llm_name=llm_name,
            llm_model_version="v1",
            persona="Provider",
            question_id=question_id,
            question_text="test question?",
            domain="Safety",
            response_text=f"answer-{sample_index}",
            response_tokens=10,
            finish_reason="stop",
            sample_index=sample_index,
            status="SUCCESS",
            created_at=NOW,
        ),
    )
    return resp_id


def _add_score(conn, resp_id: str, *, position: str, sentiment: float,
               score_id: str) -> str:
    """Insert a score row for the given response and return score_id."""
    save_score(
        conn,
        Score(
            score_id=score_id,
            response_id=resp_id,
            version=1,
            sentiment_score=sentiment,
            competitive_position=CompetitivePosition(position),
            brand_mentions=[],
            key_claims=[],
            scoring_rationale="auto",
            scoring_model="test-model",
            created_at=NOW,
        ),
    )
    return score_id


def _seed_samples(conn, samples, *, run_id="run1", question_id="q1",
                  llm_name="gpt-4"):
    """
    samples: list of (position_str, sentiment_float).
    Returns list of (resp_id, score_id).
    """
    ids = []
    for i, (pos, sent) in enumerate(samples):
        resp_id = f"resp-{question_id}-{llm_name}-{i}"
        score_id = f"score-{question_id}-{llm_name}-{i}"
        _add_response(conn, run_id=run_id, question_id=question_id,
                      llm_name=llm_name, sample_index=i, resp_id=resp_id)
        _add_score(conn, resp_id, position=pos, sentiment=sent, score_id=score_id)
        ids.append((resp_id, score_id))
    return ids


# ── Deterministic compute wrapper ─────────────────────────────────────────────


def _compute(conn):
    """Run compute_consensus with deterministic id/now factories."""
    _reset_ids()
    return compute_consensus(
        conn,
        now_factory=lambda: NOW,
        id_factory=_fresh_id,
    )


# ── Test 1: unanimous → 1 consensus row, no alert ────────────────────────────


def test_unanimous_three_samples_no_alert(tmp_path):
    conn = _conn(tmp_path)
    _seed_samples(
        conn,
        [
            ("FIRST_LINE_RECOMMENDED", 0.8),
            ("FIRST_LINE_RECOMMENDED", 0.7),
            ("FIRST_LINE_RECOMMENDED", 0.9),
        ],
    )

    result = _compute(conn)
    assert result.groups == 1
    assert result.alerts_raised == 0

    rows = list_consensus(conn)
    assert len(rows) == 1
    r = rows[0]
    assert r.canonical_position == "FIRST_LINE_RECOMMENDED"
    assert r.agreement == pytest.approx(1.0)
    assert r.sentiment_mean == pytest.approx(0.8)
    assert r.sample_count == 3

    alerts = list_alerts(conn)
    assert len(alerts) == 0


# ── Test 2: 2/3 majority + favorable↔unfavorable span → 1 alert ──────────────


def test_majority_with_favorable_unfavorable_span_raises_alert(tmp_path):
    conn = _conn(tmp_path)
    _seed_samples(
        conn,
        [
            ("FIRST_LINE_RECOMMENDED", 0.9),
            ("FIRST_LINE_RECOMMENDED", 0.8),
            ("NOT_MENTIONED", 0.1),
        ],
    )

    result = _compute(conn)
    assert result.groups == 1
    assert result.alerts_raised == 1

    rows = list_consensus(conn)
    assert len(rows) == 1
    r = rows[0]
    assert r.canonical_position == "FIRST_LINE_RECOMMENDED"
    assert r.agreement == pytest.approx(2 / 3)

    alerts = list_alerts(conn)
    assert len(alerts) == 1
    reason = alerts[0].reason
    assert reason.startswith("VARIANCE")
    assert "NOT_MENTIONED" in reason
    assert "FIRST_LINE_RECOMMENDED" in reason


# ── Test 3: three distinct positions → no majority, 1 alert ──────────────────


def test_three_distinct_positions_no_majority_raises_alert(tmp_path):
    conn = _conn(tmp_path)
    _seed_samples(
        conn,
        [
            ("FIRST_LINE_RECOMMENDED", 0.9),
            ("SECOND_LINE", 0.5),
            ("NOT_MENTIONED", 0.1),
        ],
    )

    result = _compute(conn)
    assert result.groups == 1
    assert result.alerts_raised == 1

    rows = list_consensus(conn)
    assert len(rows) == 1
    r = rows[0]
    assert r.canonical_position is None  # no majority
    assert r.agreement == pytest.approx(1 / 3)

    alerts = list_alerts(conn)
    assert len(alerts) == 1
    assert alerts[0].reason.startswith("VARIANCE")


# ── Test 4: 2 AMONG_OPTIONS + 1 SECOND_LINE → canonical, no alert ────────────


def test_among_options_majority_no_alert(tmp_path):
    """SECOND_LINE is neutral (not in FAVORABLE or UNFAVORABLE), so no span
    alert; canonical exists, so no majority alert either."""
    conn = _conn(tmp_path)
    _seed_samples(
        conn,
        [
            ("AMONG_OPTIONS", 0.6),
            ("AMONG_OPTIONS", 0.7),
            ("SECOND_LINE", 0.4),
        ],
    )

    result = _compute(conn)
    assert result.groups == 1
    assert result.alerts_raised == 0

    rows = list_consensus(conn)
    assert len(rows) == 1
    r = rows[0]
    assert r.canonical_position == "AMONG_OPTIONS"
    assert r.agreement == pytest.approx(2 / 3)

    alerts = list_alerts(conn)
    assert len(alerts) == 0


# ── Test 5: idempotency — second call is a no-op ─────────────────────────────


def test_idempotent_second_call_is_noop(tmp_path):
    conn = _conn(tmp_path)
    _seed_samples(
        conn,
        [
            ("FIRST_LINE_RECOMMENDED", 0.8),
            ("FIRST_LINE_RECOMMENDED", 0.7),
            ("FIRST_LINE_RECOMMENDED", 0.9),
        ],
    )

    first = _compute(conn)
    assert first.groups == 1

    second = _compute(conn)
    assert second.groups == 0
    assert second.alerts_raised == 0

    # Still only 1 consensus row after second run
    assert len(list_consensus(conn)) == 1


# ── Test 6: sentiment_mean / pstdev correctness ───────────────────────────────


def test_sentiment_statistics_correctness(tmp_path):
    conn = _conn(tmp_path)
    # Two samples: [0.0, 1.0] → mean 0.5, pstdev 0.5
    _seed_samples(
        conn,
        [
            ("AMONG_OPTIONS", 0.0),
            ("AMONG_OPTIONS", 1.0),
        ],
    )

    _compute(conn)

    rows = list_consensus(conn)
    assert len(rows) == 1
    r = rows[0]
    assert r.sentiment_mean == pytest.approx(0.5)
    assert r.sentiment_stdev == pytest.approx(0.5)


# ── Test 7: alert score_id is a real score row id ────────────────────────────


def test_alert_references_real_score_id(tmp_path):
    conn = _conn(tmp_path)
    ids = _seed_samples(
        conn,
        [
            ("FIRST_LINE_RECOMMENDED", 0.9),
            ("NOT_RECOMMENDED", 0.1),
            ("NOT_MENTIONED", 0.0),
        ],
    )
    # ids[0] is (resp_id, score_id) of the first sample
    first_score_id = ids[0][1]

    _compute(conn)

    alerts = list_alerts(conn)
    assert len(alerts) == 1
    # The alert must point to the first sample's actual score row
    assert alerts[0].score_id == first_score_id


# ── Test 8: multiple groups processed independently ──────────────────────────


def test_multiple_groups_independent(tmp_path):
    conn = _conn(tmp_path)
    create_run(conn, "run2", started_at=NOW)

    # Group A: run1/q1/gpt-4 — unanimous, no alert
    _seed_samples(
        conn,
        [("FIRST_LINE_RECOMMENDED", 0.9), ("FIRST_LINE_RECOMMENDED", 0.8),
         ("FIRST_LINE_RECOMMENDED", 0.7)],
        run_id="run1", question_id="q1", llm_name="gpt-4",
    )
    # Group B: run1/q2/gpt-4 — mixed, alert
    _seed_samples(
        conn,
        [("AMONG_OPTIONS", 0.5), ("NOT_MENTIONED", 0.1), ("NOT_RECOMMENDED", 0.0)],
        run_id="run1", question_id="q2", llm_name="gpt-4",
    )

    result = _compute(conn)
    assert result.groups == 2
    assert result.alerts_raised == 1  # only group B raises alert

    rows = list_consensus(conn)
    assert len(rows) == 2
    assert len(list_alerts(conn)) == 1
