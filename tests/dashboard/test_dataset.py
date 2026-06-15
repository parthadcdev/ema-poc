"""Tests for ema_poc.dashboard.dataset.collect_dataset (FR-audience-dashboard)."""

from __future__ import annotations

import json

import pytest

from ema_poc.dashboard.dataset import collect_dataset
from ema_poc.db import connect, init_schema
from ema_poc.models import Alert, Response, Score
from ema_poc.repositories.alerts import save_alert
from ema_poc.repositories.hallucinations import save_check, save_flags
from ema_poc.repositories.responses import save_response
from ema_poc.repositories.runs import create_run
from ema_poc.repositories.scores import save_score

# ---------------------------------------------------------------------------
# Fixed timestamps used throughout
# ---------------------------------------------------------------------------
T1 = "2026-06-13T10:00:00+00:00"
T2 = "2026-06-14T11:00:00+00:00"
T3 = "2026-06-15T12:00:00+00:00"

ABBVIE = ["Skyrizi", "Rinvoq"]
COMPETITORS = ["Humira", "Stelara"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn(tmp_path):
    conn = connect(str(tmp_path / "test.sqlite"))
    init_schema(conn)
    create_run(conn, "run-1", started_at=T1)
    return conn


def _make_response(conn, rid, *, ts, llm_name, brand_focus="Skyrizi",
                   therapeutic_area="Immunology", domain="Efficacy",
                   persona="Provider", text="Some response text."):
    save_response(conn, Response(
        response_id=rid,
        run_id="run-1",
        timestamp_utc=ts,
        llm_name=llm_name,
        llm_model_version="v1",
        persona=persona,
        question_id="Q-001",
        question_text="What is the best treatment?",
        therapeutic_area=therapeutic_area,
        brand_focus=brand_focus,
        domain=domain,
        response_text=text,
        response_tokens=50,
        finish_reason="stop",
        status="SUCCESS",
        created_at=ts,
    ))


def _make_score(conn, score_id, response_id, *, version=1,
                sentiment_score=0.7,
                competitive_position="FIRST_LINE_RECOMMENDED",
                brand_mentions=None,
                scoring_rationale="solid evidence",
                confidence_level="HIGH",
                citation_quality="GOOD"):
    save_score(conn, Score(
        score_id=score_id,
        response_id=response_id,
        version=version,
        sentiment_score=sentiment_score,
        competitive_position=competitive_position,
        brand_mentions=brand_mentions if brand_mentions is not None else ["Skyrizi", "Stelara"],
        key_claims=["claim-1"],
        scoring_rationale=scoring_rationale,
        confidence_level=confidence_level,
        citation_quality=citation_quality,
        scoring_model="claude-opus-4-8",
        created_at=T1,
    ))


# ---------------------------------------------------------------------------
# Fixture: populated DB
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded(tmp_path):
    """Seed a DB with 3 responses; response 'resp-a' has full scoring + hall + alerts."""
    conn = _conn(tmp_path)

    # resp-a: full data — scored, hallucination check/flags, two alerts
    _make_response(conn, "resp-a", ts=T1, llm_name="Claude-3-Grounded",
                   brand_focus="Skyrizi", therapeutic_area="Immunology")

    _make_score(conn, "score-a1", "resp-a",
                sentiment_score=0.85,
                competitive_position="FIRST_LINE_RECOMMENDED",
                brand_mentions=["Skyrizi", "Stelara"],
                scoring_rationale="evidence is strong",
                confidence_level="HIGH",
                citation_quality="EXCELLENT")

    save_check(conn, response_id="resp-a", risk_level="HIGH",
               rationale="Contains speculative claims.", model="verifier-1", now=T1)
    save_flags(conn, response_id="resp-a", flags=[
        {"claim": "Skyrizi cures all", "conflicts_with": "FDA label", "severity": "HIGH"},
        {"claim": "No side effects", "conflicts_with": "clinical data", "severity": "MEDIUM"},
    ], now=T1)

    # Two alerts tied to score-a1
    save_alert(conn, Alert(alert_id="al-drift-1", score_id="score-a1",
                           reason="DRIFT: cosine 0.80 < 0.85", created_at=T1))
    save_alert(conn, Alert(alert_id="al-sent-1", score_id="score-a1",
                           reason="sentiment -0.45 below -0.3 threshold", created_at=T2))

    # resp-b: scored, no hallucination check, no alerts
    _make_response(conn, "resp-b", ts=T2, llm_name="GPT-4o",
                   brand_focus="Rinvoq", therapeutic_area="Rheumatology")
    _make_score(conn, "score-b1", "resp-b",
                sentiment_score=0.2,
                competitive_position="AMONG_OPTIONS",
                brand_mentions=[],
                scoring_rationale="moderate evidence",
                confidence_level="MEDIUM",
                citation_quality="FAIR")

    # resp-c: NO score, NO hallucination check, NO alerts (tests defaults)
    _make_response(conn, "resp-c", ts=T3, llm_name="Gemini-Pro",
                   brand_focus="Skyrizi", therapeutic_area="Oncology")

    return conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCollectDatasetStructure:
    def test_top_level_keys(self, seeded):
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS, now="2026-06-13T00:00:00Z")
        assert set(result.keys()) == {"generated_at", "abbvie_brands", "competitor_brands", "records"}

    def test_generated_at_echoed(self, seeded):
        now = "2026-06-13T00:00:00Z"
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS, now=now)
        assert result["generated_at"] == now

    def test_brands_echoed(self, seeded):
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS)
        assert result["abbvie_brands"] == ABBVIE
        assert result["competitor_brands"] == COMPETITORS

    def test_record_count(self, seeded):
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS)
        assert len(result["records"]) == 3

    def test_records_ordered_by_timestamp_then_response_id(self, seeded):
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS)
        ids = [r["response_id"] for r in result["records"]]
        assert ids == ["resp-a", "resp-b", "resp-c"]

    def test_json_serializable(self, seeded):
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS, now="ts")
        serialized = json.dumps(result)
        assert isinstance(serialized, str)
        # round-trip
        parsed = json.loads(serialized)
        assert len(parsed["records"]) == 3


