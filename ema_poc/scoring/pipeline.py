"""Scoring pass orchestration (FR-401, FR-405, FR-406).

For each unscored SUCCESS response: score via Claude, persist a versioned Score,
update the response's derived columns, and raise+persist an alert if warranted.
The scorer and Anthropic client are injected so this runs against a fake in
tests (no network)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from ema_poc.audit import record_event
from ema_poc.config import AppConfig
from ema_poc.models import Alert, Score
from ema_poc.repositories.alerts import save_alert
from ema_poc.repositories.responses import update_response_scoring
from ema_poc.repositories.scores import (
    next_score_version,
    save_score,
    unscored_success_responses,
)
from ema_poc.scoring.alerts import evaluate_alert
from ema_poc.scoring.scorer import score_response


@dataclass
class ScoringSummary:
    scored: int
    alerts_raised: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def score_pending(
    conn,
    *,
    client,
    config: AppConfig,
    scorer=score_response,
    model: str | None = None,
    id_factory=lambda: uuid4().hex,
    now_factory=_now_iso,
) -> ScoringSummary:
    model = model or config.settings.scoring_model
    abbvie = config.brands.abbvie_brands
    competitors = config.brands.competitor_brands

    scored = 0
    alerts_raised = 0
    for response in unscored_success_responses(conn):
        result = scorer(
            client,
            response_text=response.response_text,
            brand_focus=response.brand_focus,
            abbvie_brands=abbvie,
            competitor_brands=competitors,
            model=model,
        )
        version = next_score_version(conn, response.response_id)
        score = Score(
            score_id=id_factory(),
            response_id=response.response_id,
            version=version,
            sentiment_score=result.sentiment_score,
            competitive_position=result.competitive_position,
            brand_mentions=result.brand_mentions,
            key_claims=result.key_claims,
            scoring_rationale=result.scoring_rationale,
            scoring_model=model,
            created_at=now_factory(),
        )
        save_score(conn, score)

        reason = evaluate_alert(
            result, abbvie_brands=abbvie, competitor_brands=competitors
        )
        update_response_scoring(
            conn,
            response.response_id,
            sentiment_score=result.sentiment_score,
            competitive_position=result.competitive_position,
            alert_triggered=reason is not None,
        )
        if reason is not None:
            save_alert(conn, Alert(
                alert_id=id_factory(), score_id=score.score_id,
                reason=reason, created_at=now_factory(),
            ))
            alerts_raised += 1

        record_event(
            conn,
            event_type="SCORING",
            role="ORCHESTRATOR",
            question_id=response.question_id,
            llm_target=response.llm_name,
            detail=result.competitive_position,
        )
        scored += 1

    return ScoringSummary(scored=scored, alerts_raised=alerts_raised)
