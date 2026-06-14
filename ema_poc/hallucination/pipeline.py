"""Hallucination-check pass: for each unchecked SUCCESS response whose brand is
in the reference corpus, run the detector, persist the check + flags, and raise
an alert on HIGH risk. Idempotent (skips responses already checked)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from ema_poc.audit import record_event
from ema_poc.hallucination.detector import check_response
from ema_poc.models import Alert
from ema_poc.repositories.alerts import save_alert
from ema_poc.repositories.hallucinations import has_check, save_check, save_flags
from ema_poc.repositories.responses import success_responses
from ema_poc.repositories.scores import latest_score


@dataclass
class CheckSummary:
    checked: int
    alerts_raised: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_pending(
    conn,
    *,
    client,
    config,
    corpus,
    checker=check_response,
    model: str | None = None,
    id_factory=lambda: uuid4().hex,
    now_factory=_now_iso,
) -> CheckSummary:
    model = model or config.settings.scoring_model
    checked = 0
    alerts_raised = 0

    for response in success_responses(conn):
        ref = corpus.get(response.brand_focus)
        if ref is None:
            continue  # brand not in corpus — nothing to ground-check

        if has_check(conn, response.response_id):
            continue

        result = checker(
            client,
            response_text=response.response_text,
            brand_focus=response.brand_focus,
            brand_reference=ref,
            model=model,
        )

        now = now_factory()
        save_check(
            conn,
            response_id=response.response_id,
            risk_level=result.risk_level,
            rationale=result.rationale,
            model=model,
            now=now,
        )
        save_flags(
            conn,
            response_id=response.response_id,
            flags=result.flagged_claims,
            now=now,
            id_factory=id_factory,
        )

        high = result.risk_level == "HIGH" or any(
            getattr(f, "severity", None) == "HIGH" for f in result.flagged_claims
        )
        if high:
            score = latest_score(conn, response.response_id)
            if score is not None:
                save_alert(
                    conn,
                    Alert(
                        alert_id=id_factory(),
                        score_id=score.score_id,
                        reason=(
                            f"HALLUCINATION: {result.risk_level} risk — "
                            f"{len(result.flagged_claims)} flagged claim(s)"
                        ),
                        created_at=now,
                    ),
                )
                alerts_raised += 1

        record_event(
            conn,
            event_type="HALLUCINATION_CHECK",
            role="ORCHESTRATOR",
            question_id=response.question_id,
            llm_target=response.llm_name,
            detail=result.risk_level,
        )
        checked += 1

    return CheckSummary(checked=checked, alerts_raised=alerts_raised)
