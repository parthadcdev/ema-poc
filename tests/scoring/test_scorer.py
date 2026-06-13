import pytest
from pydantic import ValidationError

from ema_poc.scoring.scorer import ScoreResult, score_response


class _FakeMessages:
    def __init__(self, result):
        self._result = result
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return type("Parsed", (), {"parsed_output": self._result})()


class _FakeClient:
    def __init__(self, result):
        self.messages = _FakeMessages(result)


def test_score_result_validates_sentiment_bounds():
    ScoreResult(
        sentiment_score=0.5, competitive_position="AMONG_OPTIONS",
        brand_mentions=["Skyrizi"], key_claims=["claim"], scoring_rationale="r",
    )
    with pytest.raises(ValidationError):
        ScoreResult(
            sentiment_score=1.5, competitive_position="AMONG_OPTIONS",
            brand_mentions=[], key_claims=[], scoring_rationale="r",
        )


def test_score_result_rejects_bad_competitive_position():
    with pytest.raises(ValidationError):
        ScoreResult(
            sentiment_score=0.0, competitive_position="MAYBE",
            brand_mentions=[], key_claims=[], scoring_rationale="r",
        )


def test_score_response_returns_parsed_output():
    expected = ScoreResult(
        sentiment_score=-0.4, competitive_position="SECOND_LINE",
        brand_mentions=["Skyrizi", "Humira"], key_claims=["c1"], scoring_rationale="why",
    )
    client = _FakeClient(expected)
    out = score_response(
        client, response_text="some answer", brand_focus="Skyrizi",
        abbvie_brands=["Skyrizi"], competitor_brands=["Humira"],
    )
    assert out is expected


def test_score_response_call_shape_opus48_rules():
    client = _FakeClient(ScoreResult(
        sentiment_score=0.0, competitive_position="NOT_MENTIONED",
        brand_mentions=[], key_claims=[], scoring_rationale="r",
    ))
    score_response(
        client, response_text="text about Skyrizi", brand_focus="Skyrizi",
        abbvie_brands=["Skyrizi"], competitor_brands=["Humira"],
        model="claude-opus-4-8",
    )
    kw = client.messages.kwargs
    assert kw["model"] == "claude-opus-4-8"
    assert kw["output_format"] is ScoreResult
    assert kw["thinking"] == {"type": "adaptive"}
    assert "temperature" not in kw  # Opus 4.8 rejects temperature
    assert "top_p" not in kw
    assert "budget_tokens" not in kw
    user_content = kw["messages"][0]["content"]
    assert "text about Skyrizi" in user_content
    assert "Skyrizi" in user_content
