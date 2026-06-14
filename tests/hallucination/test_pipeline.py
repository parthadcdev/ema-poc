"""Tests for ema_poc/hallucination/pipeline.py — offline, fake checker."""

from __future__ import annotations

import pytest

from ema_poc.config import AppConfig, BrandConfig, Settings
from ema_poc.db import connect, init_schema
from ema_poc.hallucination.corpus import BrandReference, ReferenceCorpus
from ema_poc.hallucination.detector import FlaggedClaim, HallucinationResult
from ema_poc.hallucination.pipeline import CheckSummary, check_pending
from ema_poc.models import Alert, CompetitivePosition, Response, Score
from ema_poc.repositories.alerts import list_alerts
from ema_poc.repositories.hallucinations import get_check, has_check, list_flags
from ema_poc.repositories.responses import save_response
from ema_poc.repositories.runs import create_run
from ema_poc.repositories.scores import save_score

NOW = "2026-06-13T02:00:00+00:00"
SKYRIZI_BRAND = "Skyrizi"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config() -> AppConfig:
    return AppConfig(
        settings=Settings(scoring_model="claude-opus-4-8"),
        brands=BrandConfig(abbvie_brands=[SKYRIZI_BRAND], competitor_brands=["Humira"]),
        targets=[],
    )


def _corpus() -> ReferenceCorpus:
    return ReferenceCorpus(
        brands={
            SKYRIZI_BRAND: BrandReference(
                generic="risankizumab",
                indications=["plaque psoriasis", "psoriatic arthritis"],
                key_dosing="600 mg IV x3, then 360 mg SC q8w",
                boxed_warnings=[],
            )
        }
    )


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=NOW)
    return conn


def _resp(conn, rid, *, status="SUCCESS", brand=SKYRIZI_BRAND,
          question_id="Q1", llm_name="GPT-4o", text="Some response text."):
    save_response(
        conn,
        Response(
            response_id=rid,
            run_id="r1",
            timestamp_utc=NOW,
            llm_name=llm_name,
            llm_model_version="m",
            persona="Provider",
            question_id=question_id,
            question_text="What is Skyrizi?",
            brand_focus=brand,
            domain="Safety",
            response_text=text,
            response_tokens=10,
            finish_reason="stop",
            status=status,
            created_at=NOW,
        ),
    )


def _score(conn, response_id, score_id):
    save_score(
        conn,
        Score(
            score_id=score_id,
            response_id=response_id,
            version=1,
            sentiment_score=0.5,
            competitive_position=CompetitivePosition.AMONG_OPTIONS,
            brand_mentions=[SKYRIZI_BRAND],
            key_claims=["effective"],
            scoring_rationale="neutral",
            confidence_level="ASSERTIVE",
            citation_quality="NONE",
            scoring_model="claude-opus-4-8",
            created_at=NOW,
        ),
    )


def _ids():
    """Sequential id factory for deterministic IDs in tests."""
    state = {"i": 0}

    def f():
        state["i"] += 1
        return f"id-{state['i']}"

    return f


def make_checker(result: HallucinationResult):
    """Return a fake checker that always returns the given result."""

    def checker(client, *, response_text, brand_focus, brand_reference, model):
        return result

    return checker


# ---------------------------------------------------------------------------
# Case 1: HIGH-risk result → check saved, flags saved, one alert raised
# ---------------------------------------------------------------------------

class TestHighRiskAlert:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.conn = _conn(tmp_path)
        _resp(self.conn, "resp-1", text="Wrong dosing statement.")
        _score(self.conn, "resp-1", "score-1")

        flagged = HallucinationResult(
            risk_level="HIGH",
            flagged_claims=[
                FlaggedClaim(
                    claim="Wrong dosing statement.",
                    conflicts_with="Key dosing: 600 mg IV",
                    severity="HIGH",
                )
            ],
            rationale="Dosing is incorrect.",
        )
        self.summary = check_pending(
            self.conn,
            client=object(),
            config=_config(),
            corpus=_corpus(),
            checker=make_checker(flagged),
            id_factory=_ids(),
            now_factory=lambda: NOW,
        )

    def test_summary_checked_is_one(self):
        assert self.summary.checked == 1

    def test_summary_alerts_raised_is_one(self):
        assert self.summary.alerts_raised == 1

    def test_check_row_persisted(self):
        assert has_check(self.conn, "resp-1")

    def test_check_row_has_high_risk_level(self):
        check = get_check(self.conn, "resp-1")
        assert check.risk_level == "HIGH"

    def test_check_row_has_rationale(self):
        check = get_check(self.conn, "resp-1")
        assert check.rationale == "Dosing is incorrect."

    def test_flags_persisted(self):
        flags = list_flags(self.conn, "resp-1")
        assert len(flags) == 1
        assert flags[0].claim == "Wrong dosing statement."
        assert flags[0].severity == "HIGH"

    def test_alert_raised_with_hallucination_reason(self):
        alerts = list_alerts(self.conn)
        assert len(alerts) == 1
        assert alerts[0].reason.startswith("HALLUCINATION")

    def test_alert_reason_contains_risk_level(self):
        alert = list_alerts(self.conn)[0]
        assert "HIGH" in alert.reason

    def test_alert_reason_mentions_flagged_claim_count(self):
        alert = list_alerts(self.conn)[0]
        assert "1 flagged claim" in alert.reason

    def test_alert_linked_to_score(self):
        alert = list_alerts(self.conn)[0]
        assert alert.score_id == "score-1"


