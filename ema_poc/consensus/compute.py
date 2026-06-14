"""Compute per-(run, question, LLM) consensus across samples and raise VARIANCE
alerts on material disagreement (no majority, or positions spanning favorable and
unfavorable/absent)."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from ema_poc.audit import record_event
from ema_poc.models import Alert
from ema_poc.repositories.alerts import save_alert
from ema_poc.repositories.consensus import existing_groups, save_consensus
from ema_poc.repositories.responses import success_responses
from ema_poc.repositories.scores import latest_score

FAVORABLE = {"FIRST_LINE_RECOMMENDED", "AMONG_OPTIONS"}
UNFAVORABLE = {"NOT_RECOMMENDED", "NOT_MENTIONED"}


@dataclass
class ConsensusSummary:
    groups: int
    alerts_raised: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pos_value(score) -> str | None:
    """Return the string value of a score's competitive_position, or None."""
    cp = getattr(score, "competitive_position", None)
    if cp is None:
        return None
    return cp.value if hasattr(cp, "value") else cp


def compute_consensus(
    conn,
    *,
    now_factory=_now_iso,
    id_factory=lambda: uuid4().hex,
) -> ConsensusSummary:
    """Group scored SUCCESS responses by (run_id, question_id, llm_name), compute
    majority position + agreement + sentiment spread, persist a consensus row, and
    raise a VARIANCE alert on material disagreement."""
    # Build groups: (run_id, question_id, llm_name) -> [(resp, score), ...]
    groups: dict[tuple, list] = defaultdict(list)
    for resp in success_responses(conn):
        score = latest_score(conn, resp.response_id)
        if score is None:
            continue
        groups[(resp.run_id, resp.question_id, resp.llm_name)].append((resp, score))

    already = existing_groups(conn)
    n_groups = 0
    alerts_raised = 0

    for key, items in groups.items():
        if key in already:
            continue

        run_id, question_id, llm_name = key

        positions = [p for p in (_pos_value(s) for _, s in items) if p is not None]
        sentiments = [
            s.sentiment_score
            for _, s in items
            if getattr(s, "sentiment_score", None) is not None
        ]
        sample_count = len(items)

        if not positions:
            continue  # nothing to vote on

        counts = Counter(positions)
        top_count = max(counts.values())
        top = [p for p, c in counts.items() if c == top_count]
        # Vote uses each sample's latest (override-aware) score via latest_score.
        agreement = top_count / len(positions)
        # Canonical requires a UNIQUE top position AND a strict majority (> 0.5).
        # A plurality winner that is not a strict majority yields canonical=None.
        canonical = top[0] if (len(top) == 1 and agreement > 0.5) else None
        sentiment_mean = statistics.fmean(sentiments) if sentiments else None
        sentiment_stdev = (
            statistics.pstdev(sentiments)
            if len(sentiments) >= 2
            else (0.0 if sentiments else None)
        )

        now = now_factory()
        save_consensus(
            conn,
            consensus_id=id_factory(),
            run_id=run_id,
            question_id=question_id,
            llm_name=llm_name,
            canonical_position=canonical,
            agreement=agreement,
            sentiment_mean=sentiment_mean,
            sentiment_stdev=sentiment_stdev,
            sample_count=sample_count,
            now=now,
        )
        n_groups += 1

        # Material disagreement: no unique majority OR positions straddle
        # favorable ↔ unfavorable sets.
        posset = set(positions)
        material = canonical is None or (posset & FAVORABLE and posset & UNFAVORABLE)
        if material:
            # Use the score_id from the first item's score (a real score row)
            rep_score_id = items[0][1].score_id
            breakdown = ", ".join(f"{c}x{p}" for p, c in counts.most_common())
            reason = f"VARIANCE: {breakdown} across {sample_count} samples"
            save_alert(
                conn,
                Alert(
                    alert_id=id_factory(),
                    score_id=rep_score_id,
                    reason=reason,
                    created_at=now,
                ),
            )
            alerts_raised += 1

        record_event(
            conn,
            event_type="CONSENSUS",
            role="ORCHESTRATOR",
            question_id=question_id,
            llm_target=llm_name,
            detail=canonical or "NO_MAJORITY",
        )

    return ConsensusSummary(groups=n_groups, alerts_raised=alerts_raised)
