"""Tests for freeze_baseline and the baselines repository (drift v0 baseline)."""

import pytest

from ema_poc.db import connect, init_schema
from ema_poc.repositories.baselines import get_baseline, list_baselines, set_baseline
from ema_poc.drift.baseline import freeze_baseline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    conn.execute(
        "INSERT INTO runs (run_id, started_at) VALUES ('r1', '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    return conn


def _insert_response(conn, *, response_id, question_id, llm_name,
                     competitive_position=None, timestamp_utc="2026-01-01T00:00:00+00:00"):
    """Insert a minimal responses row; competitive_position NULL means unscored."""
    conn.execute(
        """INSERT INTO responses (response_id, run_id, timestamp_utc, llm_name,
           llm_model_version, persona, question_id, question_text, domain,
           response_text, status, competitive_position, created_at)
           VALUES (?, 'r1', ?, ?, 'm', 'Provider', ?, 'q', 'General', 'ans', 'SUCCESS', ?, ?)""",
        (response_id, timestamp_utc, llm_name, question_id, competitive_position,
         timestamp_utc),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Repository round-trip tests
# ---------------------------------------------------------------------------

def test_set_get_baseline_round_trip(tmp_path):
    conn = _conn(tmp_path)
    _insert_response(conn, response_id="resp1", question_id="Q1", llm_name="llm-a",
                     competitive_position="FIRST_LINE_RECOMMENDED")
    set_baseline(conn, question_id="Q1", llm_name="llm-a",
                 response_id="resp1", now="2026-06-01T00:00:00+00:00")
    row = get_baseline(conn, "Q1", "llm-a")
    assert row is not None
    assert row.question_id == "Q1"
    assert row.llm_name == "llm-a"
    assert row.response_id == "resp1"
    assert row.frozen_at == "2026-06-01T00:00:00+00:00"


def test_get_baseline_missing_returns_none(tmp_path):
    conn = _conn(tmp_path)
    assert get_baseline(conn, "Q-none", "no-llm") is None


def test_list_baselines_empty(tmp_path):
    conn = _conn(tmp_path)
    assert list_baselines(conn) == []


def test_list_baselines_multiple_ordered(tmp_path):
    conn = _conn(tmp_path)
    for rid, qid, llm in [("r1", "Q2", "llm-b"), ("r2", "Q1", "llm-a"), ("r3", "Q2", "llm-a")]:
        _insert_response(conn, response_id=rid, question_id=qid, llm_name=llm,
                         competitive_position="AMONG_OPTIONS")
    set_baseline(conn, question_id="Q2", llm_name="llm-b", response_id="r1",
                 now="2026-06-01T00:00:00+00:00")
    set_baseline(conn, question_id="Q1", llm_name="llm-a", response_id="r2",
                 now="2026-06-01T00:00:00+00:00")
    set_baseline(conn, question_id="Q2", llm_name="llm-a", response_id="r3",
                 now="2026-06-01T00:00:00+00:00")
    rows = list_baselines(conn)
    # ordered by question_id then llm_name
    assert [(r.question_id, r.llm_name) for r in rows] == [
        ("Q1", "llm-a"), ("Q2", "llm-a"), ("Q2", "llm-b")
    ]


def test_set_baseline_insert_or_replace(tmp_path):
    """INSERT OR REPLACE overwrites the existing row for the same PK."""
    conn = _conn(tmp_path)
    _insert_response(conn, response_id="resp1", question_id="Q1", llm_name="llm-a",
                     competitive_position="FIRST_LINE_RECOMMENDED")
    _insert_response(conn, response_id="resp2", question_id="Q1", llm_name="llm-a",
                     competitive_position="AMONG_OPTIONS",
                     timestamp_utc="2026-02-01T00:00:00+00:00")
    set_baseline(conn, question_id="Q1", llm_name="llm-a",
                 response_id="resp1", now="2026-06-01T00:00:00+00:00")
    set_baseline(conn, question_id="Q1", llm_name="llm-a",
                 response_id="resp2", now="2026-06-02T00:00:00+00:00")
    row = get_baseline(conn, "Q1", "llm-a")
    assert row.response_id == "resp2"
    assert row.frozen_at == "2026-06-02T00:00:00+00:00"


# ---------------------------------------------------------------------------
# freeze_baseline behaviour tests
# ---------------------------------------------------------------------------

def test_freeze_baseline_picks_latest_scored(tmp_path):
    """Baseline must point to the newer (higher timestamp) scored response."""
    conn = _conn(tmp_path)
    _insert_response(conn, response_id="old", question_id="Q1", llm_name="llm-a",
                     competitive_position="AMONG_OPTIONS",
                     timestamp_utc="2026-01-01T00:00:00+00:00")
    _insert_response(conn, response_id="new", question_id="Q1", llm_name="llm-a",
                     competitive_position="FIRST_LINE_RECOMMENDED",
                     timestamp_utc="2026-02-01T00:00:00+00:00")
    count = freeze_baseline(conn, now="2026-06-01T00:00:00+00:00")
    assert count == 1
    row = get_baseline(conn, "Q1", "llm-a")
    assert row.response_id == "new"


def test_freeze_baseline_unscored_pair_gets_no_baseline(tmp_path):
    """A pair with only NULL competitive_position must not receive a baseline."""
    conn = _conn(tmp_path)
    _insert_response(conn, response_id="resp1", question_id="Q1", llm_name="llm-a",
                     competitive_position=None)
    count = freeze_baseline(conn, now="2026-06-01T00:00:00+00:00")
    assert count == 0
    assert get_baseline(conn, "Q1", "llm-a") is None


def test_freeze_baseline_skips_already_frozen(tmp_path):
    """Without force=True, already-frozen pairs are not overwritten."""
    conn = _conn(tmp_path)
    _insert_response(conn, response_id="resp1", question_id="Q1", llm_name="llm-a",
                     competitive_position="AMONG_OPTIONS",
                     timestamp_utc="2026-01-01T00:00:00+00:00")
    # Freeze once — establishes the baseline
    freeze_baseline(conn, now="2026-06-01T00:00:00+00:00")

    # Add a newer scored response for the same pair
    _insert_response(conn, response_id="resp2", question_id="Q1", llm_name="llm-a",
                     competitive_position="FIRST_LINE_RECOMMENDED",
                     timestamp_utc="2026-03-01T00:00:00+00:00")

    # freeze again without force — should skip
    count = freeze_baseline(conn, now="2026-06-02T00:00:00+00:00")
    assert count == 0
    row = get_baseline(conn, "Q1", "llm-a")
    assert row.response_id == "resp1"  # still the original


def test_freeze_baseline_force_updates_to_newest(tmp_path):
    """With force=True, an existing baseline is replaced with the current latest."""
    conn = _conn(tmp_path)
    _insert_response(conn, response_id="resp1", question_id="Q1", llm_name="llm-a",
                     competitive_position="AMONG_OPTIONS",
                     timestamp_utc="2026-01-01T00:00:00+00:00")
    freeze_baseline(conn, now="2026-06-01T00:00:00+00:00")

    # New scored response arrives after initial freeze
    _insert_response(conn, response_id="resp2", question_id="Q1", llm_name="llm-a",
                     competitive_position="FIRST_LINE_RECOMMENDED",
                     timestamp_utc="2026-03-01T00:00:00+00:00")

    count = freeze_baseline(conn, now="2026-06-02T00:00:00+00:00", force=True)
    assert count == 1
    row = get_baseline(conn, "Q1", "llm-a")
    assert row.response_id == "resp2"
    assert row.frozen_at == "2026-06-02T00:00:00+00:00"


def test_freeze_baseline_returns_count(tmp_path):
    """Returns correct count of newly-written baselines."""
    conn = _conn(tmp_path)
    # Two scored pairs
    _insert_response(conn, response_id="r1", question_id="Q1", llm_name="llm-a",
                     competitive_position="AMONG_OPTIONS")
    _insert_response(conn, response_id="r2", question_id="Q2", llm_name="llm-b",
                     competitive_position="FIRST_LINE_RECOMMENDED")
    # One unscored pair — should NOT count
    _insert_response(conn, response_id="r3", question_id="Q3", llm_name="llm-c",
                     competitive_position=None)

    count = freeze_baseline(conn, now="2026-06-01T00:00:00+00:00")
    assert count == 2


def test_freeze_baseline_mixed_scored_unscored_in_pair(tmp_path):
    """A pair with both scored and unscored responses picks the latest SCORED one."""
    conn = _conn(tmp_path)
    # Unscored (newer timestamp)
    _insert_response(conn, response_id="unscored", question_id="Q1", llm_name="llm-a",
                     competitive_position=None,
                     timestamp_utc="2026-03-01T00:00:00+00:00")
    # Scored (older timestamp)
    _insert_response(conn, response_id="scored", question_id="Q1", llm_name="llm-a",
                     competitive_position="SECOND_LINE",
                     timestamp_utc="2026-01-01T00:00:00+00:00")
    count = freeze_baseline(conn, now="2026-06-01T00:00:00+00:00")
    assert count == 1
    row = get_baseline(conn, "Q1", "llm-a")
    assert row.response_id == "scored"


def test_freeze_baseline_no_responses_returns_zero(tmp_path):
    """Empty database — nothing to freeze."""
    conn = _conn(tmp_path)
    count = freeze_baseline(conn, now="2026-06-01T00:00:00+00:00")
    assert count == 0