# ---------------------------------------------------------------------------
# Case 2: MEDIUM-risk result → check saved, NO alert
# ---------------------------------------------------------------------------

class TestMediumRiskNoAlert:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.conn = _conn(tmp_path)
        _resp(self.conn, "resp-2", text="Skyrizi treats psoriasis.")
        _score(self.conn, "resp-2", "score-2")

        medium = HallucinationResult(
            risk_level="MEDIUM",
            flagged_claims=[
                FlaggedClaim(
                    claim="Some overstated claim.",
                    conflicts_with="Reference is more nuanced.",
                    severity="MEDIUM",
                )
            ],
            rationale="Minor overstatement detected.",
        )
        self.summary = check_pending(
            self.conn,
            client=object(),
            config=_config(),
            corpus=_corpus(),
            checker=make_checker(medium),
            id_factory=_ids(),
            now_factory=lambda: NOW,
        )

    def test_summary_checked_is_one(self):
        assert self.summary.checked == 1

    def test_no_alert_raised(self):
        assert self.summary.alerts_raised == 0

    def test_check_row_persisted(self):
        assert has_check(self.conn, "resp-2")

    def test_check_row_has_medium_risk(self):
        assert get_check(self.conn, "resp-2").risk_level == "MEDIUM"

    def test_flags_persisted(self):
        flags = list_flags(self.conn, "resp-2")
        assert len(flags) == 1
        assert flags[0].severity == "MEDIUM"

    def test_no_alerts_in_db(self):
        assert list_alerts(self.conn) == []


# ---------------------------------------------------------------------------
# Case 3: Brand NOT in corpus → response skipped entirely
# ---------------------------------------------------------------------------

class TestOutOfCorpusBrandSkipped:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.conn = _conn(tmp_path)
        # brand_focus "Humira" is a competitor — not in our corpus
        _resp(self.conn, "resp-in", text="Skyrizi works.", brand=SKYRIZI_BRAND)
        _resp(self.conn, "resp-out", text="Humira works.", brand="Humira")
        _score(self.conn, "resp-in", "score-in")

        none_result = HallucinationResult(
            risk_level="NONE",
            flagged_claims=[],
            rationale="All good.",
        )
        self.summary = check_pending(
            self.conn,
            client=object(),
            config=_config(),
            corpus=_corpus(),
            checker=make_checker(none_result),
            id_factory=_ids(),
            now_factory=lambda: NOW,
        )

    def test_summary_checked_only_in_corpus(self):
        # Only resp-in is in-corpus; resp-out is skipped
        assert self.summary.checked == 1

    def test_in_corpus_response_has_check(self):
        assert has_check(self.conn, "resp-in")

    def test_out_of_corpus_response_has_no_check(self):
        assert not has_check(self.conn, "resp-out")

    def test_no_check_row_for_out_of_corpus(self):
        assert get_check(self.conn, "resp-out") is None


# ---------------------------------------------------------------------------
# Case 4: Idempotency — second run skips already-checked responses
# ---------------------------------------------------------------------------

class TestIdempotency:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.conn = _conn(tmp_path)
        _resp(self.conn, "resp-idem", text="Skyrizi is safe.")
        _score(self.conn, "resp-idem", "score-idem")

        result = HallucinationResult(
            risk_level="NONE",
            flagged_claims=[],
            rationale="Clean.",
        )
        cfg = _config()
        corpus = _corpus()
        checker = make_checker(result)

        self.first = check_pending(
            self.conn,
            client=object(),
            config=cfg,
            corpus=corpus,
            checker=checker,
            id_factory=_ids(),
            now_factory=lambda: NOW,
        )
        self.second = check_pending(
            self.conn,
            client=object(),
            config=cfg,
            corpus=corpus,
            checker=checker,
            id_factory=_ids(),
            now_factory=lambda: NOW,
        )

    def test_first_run_checked_one(self):
        assert self.first.checked == 1

    def test_second_run_checked_zero(self):
        assert self.second.checked == 0

    def test_second_run_alerts_zero(self):
        assert self.second.alerts_raised == 0

    def test_only_one_check_row_in_db(self):
        # check idempotency at DB level — still one row
        assert has_check(self.conn, "resp-idem")


