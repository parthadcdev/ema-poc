"""Rescore sandbox (playground) responses that were left unscored — e.g. when the
scoring API failed at run time. Idempotent: only touches SUCCESS responses with no
score yet. Per-item failures are recorded as scoring_error, never raised."""

from __future__ import annotations

from dataclasses import dataclass

from ema_poc.repositories import sandbox as S


@dataclass
class RescoreResult:
    scored: int
    failed: int


def rescore_sandbox(conn, *, scoring_client, scorer, config) -> RescoreResult:
    scored = failed = 0
    for row in S.list_unscored_sandbox(conn):
        rid = row["sandbox_response_id"]
        try:
            result = scorer(
                scoring_client, response_text=row["answer_text"],
                brand_focus=row["brand_focus"],
                abbvie_brands=config.brands.abbvie_brands,
                competitor_brands=config.brands.competitor_brands,
                model=config.settings.scoring_model)
            S.set_response_score(
                conn, sandbox_response_id=rid,
                sentiment_score=result.sentiment_score,
                competitive_position=result.competitive_position,
                scoring_rationale=result.scoring_rationale,
                brand_mentions=result.brand_mentions)
            scored += 1
        except Exception as exc:
            S.set_response_scoring_error(conn, sandbox_response_id=rid, error=str(exc)[:500])
            failed += 1
    return RescoreResult(scored=scored, failed=failed)
