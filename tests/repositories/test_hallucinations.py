import sqlite3
from types import SimpleNamespace

import pytest

from ema_poc.db import connect, init_schema
from ema_poc.repositories import hallucinations as H

NOW = "2026-01-01T00:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    # hallucination tables have FKs to responses; insert a minimal parent run+response.
    conn.execute(
        "INSERT INTO runs (run_id, started_at) VALUES ('r1', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        """INSERT INTO responses (response_id, run_id, timestamp_utc, llm_name,
           llm_model_version, persona, question_id, question_text, domain,
           response_text, status, created_at)
           VALUES ('resp1','r1','2026-01-01T00:00:00+00:00','L','m','Provider',
           'Q1','q','General','ans','SUCCESS','2026-01-01T00:00:00+00:00')"""
    )
    conn.commit()
    return conn


# --- save_check / get_check round-trip ---

def test_save_and_get_check(tmp_path):
    conn = _conn(tmp_path)
    H.save_check(
        conn,
        response_id="resp1",
        risk_level="HIGH",
        rationale="Some rationale",
        model="gpt-4",
        now=NOW,
    )
    row = H.get_check(conn, "resp1")
    assert row is not None
    assert row.response_id == "resp1"
    assert row.risk_level == "HIGH"
    assert row.rationale == "Some rationale"
    assert row.model == "gpt-4"
    assert row.created_at == NOW


def test_get_check_returns_none_for_unknown(tmp_path):
    conn = _conn(tmp_path)
    assert H.get_check(conn, "nonexistent") is None


def test_has_check_true_after_save(tmp_path):
    conn = _conn(tmp_path)
    H.save_check(
        conn,
        response_id="resp1",
        risk_level="LOW",
        rationale=None,
        model="claude-3",
        now=NOW,
    )
    assert H.has_check(conn, "resp1") is True


def test_has_check_false_for_unknown(tmp_path):
    conn = _conn(tmp_path)
    assert H.has_check(conn, "unknown-id") is False


def test_save_check_rationale_can_be_none(tmp_path):
    conn = _conn(tmp_path)
    H.save_check(
        conn,
        response_id="resp1",
        risk_level="MEDIUM",
        rationale=None,
        model="claude-3",
        now=NOW,
    )
    row = H.get_check(conn, "resp1")
    assert row.rationale is None


# --- save_flags / list_flags ---

def test_save_flags_with_dicts_and_list_flags(tmp_path):
    conn = _conn(tmp_path)
    flags = [
        {"claim": "Drug X cures Y", "conflicts_with": "Study 2021", "severity": "HIGH"},
        {"claim": "Safe for all ages", "conflicts_with": None, "severity": "LOW"},
    ]
    H.save_flags(
        conn,
        response_id="resp1",
        flags=flags,
        now=NOW,
        id_factory=iter(["f1", "f2"]).__next__,
    )
    rows = H.list_flags(conn, "resp1")
    assert len(rows) == 2
    assert rows[0].flag_id == "f1"
    assert rows[0].claim == "Drug X cures Y"
    assert rows[0].conflicts_with == "Study 2021"
    assert rows[0].severity == "HIGH"
    assert rows[1].flag_id == "f2"
    assert rows[1].claim == "Safe for all ages"
    assert rows[1].conflicts_with is None
    assert rows[1].severity == "LOW"


def test_save_flags_with_objects(tmp_path):
    conn = _conn(tmp_path)
    flags = [
        SimpleNamespace(claim="Claim A", conflicts_with="Ref 1", severity="MEDIUM"),
        SimpleNamespace(claim="Claim B", conflicts_with=None, severity="LOW"),
    ]
    H.save_flags(
        conn,
        response_id="resp1",
        flags=flags,
        now=NOW,
        id_factory=iter(["o1", "o2"]).__next__,
    )
    rows = H.list_flags(conn, "resp1")
    assert len(rows) == 2
    assert rows[0].claim == "Claim A"
    assert rows[0].conflicts_with == "Ref 1"
    assert rows[1].claim == "Claim B"
    assert rows[1].conflicts_with is None


def test_save_flags_empty_is_noop(tmp_path):
    conn = _conn(tmp_path)
    H.save_flags(conn, response_id="resp1", flags=[], now=NOW)
    assert H.list_flags(conn, "resp1") == []


def test_list_flags_returns_empty_for_unknown_response(tmp_path):
    conn = _conn(tmp_path)
    assert H.list_flags(conn, "no-such-response") == []


# --- FK enforcement ---

def test_save_check_fk_rejects_unknown_response(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        H.save_check(
            conn,
            response_id="nope",
            risk_level="HIGH",
            rationale=None,
            model="gpt-4",
            now=NOW,
        )


def test_save_flags_fk_rejects_unknown_response(tmp_path):
    conn = _conn(tmp_path)
    flags = [{"claim": "Bad claim", "conflicts_with": None, "severity": "HIGH"}]
    with pytest.raises(sqlite3.IntegrityError):
        H.save_flags(
            conn,
            response_id="nope",
            flags=flags,
            now=NOW,
            id_factory=iter(["x1"]).__next__,
        )