class TestScoredRecord:
    @pytest.fixture()
    def record_a(self, seeded):
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS)
        return next(r for r in result["records"] if r["response_id"] == "resp-a")

    def test_sentiment_score(self, record_a):
        assert record_a["sentiment_score"] == pytest.approx(0.85)

    def test_competitive_position(self, record_a):
        assert record_a["competitive_position"] == "FIRST_LINE_RECOMMENDED"

    def test_confidence_level(self, record_a):
        assert record_a["confidence_level"] == "HIGH"

    def test_citation_quality(self, record_a):
        assert record_a["citation_quality"] == "EXCELLENT"

    def test_brand_mentions_is_real_list(self, record_a):
        assert record_a["brand_mentions"] == ["Skyrizi", "Stelara"]

    def test_scoring_rationale(self, record_a):
        assert record_a["scoring_rationale"] == "evidence is strong"

    def test_date_derived_from_timestamp(self, record_a):
        assert record_a["date"] == "2026-06-13"

    def test_timestamp_utc(self, record_a):
        assert record_a["timestamp_utc"] == T1

    def test_base_fields(self, record_a):
        assert record_a["persona"] == "Provider"
        assert record_a["question_id"] == "Q-001"
        assert record_a["therapeutic_area"] == "Immunology"
        assert record_a["brand_focus"] == "Skyrizi"
        assert record_a["domain"] == "Efficacy"
        assert record_a["status"] == "SUCCESS"


