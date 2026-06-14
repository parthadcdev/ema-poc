"""Tests for detect_drift — cosine-to-baseline and position-change alerts."""

from __future__ import annotations

import types

import pytest

from ema_poc.config import DriftConfig
from ema_poc.db import connect, init_schema
from ema_poc.models import CompetitivePosition, Score
from ema_poc.repositories.alerts import list_alerts
from ema_poc.repositories.baselines import set_baseline
from ema_poc.repositories.responses import update_response_scoring
from ema_poc.repositories.scores import save_score
from ema_poc.drift.detector import DriftSummary, detect_drift


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

NOW = "2026-06-01T00:00:00+00:00"
NOW2 = "2026-06-02T00:00:00+00:00"
MODEL = "text-embedding-3-small"


class FakeEmb:
    """Fake embedding client: maps response_text -> fixed vector."""
    def __init__(self, mapping: dict[str, list[float]]):
        self.mapping = mapping

    def embed(self, text: str) -> list[float]:
        return self.mapping[text]


def _make_config(threshold: float = 0.85, model: str = MODEL):
    """Build a minimal config namespace exposing .drift.cosine_threshold and
    .drift.embedding_model (matches AppConfig's .drift attribute shape)."""
    drift = DriftConfig(cosine_threshold=threshold, embedding_model=model)
    cfg = types.SimpleNamespace(drift=drift)
    return cfg


