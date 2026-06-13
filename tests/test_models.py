import pytest
from pydantic import ValidationError

from ema_poc.models import (
    Question,
    Response,
    Run,
    Score,
    Alert,
    Persona,
    Domain,
    ApprovalStatus,
    ResponseStatus,
    CompetitivePosition,
)


def test_question_valid():
    q = Question(
        question_id="Q1",
        question_text="Is drug X first-line for condition Y?",
        persona=Persona.PROVIDER,
        domain=Domain.COMPARATIVE,
    )
    assert q.version == 1
    assert q.active is True
    assert q.approval_status is ApprovalStatus.PENDING


def test_question_rejects_bad_persona():
    with pytest.raises(ValidationError):
        Question(
            question_id="Q1",
            question_text="text",
            persona="Doctor",  # not a valid Persona
            domain=Domain.GENERAL,
        )


def test_response_defaults_and_enum():
    r = Response(
        response_id="r-1",
        run_id="run-1",
        timestamp_utc="2026-06-13T02:00:00+00:00",
        llm_name="GPT-4o",
        llm_model_version="gpt-4o-2024-11-20",
        persona=Persona.PATIENT,
        question_id="Q1",
        question_text="text",
        domain=Domain.SAFETY,
        response_text="some answer",
        status=ResponseStatus.SUCCESS,
    )
    assert r.alert_triggered is False
    assert r.sentiment_score is None


def test_score_sentiment_bounds():
    with pytest.raises(ValidationError):
        Score(
            score_id="s-1",
            response_id="r-1",
            sentiment_score=1.5,  # out of [-1, 1]
            competitive_position=CompetitivePosition.AMONG_OPTIONS,
            scoring_model="claude-opus-4-8",
        )


def test_run_and_alert_construct():
    run = Run(run_id="run-1", started_at="2026-06-13T02:00:00+00:00")
    assert run.status == "RUNNING"
    alert = Alert(alert_id="a-1", score_id="s-1", reason="sentiment < -0.3")
    assert alert.reason
