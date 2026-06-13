"""Threshold-based alert rule over a ScoreResult (FR-405).

Brand lists come from config (SE-007). Returns an alert reason string or None.
The competitor-favored rule is a POC proxy for FR-405's "competitor with
materially higher sentiment than the AbbVie therapy": since the score carries a
single AbbVie-directed sentiment, we flag when a known competitor is mentioned
AND the AbbVie sentiment is non-positive."""

from __future__ import annotations

from ema_poc.scoring.scorer import ScoreResult

SENTIMENT_THRESHOLD = -0.3


def evaluate_alert(
    result: ScoreResult, *, abbvie_brands, competitor_brands
) -> str | None:
    if result.sentiment_score < SENTIMENT_THRESHOLD:
        return "SENTIMENT_BELOW_THRESHOLD"
    if result.competitive_position == "NOT_RECOMMENDED":
        return "COMPETITIVE_POSITION_NOT_RECOMMENDED"
    mentions = [m.lower() for m in result.brand_mentions]
    competitor_mentioned = any(
        comp.lower() in mention
        for comp in competitor_brands
        for mention in mentions
    )
    if competitor_mentioned and result.sentiment_score < 0:
        return "COMPETITOR_FAVORED"
    return None
