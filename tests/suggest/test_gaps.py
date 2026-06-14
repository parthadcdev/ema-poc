"""Tests for ema_poc.suggest.gaps — coverage matrix + effectiveness gap analysis."""

from __future__ import annotations

import sqlite3

from ema_poc.db import init_schema
from ema_poc.repositories.questions import add_question, approve_question
from ema_poc.suggest.gaps import DOMAINS, PERSONAS, Cell, GapReport, analyze_gaps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


def _seed_approved(conn, *, question_id, brand, persona, domain,
                   question_text="Test question?"):
    add_question(
        conn,
        question_id=question_id,
        question_text=question_text,
        persona=persona,
        domain=domain,
        brand_focus=brand,
    )
    approve_question(conn, question_id, "test-approver")


def _insert_scored_response(conn, *, response_id, question_id, question_text,
                             brand_focus, competitive_position):
    conn.execute(
        """
        INSERT INTO runs (run_id, started_at, status)
        VALUES ('run-gap-test', '2024-01-01T00:00:00Z', 'DONE')
        ON CONFLICT(run_id) DO NOTHING
        """,
    )
    conn.execute(
        """
        INSERT INTO responses (
            response_id, run_id, timestamp_utc, llm_name, llm_model_version,
            persona, question_id, question_text, brand_focus, domain,
            response_text, status, competitive_position, created_at
        ) VALUES (?, 'run-gap-test', '2024-01-01T00:00:00Z', 'gpt-4o', 'gpt-4o',
                  'Provider', ?, ?, ?, 'Efficacy', 'some response text',
                  'SUCCESS', ?, '2024-01-01T00:00:00Z')
        """,
        (response_id, question_id, question_text, brand_focus,
         competitive_position),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# under_covered tests
# ---------------------------------------------------------------------------

class TestUnderCovered:
    def test_covered_cell_excluded_from_under_covered(self):
        """A cell with at least one active+approved question should not appear in under_covered."""
        conn = _make_conn()
        _seed_approved(conn, question_id="Q1", brand="Skyrizi",
                       persona="Provider", domain="Efficacy")

        report = analyze_gaps(conn, abbvie_brands=["Skyrizi"])

        covered_tuples = {(c.brand, c.persona, c.domain) for c in report.under_covered}
        assert ("Skyrizi", "Provider", "Efficacy") not in covered_tuples

    def test_empty_cell_appears_in_under_covered(self):
        """A brand×persona×domain combination with no questions is under_covered."""
        conn = _make_conn()
        # Cover only (Skyrizi, Provider, Efficacy)
        _seed_approved(conn, question_id="Q1", brand="Skyrizi",
                       persona="Provider", domain="Efficacy")

        report = analyze_gaps(conn, abbvie_brands=["Skyrizi"])

        covered_tuples = {(c.brand, c.persona, c.domain) for c in report.under_covered}
        # (Skyrizi, Patient, Access) has no coverage
        assert ("Skyrizi", "Patient", "Access") in covered_tuples

    def test_multiple_brands_multiple_covered_cells(self):
        """Covering cells for two brands; only covered cells excluded."""
        conn = _make_conn()
        # Cover (Skyrizi, Provider, Efficacy) and (Rinvoq, Patient, Safety)
        _seed_approved(conn, question_id="Q1", brand="Skyrizi",
                       persona="Provider", domain="Efficacy")
        _seed_approved(conn, question_id="Q2", brand="Rinvoq",
                       persona="Patient", domain="Safety")

        report = analyze_gaps(conn, abbvie_brands=["Skyrizi", "Rinvoq"])

        covered_tuples = {(c.brand, c.persona, c.domain) for c in report.under_covered}
        assert ("Skyrizi", "Provider", "Efficacy") not in covered_tuples
        assert ("Rinvoq", "Patient", "Safety") not in covered_tuples
        # Other cells are still under-covered
        assert ("Skyrizi", "Patient", "Access") in covered_tuples
        assert ("Rinvoq", "Prospect", "General") in covered_tuples

    def test_brand_with_no_questions_has_all_15_cells_under_covered(self):
        """A brand with zero questions should generate all 15 (3 personas × 5 domains) under_covered cells."""
        conn = _make_conn()

        report = analyze_gaps(conn, abbvie_brands=["Rinvoq"])

        rinvoq_cells = [c for c in report.under_covered if c.brand == "Rinvoq"]
        assert len(rinvoq_cells) == len(PERSONAS) * len(DOMAINS)  # 15
        # All counts should be 0
        assert all(c.count == 0 for c in rinvoq_cells)

    def test_cell_count_is_zero_for_under_covered(self):
        """All under_covered cells have count == 0."""
        conn = _make_conn()
        _seed_approved(conn, question_id="Q1", brand="Skyrizi",
                       persona="Provider", domain="Efficacy")

        report = analyze_gaps(conn, abbvie_brands=["Skyrizi"])

        assert all(c.count == 0 for c in report.under_covered)

    def test_inactive_questions_not_counted(self):
        """Questions that are not active are excluded from coverage counts."""
        conn = _make_conn()
        # Add then deactivate a question
        add_question(conn, question_id="Q1", question_text="Test?",
                     persona="Provider", domain="Efficacy", brand_focus="Skyrizi")
        approve_question(conn, "Q1", "approver")
        from ema_poc.repositories.questions import deactivate_question
        deactivate_question(conn, "Q1")

        report = analyze_gaps(conn, abbvie_brands=["Skyrizi"])

        covered_tuples = {(c.brand, c.persona, c.domain) for c in report.under_covered}
        # Deactivated question should not count as coverage
        assert ("Skyrizi", "Provider", "Efficacy") in covered_tuples

    def test_pending_questions_not_counted(self):
        """Questions in PENDING approval status are excluded from coverage counts."""
        conn = _make_conn()
        # Add but do NOT approve
        add_question(conn, question_id="Q1", question_text="Test?",
                     persona="Provider", domain="Efficacy", brand_focus="Skyrizi")

        report = analyze_gaps(conn, abbvie_brands=["Skyrizi"])

        covered_tuples = {(c.brand, c.persona, c.domain) for c in report.under_covered}
        # PENDING question should not count as coverage
        assert ("Skyrizi", "Provider", "Efficacy") in covered_tuples

    def test_empty_brands_list_produces_no_under_covered(self):
        """No brands → no cells to analyze."""
        conn = _make_conn()
        report = analyze_gaps(conn, abbvie_brands=[])
        assert report.under_covered == []

    def test_returns_gap_report_instance(self):
        """analyze_gaps returns a GapReport."""
        conn = _make_conn()
        report = analyze_gaps(conn, abbvie_brands=["Skyrizi"])
        assert isinstance(report, GapReport)

    def test_cells_are_cell_instances(self):
        """Items in under_covered are Cell dataclass instances."""
        conn = _make_conn()
        report = analyze_gaps(conn, abbvie_brands=["Skyrizi"])
        assert all(isinstance(c, Cell) for c in report.under_covered)


# ---------------------------------------------------------------------------
# low_value tests
# ---------------------------------------------------------------------------

class TestLowValue:
    def test_no_scored_data_returns_empty_low_value(self):
        """With no scored responses, low_value should be empty."""
        conn = _make_conn()
        report = analyze_gaps(conn, abbvie_brands=["Skyrizi"])
        assert report.low_value == []

    def test_low_value_question_appears_in_report(self):
        """A question with >= 3 scored responses all NOT_MENTIONED is flagged low_value."""
        conn = _make_conn()
        q_text = "Does Skyrizi help with plaque psoriasis?"
        # Seed 3 NOT_MENTIONED responses for Q-LV
        for i in range(3):
            _insert_scored_response(
                conn,
                response_id=f"r-lv-{i}",
                question_id="Q-LV",
                question_text=q_text,
                brand_focus="Skyrizi",
                competitive_position="NOT_MENTIONED",
            )

        report = analyze_gaps(conn, abbvie_brands=["Skyrizi"])

        lv_ids = [item["question_id"] for item in report.low_value]
        assert "Q-LV" in lv_ids

    def test_low_value_dict_has_required_keys(self):
        """Each low_value entry has question_id, brand_focus, question_text, not_mentioned_rate."""
        conn = _make_conn()
        q_text = "What are Rinvoq's side effects?"
        for i in range(3):
            _insert_scored_response(
                conn,
                response_id=f"r-rv-{i}",
                question_id="Q-RV",
                question_text=q_text,
                brand_focus="Rinvoq",
                competitive_position="NOT_MENTIONED",
            )

        report = analyze_gaps(conn, abbvie_brands=["Rinvoq"])

        assert len(report.low_value) >= 1
        entry = next(e for e in report.low_value if e["question_id"] == "Q-RV")
        assert entry["brand_focus"] == "Rinvoq"
        assert entry["question_text"] == q_text
        assert abs(entry["not_mentioned_rate"] - 1.0) < 1e-9

    def test_non_low_value_question_excluded(self):
        """A question below the NOT_MENTIONED threshold does not appear in low_value."""
        conn = _make_conn()
        # 1 out of 3 NOT_MENTIONED => 33% => not low_value
        _insert_scored_response(
            conn, response_id="r-ok-0", question_id="Q-OK",
            question_text="Is Skyrizi good?", brand_focus="Skyrizi",
            competitive_position="NOT_MENTIONED",
        )
        for i in range(2):
            _insert_scored_response(
                conn, response_id=f"r-ok-{i+1}", question_id="Q-OK",
                question_text="Is Skyrizi good?", brand_focus="Skyrizi",
                competitive_position="FIRST_LINE_RECOMMENDED",
            )

        report = analyze_gaps(conn, abbvie_brands=["Skyrizi"])

        lv_ids = [item["question_id"] for item in report.low_value]
        assert "Q-OK" not in lv_ids

    def test_question_below_min_responses_not_low_value(self):
        """A question with only 2 scored responses (< min_responses=3) is not low_value."""
        conn = _make_conn()
        for i in range(2):
            _insert_scored_response(
                conn, response_id=f"r-few-{i}", question_id="Q-FEW",
                question_text="Is Skyrizi mentioned?", brand_focus="Skyrizi",
                competitive_position="NOT_MENTIONED",
            )

        report = analyze_gaps(conn, abbvie_brands=["Skyrizi"])

        lv_ids = [item["question_id"] for item in report.low_value]
        assert "Q-FEW" not in lv_ids

    def test_low_value_not_mentioned_rate_correct(self):
        """The not_mentioned_rate in the low_value dict is accurate."""
        conn = _make_conn()
        # 4 NOT_MENTIONED out of 5 = 80%
        for i in range(4):
            _insert_scored_response(
                conn, response_id=f"r-rate-nm-{i}", question_id="Q-RATE",
                question_text="Rate question?", brand_focus="Skyrizi",
                competitive_position="NOT_MENTIONED",
            )
        _insert_scored_response(
            conn, response_id="r-rate-ok", question_id="Q-RATE",
            question_text="Rate question?", brand_focus="Skyrizi",
            competitive_position="AMONG_OPTIONS",
        )

        report = analyze_gaps(conn, abbvie_brands=["Skyrizi"])

        entry = next((e for e in report.low_value if e["question_id"] == "Q-RATE"), None)
        assert entry is not None
        assert abs(entry["not_mentioned_rate"] - 0.8) < 1e-9