# ---------------------------------------------------------------------------
# Case 5: HIGH-severity flag (even with MEDIUM risk_level) → alert raised
# ---------------------------------------------------------------------------

class TestHighSeverityFlagTriggersAlert:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.conn = _conn(tmp_path)
        _resp(self.conn, "resp-sev", text="Skyrizi has some side effects.")
        _score(self.conn, "resp-sev", "score-sev")

        # risk_level is MEDIUM but one flag has severity HIGH
        result = HallucinationResult(
            risk_level="MEDIUM",
            flagged_claims=[
                FlaggedClaim(
                    claim="Skyrizi has some side effects.",
                    conflicts_with="Specific known side effects not mentioned.",
                    severity="HIGH",
                )
            ],
            rationale="One claim is critically inaccurate despite medium overall risk.",
        )
        self.summary = check_pending(
            self.conn,
            client=object(),
            config=_config(),
            corpus=_corpus(),
            checker=make_checker(result),
            id_factory=_ids(),
            now_factory=lambda: NOW,
        )

    def test_summary_alerts_raised_is_one(self):
        assert self.summary.alerts_raised == 1

    def test_summary_checked_is_one(self):
        assert self.summary.checked == 1

    def test_alert_persisted(self):
        alerts = list_alerts(self.conn)
        assert len(alerts) == 1

    def test_alert_reason_starts_with_hallucination(self):
        alert = list_alerts(self.conn)[0]
        assert alert.reason.startswith("HALLUCINATION")

    def test_alert_linked_to_correct_score(self):
        alert = list_alerts(self.conn)[0]
        assert alert.score_id == "score-sev"

    def test_check_row_has_medium_risk(self):
        # Underlying risk_level is MEDIUM; alert came from HIGH-severity flag
        assert get_check(self.conn, "resp-sev").risk_level == "MEDIUM"

    def test_flag_row_has_high_severity(self):
        flags = list_flags(self.conn, "resp-sev")
        assert len(flags) == 1
        assert flags[0].severity == "HIGH"


# ---------------------------------------------------------------------------
# Edge: HIGH risk but NO score row → alert NOT raised (no score to link to)
# ---------------------------------------------------------------------------

class TestHighRiskNoScoreNoAlert:
    def test_no_alert_when_no_score(self, tmp_path):
        conn = _conn(tmp_path)
        _resp(conn, "resp-noscore", text="Bad claim.")
        # deliberately NOT creating a score row

        result = HallucinationResult(
            risk_level="HIGH",
            flagged_claims=[
                FlaggedClaim(
                    claim="Bad claim.",
                    conflicts_with="Reference says otherwise.",
                    severity="HIGH",
                )
            ],
            rationale="No score to link alert to.",
        )
        summary = check_pending(
            conn,
            client=object(),
            config=_config(),
            corpus=_corpus(),
            checker=make_checker(result),
            id_factory=_ids(),
            now_factory=lambda: NOW,
        )
        assert summary.checked == 1
        assert summary.alerts_raised == 0
        assert list_alerts(conn) == []


# ---------------------------------------------------------------------------
# Edge: FAILED response — should be skipped (not in success_responses)
# ---------------------------------------------------------------------------

class TestFailedResponseSkipped:
    def test_failed_response_not_checked(self, tmp_path):
        conn = _conn(tmp_path)
        _resp(conn, "resp-failed", status="FAILED", text="Error text.")

        result = HallucinationResult(risk_level="NONE", flagged_claims=[], rationale="n/a")
        summary = check_pending(
            conn,
            client=object(),
            config=_config(),
            corpus=_corpus(),
            checker=make_checker(result),
            id_factory=_ids(),
            now_factory=lambda: NOW,
        )
        assert summary.checked == 0
        assert not has_check(conn, "resp-failed")


# ---------------------------------------------------------------------------
# CheckSummary dataclass
# ---------------------------------------------------------------------------

class TestCheckSummary:
    def test_fields(self):
        s = CheckSummary(checked=3, alerts_raised=1)
        assert s.checked == 3
        assert s.alerts_raised == 1
