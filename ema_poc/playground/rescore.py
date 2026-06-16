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


def _score_response_row(conn, sandbox_response_id, answer_text, brand_focus,
                        *, scoring_client, scorer, config) -> bool:
    """Score one response row. True if scored (clears error); False if it failed
    (records scoring_error). Never raises on a scoring failure."""
    try:
        result = scorer(
            scoring_client, response_text=answer_text, brand_focus=brand_focus,
            abbvie_brands=config.brands.abbvie_brands,
            competitor_brands=config.brands.competitor_brands,
            model=config.settings.scoring_model)
        S.set_response_score(
            conn, sandbox_response_id=sandbox_response_id,
            sentiment_score=result.sentiment_score,
            competitive_position=result.competitive_position,
            scoring_rationale=result.scoring_rationale,
            brand_mentions=result.brand_mentions)
        return True
    except Exception as exc:
        S.set_response_scoring_error(conn, sandbox_response_id=sandbox_response_id,
                                     error=str(exc)[:500])
        return False


def rescore_one(conn, sandbox_response_id, *, scoring_client, scorer, config) -> bool:
    """Rescore a single sandbox response. Raises KeyError if the id is unknown."""
    row = conn.execute(
        "SELECT sr.answer_text, q.brand_focus FROM sandbox_responses sr "
        "JOIN sandbox_queries q ON sr.query_id = q.query_id "
        "WHERE sr.sandbox_response_id = ?", (sandbox_response_id,)).fetchone()
    if row is None:
        raise KeyError(sandbox_response_id)
    return _score_response_row(conn, sandbox_response_id, row["answer_text"],
                               row["brand_focus"], scoring_client=scoring_client,
                               scorer=scorer, config=config)


def rescore_sandbox(conn, *, scoring_client, scorer, config) -> RescoreResult:
    scored = failed = 0
    for row in S.list_unscored_sandbox(conn):
        ok = _score_response_row(conn, row["sandbox_response_id"], row["answer_text"],
                                 row["brand_focus"], scoring_client=scoring_client,
                                 scorer=scorer, config=config)
        scored += int(ok)
        failed += int(not ok)
    return RescoreResult(scored=scored, failed=failed)
