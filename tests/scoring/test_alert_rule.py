from ema_poc.scoring.alerts import evaluate_alert
from ema_poc.scoring.scorer import ScoreResult

ABBVIE = ["Skyrizi", "Rinvoq"]
COMPETITORS = ["Humira", "Stelara"]


def _score(sentiment=0.5, position="AMONG_OPTIONS", mentions=None):
    return ScoreResult(
        sentiment_score=sentiment, competitive_position=position,
        brand_mentions=mentions or [], key_claims=[], scoring_rationale="r",
        confidence_level="MIXED", citation_quality="MODERATE",
    )


def test_no_alert_for_positive_neutral():
    assert evaluate_alert(_score(sentiment=0.4), abbvie_brands=ABBVIE,
                          competitor_brands=COMPETITORS) is None


def test_alert_on_low_sentiment():
    assert evaluate_alert(_score(sentiment=-0.5), abbvie_brands=ABBVIE,
                          competitor_brands=COMPETITORS) == "SENTIMENT_BELOW_THRESHOLD"


def test_alert_on_not_recommended_position():
    reason = evaluate_alert(_score(sentiment=0.2, position="NOT_RECOMMENDED"),
                            abbvie_brands=ABBVIE, competitor_brands=COMPETITORS)
    assert reason == "COMPETITIVE_POSITION_NOT_RECOMMENDED"


def test_alert_on_competitor_favored():
    # competitor mentioned + AbbVie sentiment non-positive (POC proxy)
    reason = evaluate_alert(
        _score(sentiment=-0.1, position="AMONG_OPTIONS", mentions=["Skyrizi", "Humira"]),
        abbvie_brands=ABBVIE, competitor_brands=COMPETITORS,
    )
    assert reason == "COMPETITOR_FAVORED"


def test_no_competitor_favored_when_sentiment_positive():
    assert evaluate_alert(
        _score(sentiment=0.3, mentions=["Skyrizi", "Humira"]),
        abbvie_brands=ABBVIE, competitor_brands=COMPETITORS,
    ) is None