class TestGroundedFlag:
    def test_grounded_true_for_grounded_llm(self, seeded):
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS)
        rec_a = next(r for r in result["records"] if r["response_id"] == "resp-a")
        assert rec_a["grounded"] is True

    def test_grounded_false_for_non_grounded(self, seeded):
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS)
        rec_b = next(r for r in result["records"] if r["response_id"] == "resp-b")
        rec_c = next(r for r in result["records"] if r["response_id"] == "resp-c")
        assert rec_b["grounded"] is False
        assert rec_c["grounded"] is False


class TestHallucinationFields:
    @pytest.fixture()
    def record_a(self, seeded):
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS)
        return next(r for r in result["records"] if r["response_id"] == "resp-a")

    def test_hallucination_risk(self, record_a):
        assert record_a["hallucination_risk"] == "HIGH"

    def test_hallucination_flags_count(self, record_a):
        assert len(record_a["hallucination_flags"]) == 2

    def test_hallucination_flags_keys(self, record_a):
        for flag in record_a["hallucination_flags"]:
            assert set(flag.keys()) == {"claim", "conflicts_with", "severity"}

    def test_hallucination_flag_values(self, record_a):
        flags = record_a["hallucination_flags"]
        claims = [f["claim"] for f in flags]
        assert "Skyrizi cures all" in claims
        assert "No side effects" in claims

    def test_hallucination_flags_severities(self, record_a):
        flags = {f["claim"]: f for f in record_a["hallucination_flags"]}
        assert flags["Skyrizi cures all"]["severity"] == "HIGH"
        assert flags["No side effects"]["severity"] == "MEDIUM"

    def test_hallucination_flags_conflicts_with(self, record_a):
        flags = {f["claim"]: f for f in record_a["hallucination_flags"]}
        assert flags["Skyrizi cures all"]["conflicts_with"] == "FDA label"
        assert flags["No side effects"]["conflicts_with"] == "clinical data"


class TestAlertFields:
    @pytest.fixture()
    def record_a(self, seeded):
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS)
        return next(r for r in result["records"] if r["response_id"] == "resp-a")

    def test_alert_triggered_true(self, record_a):
        assert record_a["alert_triggered"] is True

    def test_alert_reasons_contains_both(self, record_a):
        reasons = record_a["alert_reasons"]
        assert any(r.startswith("DRIFT:") for r in reasons)
        assert any("sentiment" in r and "threshold" in r for r in reasons)

    def test_alert_reasons_deterministic_order(self, record_a):
        # DRIFT alert was inserted with created_at=T1, sentiment alert with T2
        reasons = record_a["alert_reasons"]
        assert reasons[0] == "DRIFT: cosine 0.80 < 0.85"
        assert reasons[1] == "sentiment -0.45 below -0.3 threshold"

    def test_no_alerts_for_scored_but_unalerted(self, seeded):
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS)
        rec_b = next(r for r in result["records"] if r["response_id"] == "resp-b")
        assert rec_b["alert_reasons"] == []
        assert rec_b["alert_triggered"] is False


class TestUnscoredRecord:
    @pytest.fixture()
    def record_c(self, seeded):
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS)
        return next(r for r in result["records"] if r["response_id"] == "resp-c")

    def test_sentiment_score_none(self, record_c):
        assert record_c["sentiment_score"] is None

    def test_competitive_position_none(self, record_c):
        assert record_c["competitive_position"] is None

    def test_confidence_level_none(self, record_c):
        assert record_c["confidence_level"] is None

    def test_citation_quality_none(self, record_c):
        assert record_c["citation_quality"] is None

    def test_brand_mentions_empty_list(self, record_c):
        assert record_c["brand_mentions"] == []

    def test_scoring_rationale_none(self, record_c):
        assert record_c["scoring_rationale"] is None

    def test_hallucination_risk_none(self, record_c):
        assert record_c["hallucination_risk"] is None

    def test_hallucination_flags_empty(self, record_c):
        assert record_c["hallucination_flags"] == []

    def test_alert_reasons_empty(self, record_c):
        assert record_c["alert_reasons"] == []

    def test_alert_triggered_false(self, record_c):
        assert record_c["alert_triggered"] is False


