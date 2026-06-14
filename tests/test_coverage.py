"""Tests for ema_poc.coverage — question effectiveness / coverage analysis."""

from __future__ import annotations

import sqlite3

import pytest

from ema_poc.db import init_schema
from ema_poc.coverage import (
    QuestionEffectiveness,
    format_coverage_report,
    question_effectiveness,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


def _insert_response(conn, *, response_id, question_id, question_text,
                     brand_focus, competitive_position):
    conn.execute(
        """
        INSERT INTO runs (run_id, started_at, status)
        VALUES ('run-1', '2024-01-01T00:00:00Z', 'DONE')
        ON CONFLICT(run_id) DO NOTHING
        """,
    )
    conn.execute(
        """
        INSERT INTO responses (
            response_id, run_id, timestamp_utc, llm_name, llm_model_version,
            persona, question_id, question_text, brand_focus, domain,
            response_text, status, competitive_position, created_at
        ) VALUES (?, 'run-1', '2024-01-01T00:00:00Z', 'gpt-4o', 'gpt-4o',
                  'Provider', ?, ?, ?, 'general', 'some response text',
                  'SUCCESS', ?, '2024-01-01T00:00:00Z')
        """,
        (response_id, question_id, question_text, brand_focus,
         competitive_position),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_low_value_question_crosses_threshold():
    """A question with 4 NOT_MENTIONED out of 4 scored should be low_value."""
    conn = _make_conn()
    # Q1: 4 NOT_MENTIONED out of 4 => 100% => low_value (>= 3, >= 0.8)
    for i in range(4):
        _insert_response(
            conn,
            response_id=f"r-q1-{i}",
            question_id="Q1",
            question_text="Does BrandX help with asthma?",
            brand_focus="BrandX",
            competitive_position="NOT_MENTIONED",
        )
    # Q2: 1 NOT_MENTIONED out of 3 => 33% => not low_value
    _insert_response(
        conn,
        response_id="r-q2-0",
        question_id="Q2",
        question_text="What are the benefits of BrandY?",
        brand_focus="BrandY",
        competitive_position="NOT_MENTIONED",
    )
    _insert_response(
        conn,
        response_id="r-q2-1",
        question_id="Q2",
        question_text="What are the benefits of BrandY?",
        brand_focus="BrandY",
        competitive_position="POSITIVE",
    )
    _insert_response(
        conn,
        response_id="r-q2-2",
        question_id="Q2",
        question_text="What are the benefits of BrandY?",
        brand_focus="BrandY",
        competitive_position="NEUTRAL",
    )

    results = question_effectiveness(conn, min_responses=3, not_mentioned_threshold=0.8)

    assert len(results) == 2
    # low-value first
    assert results[0].question_id == "Q1"
    assert results[0].low_value is True
    assert results[0].total_scored == 4
    assert results[0].not_mentioned == 4
    assert abs(results[0].not_mentioned_rate - 1.0) < 1e-9

    assert results[1].question_id == "Q2"
    assert results[1].low_value is False
    assert results[1].total_scored == 3
    assert results[1].not_mentioned == 1
    assert abs(results[1].not_mentioned_rate - 1 / 3) < 1e-9


def test_question_below_min_responses_never_low_value():
    """A question with fewer than min_responses scored is never low_value,
    even if 100% NOT_MENTIONED."""
    conn = _make_conn()
    # Only 2 responses, all NOT_MENTIONED — below min_responses=3
    for i in range(2):
        _insert_response(
            conn,
            response_id=f"r-q3-{i}",
            question_id="Q3",
            question_text="Is BrandZ effective?",
            brand_focus="BrandZ",
            competitive_position="NOT_MENTIONED",
        )

    results = question_effectiveness(conn, min_responses=3, not_mentioned_threshold=0.8)

    assert len(results) == 1
    q = results[0]
    assert q.question_id == "Q3"
    assert q.low_value is False
    assert q.not_mentioned == 2
    assert q.total_scored == 2
    assert abs(q.not_mentioned_rate - 1.0) < 1e-9


def test_exactly_at_threshold_is_low_value():
    """A question at exactly min_responses and exactly the threshold is low_value."""
    conn = _make_conn()
    # 3 responses, 3 NOT_MENTIONED => 100% >= 0.8, count >= 3 => low_value
    for i in range(3):
        _insert_response(
            conn,
            response_id=f"r-q4-{i}",
            question_id="Q4",
            question_text="Is BrandA ever mentioned?",
            brand_focus="BrandA",
            competitive_position="NOT_MENTIONED",
        )

    results = question_effectiveness(conn, min_responses=3, not_mentioned_threshold=0.8)
    assert len(results) == 1
    assert results[0].low_value is True


def test_ordering_low_value_first_then_by_rate_desc():
    """Low-value questions come first; within same group, sorted by rate desc."""
    conn = _make_conn()
    # Q-A: low_value, 100% NOT_MENTIONED (4/4)
    for i in range(4):
        _insert_response(
            conn, response_id=f"qa-{i}", question_id="Q-A",
            question_text="Q A text", brand_focus="BrandA",
            competitive_position="NOT_MENTIONED",
        )
    # Q-B: low_value, 80% NOT_MENTIONED (4 NM out of 5)
    for i in range(4):
        _insert_response(
            conn, response_id=f"qb-nm-{i}", question_id="Q-B",
            question_text="Q B text", brand_focus="BrandB",
            competitive_position="NOT_MENTIONED",
        )
    _insert_response(
        conn, response_id="qb-ok", question_id="Q-B",
        question_text="Q B text", brand_focus="BrandB",
        competitive_position="POSITIVE",
    )
    # Q-C: not low_value, 33% NOT_MENTIONED (1 out of 3)
    _insert_response(
        conn, response_id="qc-nm", question_id="Q-C",
        question_text="Q C text", brand_focus="BrandC",
        competitive_position="NOT_MENTIONED",
    )
    for i in range(2):
        _insert_response(
            conn, response_id=f"qc-ok-{i}", question_id="Q-C",
            question_text="Q C text", brand_focus="BrandC",
            competitive_position="NEUTRAL",
        )

    results = question_effectiveness(conn, min_responses=3, not_mentioned_threshold=0.8)

    assert len(results) == 3
    # Low-value first (Q-A 100%, then Q-B 80%)
    assert results[0].question_id == "Q-A"
    assert results[1].question_id == "Q-B"
    # Non-low-value last
    assert results[2].question_id == "Q-C"
    assert results[2].low_value is False


def test_no_scored_responses_returns_empty():
    """Empty DB returns empty list."""
    conn = _make_conn()
    results = question_effectiveness(conn)
    assert results == []


def test_unscored_responses_ignored():
    """Responses with NULL competitive_position are excluded."""
    conn = _make_conn()
    conn.execute(
        """
        INSERT INTO runs (run_id, started_at, status)
        VALUES ('run-1', '2024-01-01T00:00:00Z', 'DONE')
        ON CONFLICT(run_id) DO NOTHING
        """,
    )
    conn.execute(
        """
        INSERT INTO responses (
            response_id, run_id, timestamp_utc, llm_name, llm_model_version,
            persona, question_id, question_text, brand_focus, domain,
            response_text, status, competitive_position, created_at
        ) VALUES ('r-unscored', 'run-1', '2024-01-01T00:00:00Z',
                  'gpt-4o', 'gpt-4o', 'Provider', 'Q5', 'Unscored Q',
                  'BrandX', 'general', 'text', 'SUCCESS', NULL,
                  '2024-01-01T00:00:00Z')
        """,
    )
    conn.commit()
    results = question_effectiveness(conn)
    assert results == []


# ---------------------------------------------------------------------------
# format_coverage_report tests
# ---------------------------------------------------------------------------

def test_format_coverage_report_empty():
    report = format_coverage_report([])
    assert report == "No scored responses yet — run scoring first."


def test_format_coverage_report_with_items():
    items = [
        QuestionEffectiveness(
            question_id="Q1",
            question_text="Does BrandX help with asthma?",
            brand_focus="BrandX",
            total_scored=4,
            not_mentioned=4,
            not_mentioned_rate=1.0,
            low_value=True,
        ),
        QuestionEffectiveness(
            question_id="Q2",
            question_text="What are the benefits of BrandY?",
            brand_focus="BrandY",
            total_scored=3,
            not_mentioned=1,
            not_mentioned_rate=1 / 3,
            low_value=False,
        ),
    ]
    report = format_coverage_report(items)
    assert "2 scored questions" in report
    assert "1 flagged low-value" in report
    assert "[LOW-VALUE]" in report
    assert "[ok]" in report
    assert "Q1" in report
    assert "Q2" in report
    assert "100%" in report
    assert "33%" in report


def test_format_coverage_report_question_text_truncated():
    # Use a text where char 60 onward is distinctive and won't appear in the truncated form
    prefix = "Short question text that fills exactly sixty characters!!!!!"
    suffix = "TRAILING_UNIQUE_SUFFIX_THAT_SHOULD_NOT_APPEAR"
    long_text = prefix + suffix
    assert len(prefix) == 60  # sanity check
    items = [
        QuestionEffectiveness(
            question_id="Q1",
            question_text=long_text,
            brand_focus="BrandX",
            total_scored=4,
            not_mentioned=4,
            not_mentioned_rate=1.0,
            low_value=True,
        ),
    ]
    report = format_coverage_report(items)
    # Only first 60 chars of question_text should appear
    assert prefix in report
    assert suffix not in report
