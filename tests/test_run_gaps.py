"""Tests for find_run_gaps and format_gaps_report."""

from __future__ import annotations

import pytest

from ema_poc.db import connect, init_schema
from ema_poc.run_gaps import find_run_gaps, format_gaps_report


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def _seed(conn):
    """Seed canonical test data:
    r1 COMPLETED 2026-06-01 (no backfill) → covers 2026-06-01
    r2 COMPLETED 2026-06-04, backfill_for=2026-06-02 → covers 2026-06-02
    r3 BUDGET_EXCEEDED 2026-06-03 → covers nothing
    """
    conn.execute(
        "INSERT INTO runs (run_id, started_at, status, backfill_for) VALUES (?,?,?,?)",
        ("r1", "2026-06-01T08:00:00+00:00", "COMPLETED", None),
    )
    conn.execute(
        "INSERT INTO runs (run_id, started_at, status, backfill_for) VALUES (?,?,?,?)",
        ("r2", "2026-06-04T08:00:00+00:00", "COMPLETED", "2026-06-02"),
    )
    conn.execute(
        "INSERT INTO runs (run_id, started_at, status, backfill_for) VALUES (?,?,?,?)",
        ("r3", "2026-06-03T08:00:00+00:00", "BUDGET_EXCEEDED", None),
    )
    conn.commit()


class TestFindRunGaps:
    def test_gaps_with_mixed_statuses(self, tmp_path):
        conn = _conn(tmp_path)
        _seed(conn)
        gaps = find_run_gaps(conn, start="2026-06-01", end="2026-06-04")
        # 01 covered by r1; 02 covered by r2's backfill_for; 03 BUDGET_EXCEEDED → gap; 04 never completed → gap
        assert gaps == ["2026-06-03", "2026-06-04"]
        conn.close()

    def test_all_covered_returns_empty(self, tmp_path):
        conn = _conn(tmp_path)
        _seed(conn)
        gaps = find_run_gaps(conn, start="2026-06-01", end="2026-06-02")
        assert gaps == []
        conn.close()

    def test_window_before_any_run_returns_all_dates(self, tmp_path):
        conn = _conn(tmp_path)
        _seed(conn)
        gaps = find_run_gaps(conn, start="2026-05-01", end="2026-05-03")
        assert gaps == ["2026-05-01", "2026-05-02", "2026-05-03"]
        conn.close()

    def test_single_day_covered_returns_empty(self, tmp_path):
        conn = _conn(tmp_path)
        _seed(conn)
        gaps = find_run_gaps(conn, start="2026-06-01", end="2026-06-01")
        assert gaps == []
        conn.close()

    def test_gaps_are_ascending(self, tmp_path):
        conn = _conn(tmp_path)
        _seed(conn)
        gaps = find_run_gaps(conn, start="2026-06-01", end="2026-06-04")
        assert gaps == sorted(gaps)
        conn.close()

    def test_failed_run_does_not_cover(self, tmp_path):
        conn = _conn(tmp_path)
        conn.execute(
            "INSERT INTO runs (run_id, started_at, status, backfill_for) VALUES (?,?,?,?)",
            ("f1", "2026-06-10T08:00:00+00:00", "FAILED", None),
        )
        conn.commit()
        gaps = find_run_gaps(conn, start="2026-06-10", end="2026-06-10")
        assert gaps == ["2026-06-10"]
        conn.close()

    def test_running_run_does_not_cover(self, tmp_path):
        conn = _conn(tmp_path)
        conn.execute(
            "INSERT INTO runs (run_id, started_at, status, backfill_for) VALUES (?,?,?,?)",
            ("x1", "2026-06-10T08:00:00+00:00", "RUNNING", None),
        )
        conn.commit()
        gaps = find_run_gaps(conn, start="2026-06-10", end="2026-06-10")
        assert gaps == ["2026-06-10"]
        conn.close()

    def test_no_runs_at_all(self, tmp_path):
        conn = _conn(tmp_path)
        gaps = find_run_gaps(conn, start="2026-06-01", end="2026-06-03")
        assert gaps == ["2026-06-01", "2026-06-02", "2026-06-03"]
        conn.close()


class TestFormatGapsReport:
    def test_empty_gaps(self):
        report = format_gaps_report([], "2026-06-01", "2026-06-04")
        assert report == "No run gaps between 2026-06-01 and 2026-06-04."

    def test_non_empty_gaps_contains_count(self):
        report = format_gaps_report(["2026-06-03", "2026-06-04"], "2026-06-01", "2026-06-04")
        assert "2 uncovered" in report

    def test_non_empty_gaps_contains_dates(self):
        report = format_gaps_report(["2026-06-03", "2026-06-04"], "2026-06-01", "2026-06-04")
        assert "2026-06-03" in report
        assert "2026-06-04" in report

    def test_non_empty_gaps_contains_backfill_hint(self):
        report = format_gaps_report(["2026-06-03", "2026-06-04"], "2026-06-01", "2026-06-04")
        assert "Backfill each with" in report