class TestExactKeyContract:
    """Verify every record has exactly the 24 required keys."""

    REQUIRED_KEYS = {
        "response_id", "source", "timestamp_utc", "date", "llm_name", "grounded",
        "persona", "question_id", "question_text", "therapeutic_area",
        "brand_focus", "domain", "status", "response_text",
        "sentiment_score", "competitive_position", "confidence_level",
        "citation_quality", "brand_mentions", "scoring_rationale",
        "hallucination_risk", "hallucination_flags",
        "alert_reasons", "alert_triggered",
    }

    def test_all_records_have_exact_keys(self, seeded):
        result = collect_dataset(seeded, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS)
        for rec in result["records"]:
            assert set(rec.keys()) == self.REQUIRED_KEYS, (
                f"Key mismatch for {rec.get('response_id')}: "
                f"extra={set(rec.keys()) - self.REQUIRED_KEYS}, "
                f"missing={self.REQUIRED_KEYS - set(rec.keys())}"
            )


class TestMultipleVersionsPickLatest:
    """When a response has multiple score versions, only the latest is used."""

    def test_latest_version_wins(self, tmp_path):
        conn = _conn(tmp_path)
        _make_response(conn, "resp-x", ts=T1, llm_name="GPT-4o")

        # version 1 — low sentiment
        _make_score(conn, "score-x1", "resp-x", version=1,
                    sentiment_score=0.1,
                    competitive_position="NOT_RECOMMENDED",
                    brand_mentions=["OldBrand"],
                    scoring_rationale="old")

        # version 2 — higher sentiment (should win)
        _make_score(conn, "score-x2", "resp-x", version=2,
                    sentiment_score=0.9,
                    competitive_position="FIRST_LINE_RECOMMENDED",
                    brand_mentions=["NewBrand"],
                    scoring_rationale="updated")

        result = collect_dataset(conn, abbvie_brands=ABBVIE, competitor_brands=COMPETITORS)
        rec = result["records"][0]
        assert rec["sentiment_score"] == pytest.approx(0.9)
        assert rec["competitive_position"] == "FIRST_LINE_RECOMMENDED"
        assert rec["brand_mentions"] == ["NewBrand"]
        assert rec["scoring_rationale"] == "updated"


class TestEmptyDatabase:
    def test_empty_db_returns_empty_records(self, tmp_path):
        conn = _conn(tmp_path)
        result = collect_dataset(conn, abbvie_brands=ABBVIE,
                                 competitor_brands=COMPETITORS, now="t")
        assert result["records"] == []
        assert result["abbvie_brands"] == ABBVIE
        assert result["competitor_brands"] == COMPETITORS
        assert result["generated_at"] == "t"
        assert json.dumps(result)  # serializable


class TestBrandMentionsEdgeCases:
    """brand_mentions stored as various JSON text forms → always parsed to list."""

    def test_empty_json_array_brand_mentions(self, tmp_path):
        conn = _conn(tmp_path)
        _make_response(conn, "resp-y", ts=T1, llm_name="GPT-4o")
        _make_score(conn, "score-y1", "resp-y", brand_mentions=[])
        result = collect_dataset(conn, abbvie_brands=ABBVIE, competitor_brands=COMPETITORS)
        assert result["records"][0]["brand_mentions"] == []

    def test_multiple_brand_mentions(self, tmp_path):
        conn = _conn(tmp_path)
        _make_response(conn, "resp-z", ts=T1, llm_name="GPT-4o")
        _make_score(conn, "score-z1", "resp-z",
                    brand_mentions=["Alpha", "Beta", "Gamma"])
        result = collect_dataset(conn, abbvie_brands=ABBVIE, competitor_brands=COMPETITORS)
        assert result["records"][0]["brand_mentions"] == ["Alpha", "Beta", "Gamma"]