def _conn(tmp_path):
    """In-file SQLite DB with schema initialised and a single run row."""
    conn = connect(str(tmp_path / "test.sqlite"))
    init_schema(conn)
    conn.execute(
        "INSERT INTO runs (run_id, started_at) VALUES ('r1', '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    return conn


def _insert_response(
    conn,
    *,
    response_id: str,
    question_id: str,
    llm_name: str,
    response_text: str = "answer",
    competitive_position: str | None = None,
    timestamp_utc: str = NOW,
):
    """Insert a minimal responses row."""
    conn.execute(
        """INSERT INTO responses
           (response_id, run_id, timestamp_utc, llm_name, llm_model_version,
            persona, question_id, question_text, domain, response_text, status,
            competitive_position, created_at)
           VALUES (?, 'r1', ?, ?, 'm', 'Provider', ?, 'q?', 'General', ?, 'SUCCESS', ?, ?)""",
        (response_id, timestamp_utc, llm_name, question_id, response_text,
         competitive_position, timestamp_utc),
    )
    conn.commit()


def _save_score_for(conn, *, response_id: str, score_id: str,
                    position: CompetitivePosition = CompetitivePosition.AMONG_OPTIONS) -> Score:
    """Insert a score row for a response and return it."""
    score = Score(
        score_id=score_id,
        response_id=response_id,
        version=1,
        sentiment_score=0.5,
        competitive_position=position,
        scoring_model="test-model",
        created_at=NOW,
    )
    save_score(conn, score)
    return score


def _setup_pair(
    conn,
    *,
    question_id: str,
    llm_name: str,
    baseline_text: str,
    baseline_pos: CompetitivePosition,
    latest_text: str,
    latest_pos: CompetitivePosition,
):
    """Insert baseline + newer response, both scored, with a drift baseline set.
    Returns (baseline_response_id, latest_response_id, latest_score_id)."""
    bid = f"base_{question_id}_{llm_name}"
    lid = f"latest_{question_id}_{llm_name}"
    sid = f"score_{lid}"

    _insert_response(conn, response_id=bid, question_id=question_id, llm_name=llm_name,
                     response_text=baseline_text, competitive_position=baseline_pos.value,
                     timestamp_utc="2026-01-01T00:00:00+00:00")
    _insert_response(conn, response_id=lid, question_id=question_id, llm_name=llm_name,
                     response_text=latest_text, competitive_position=latest_pos.value,
                     timestamp_utc="2026-05-01T00:00:00+00:00")

    # Score the latest response so latest_score() finds a row
    _save_score_for(conn, response_id=lid, score_id=sid, position=latest_pos)

    # Freeze the baseline — store the frozen position from the baseline response
    set_baseline(conn, question_id=question_id, llm_name=llm_name,
                 response_id=bid, now=NOW,
                 competitive_position=baseline_pos.value)

    return bid, lid, sid


# ---------------------------------------------------------------------------
# Case 1: different vectors (cosine < threshold) + same position → DRIFT alert
# ---------------------------------------------------------------------------

def test_cosine_drift_triggers_alert(tmp_path):
    conn = _conn(tmp_path)
    base_vec = [1.0, 0.0]
    new_vec = [0.0, 1.0]  # orthogonal → cosine == 0.0

    _setup_pair(
        conn,
        question_id="Q1", llm_name="llm-a",
        baseline_text="old answer",
        baseline_pos=CompetitivePosition.AMONG_OPTIONS,
        latest_text="new answer",
        latest_pos=CompetitivePosition.AMONG_OPTIONS,  # same position
    )

    mapping = {"old answer": base_vec, "new answer": new_vec}
    client = FakeEmb(mapping)
    config = _make_config(threshold=0.85)

    alert_ids = iter(["alert-1"])
    summary = detect_drift(
        conn, client=client, config=config, now=NOW2,
        id_factory=lambda: next(alert_ids),
    )

    assert summary.drifted == 1
    assert summary.compared == 1

    alerts = list_alerts(conn)
    assert len(alerts) == 1
    assert alerts[0].reason.startswith("DRIFT")
    assert "cosine" in alerts[0].reason
    # Tied to the latest response's score_id
    assert alerts[0].score_id == "score_latest_Q1_llm-a"


# ---------------------------------------------------------------------------
# Case 2: identical vectors (cosine == 1.0) + CHANGED position → DRIFT alert
# ---------------------------------------------------------------------------

def test_position_drift_triggers_alert(tmp_path):
    conn = _conn(tmp_path)
    shared_vec = [1.0, 0.0]

    _setup_pair(
        conn,
        question_id="Q2", llm_name="llm-b",
        baseline_text="same text",
        baseline_pos=CompetitivePosition.FIRST_LINE_RECOMMENDED,
        latest_text="same text",   # identical text → cosine == 1.0
        latest_pos=CompetitivePosition.NOT_RECOMMENDED,  # changed!
    )

    mapping = {"same text": shared_vec}
    client = FakeEmb(mapping)
    config = _make_config(threshold=0.85)

    ids = iter(["alert-pos-1"])
    summary = detect_drift(
        conn, client=client, config=config, now=NOW2,
        id_factory=lambda: next(ids),
    )

    assert summary.drifted == 1
    assert summary.compared == 1

    alerts = list_alerts(conn)
    assert len(alerts) == 1
    assert alerts[0].reason.startswith("DRIFT")
    assert "position" in alerts[0].reason
    assert "FIRST_LINE_RECOMMENDED" in alerts[0].reason
    assert "NOT_RECOMMENDED" in alerts[0].reason
    assert alerts[0].score_id == "score_latest_Q2_llm-b"


# ---------------------------------------------------------------------------
# Case 3: identical vectors + same position → NO alert
# ---------------------------------------------------------------------------

def test_no_drift_when_vectors_same_and_position_same(tmp_path):
    conn = _conn(tmp_path)
    shared_vec = [1.0, 0.0]

    _setup_pair(
        conn,
        question_id="Q3", llm_name="llm-c",
        baseline_text="stable answer",
        baseline_pos=CompetitivePosition.AMONG_OPTIONS,
        latest_text="stable answer",  # identical → cosine == 1.0
        latest_pos=CompetitivePosition.AMONG_OPTIONS,  # same
    )

    mapping = {"stable answer": shared_vec}
    client = FakeEmb(mapping)
    config = _make_config(threshold=0.85)

    summary = detect_drift(conn, client=client, config=config, now=NOW2)

    assert summary.drifted == 0
    assert summary.compared == 1
    assert list_alerts(conn) == []


# ---------------------------------------------------------------------------
# Case 4: latest response IS the baseline (no newer response) → skipped
# ---------------------------------------------------------------------------

def test_skips_when_no_newer_response_than_baseline(tmp_path):
    conn = _conn(tmp_path)

    # Insert only the baseline response (scored)
    _insert_response(conn, response_id="only", question_id="Q4", llm_name="llm-d",
                     response_text="only answer",
                     competitive_position=CompetitivePosition.AMONG_OPTIONS.value,
                     timestamp_utc="2026-01-01T00:00:00+00:00")
    _save_score_for(conn, response_id="only", score_id="score-only")
    set_baseline(conn, question_id="Q4", llm_name="llm-d",
                 response_id="only", now=NOW,
                 competitive_position=CompetitivePosition.AMONG_OPTIONS.value)

    mapping = {"only answer": [1.0, 0.0]}
    client = FakeEmb(mapping)
    config = _make_config(threshold=0.85)

    summary = detect_drift(conn, client=client, config=config, now=NOW2)

    assert summary.compared == 0
    assert summary.drifted == 0
    assert list_alerts(conn) == []


# ---------------------------------------------------------------------------
# Edge: both cosine AND position drift → single alert with both reasons
# ---------------------------------------------------------------------------

def test_both_drift_reasons_joined_in_single_alert(tmp_path):
    conn = _conn(tmp_path)
    base_vec = [1.0, 0.0]
    new_vec = [0.0, 1.0]  # cosine == 0.0

    _setup_pair(
        conn,
        question_id="Q5", llm_name="llm-e",
        baseline_text="old text",
        baseline_pos=CompetitivePosition.FIRST_LINE_RECOMMENDED,
        latest_text="new text",
        latest_pos=CompetitivePosition.NOT_MENTIONED,
    )

    mapping = {"old text": base_vec, "new text": new_vec}
    client = FakeEmb(mapping)
    config = _make_config(threshold=0.85)

    ids = iter(["alert-both"])
    summary = detect_drift(
        conn, client=client, config=config, now=NOW2,
        id_factory=lambda: next(ids),
    )

    assert summary.drifted == 1
    assert summary.compared == 1

    alerts = list_alerts(conn)
    assert len(alerts) == 1
    reason = alerts[0].reason
    assert "cosine" in reason
    assert "position" in reason
    # Both halves must be DRIFT-prefixed
    for part in reason.split("; "):
        assert part.startswith("DRIFT")


# ---------------------------------------------------------------------------
# Edge: multiple pairs — only drifted pairs count
# ---------------------------------------------------------------------------

def test_multiple_pairs_only_drifted_ones_counted(tmp_path):
    conn = _conn(tmp_path)

    # Pair A — drifted (cosine < threshold)
    _setup_pair(
        conn, question_id="QA", llm_name="llm-a",
        baseline_text="text-a-base", baseline_pos=CompetitivePosition.AMONG_OPTIONS,
        latest_text="text-a-new",   latest_pos=CompetitivePosition.AMONG_OPTIONS,
    )
    # Pair B — stable
    _setup_pair(
        conn, question_id="QB", llm_name="llm-b",
        baseline_text="stable-b", baseline_pos=CompetitivePosition.SECOND_LINE,
        latest_text="stable-b",  latest_pos=CompetitivePosition.SECOND_LINE,
    )

    mapping = {
        "text-a-base": [1.0, 0.0],
        "text-a-new":  [0.0, 1.0],   # cosine == 0.0 → drift
        "stable-b":    [1.0, 0.0],   # cosine == 1.0 → no drift
    }
    client = FakeEmb(mapping)
    config = _make_config(threshold=0.85)

    summary = detect_drift(conn, client=client, config=config, now=NOW2)

    assert summary.compared == 2
    assert summary.drifted == 1
    alerts = list_alerts(conn)
    assert len(alerts) == 1


# ---------------------------------------------------------------------------
# Immutability proof: frozen position is NOT affected by later re-scores
# ---------------------------------------------------------------------------

def test_frozen_position_anchor_is_truly_immutable(tmp_path):
    """Prove that the detector reads the FROZEN baseline position, not the
    mutable response cache.

    Steps:
    1. Insert a response with competitive_position=FIRST_LINE_RECOMMENDED.
    2. Freeze a baseline pointing to it, capturing the frozen position.
    3. Mutate the response row's competitive_position to NOT_MENTIONED (simulating
       a re-score after the freeze).
    4. Insert a NEW (later-timestamped) response with FIRST_LINE_RECOMMENDED and
       identical text to the baseline (cosine == 1.0, same position as frozen).
    5. Run detect_drift — assert NO position-drift alert fires, because the
       detector compares against the FROZEN FIRST_LINE_RECOMMENDED, not the
       mutated NOT_MENTIONED.
    """
    conn = _conn(tmp_path)
    shared_vec = [1.0, 0.0]

    # Step 1: baseline response
    _insert_response(
        conn,
        response_id="base-resp",
        question_id="Q-frozen",
        llm_name="llm-x",
        response_text="stable answer",
        competitive_position=CompetitivePosition.FIRST_LINE_RECOMMENDED.value,
        timestamp_utc="2026-01-01T00:00:00+00:00",
    )

    # Step 2: freeze — stores FIRST_LINE_RECOMMENDED in drift_baselines
    set_baseline(
        conn,
        question_id="Q-frozen",
        llm_name="llm-x",
        response_id="base-resp",
        now=NOW,
        competitive_position=CompetitivePosition.FIRST_LINE_RECOMMENDED.value,
    )

    # Step 3: mutate the response row — simulate a re-score that changes position
    conn.execute(
        "UPDATE responses SET competitive_position = ? WHERE response_id = ?",
        (CompetitivePosition.NOT_MENTIONED.value, "base-resp"),
    )
    conn.commit()

    # Step 4: newer response with SAME text and SAME position as the frozen baseline
    _insert_response(
        conn,
        response_id="new-resp",
        question_id="Q-frozen",
        llm_name="llm-x",
        response_text="stable answer",   # identical → cosine == 1.0
        competitive_position=CompetitivePosition.FIRST_LINE_RECOMMENDED.value,
        timestamp_utc="2026-05-01T00:00:00+00:00",
    )
    _save_score_for(
        conn,
        response_id="new-resp",
        score_id="score-new",
        position=CompetitivePosition.FIRST_LINE_RECOMMENDED,
    )

    # Step 5: detect — no drift expected
    mapping = {"stable answer": shared_vec}
    client = FakeEmb(mapping)
    config = _make_config(threshold=0.85)

    summary = detect_drift(conn, client=client, config=config, now=NOW2)

    assert summary.compared == 1
    assert summary.drifted == 0, (
        "Position drift alert fired even though new response matches the FROZEN position; "
        "detector must be reading the mutable response cache instead of the frozen baseline."
    )
    assert list_alerts(conn) == []
