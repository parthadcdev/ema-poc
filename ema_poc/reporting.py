"""Human-readable run-summary and health-check reports (NF-008, NF-009)."""

from __future__ import annotations

from ema_poc.agent.runner import RunSummary
from ema_poc.connectivity import TargetStatus
from ema_poc.scoring.pipeline import ScoringSummary


def format_run_report(
    summary: RunSummary, scoring: ScoringSummary | None = None
) -> str:
    lines = [
        f"Run {summary.run_id}",
        *([f"  backfill for:        {summary.backfill_for}"] if summary.backfill_for is not None else []),
        f"  questions attempted: {summary.questions_attempted}",
        f"  responses captured:  {summary.responses_captured}",
        f"  by status:           {summary.by_status}",
        f"  failures:            {summary.failure_count}",
        f"  total tokens:        {summary.total_tokens}",
        f"  estimated cost:      ${summary.est_cost:.4f}",
    ]
    if summary.budget_exceeded:
        lines.append(
            f"  budget exceeded:     stopped at {summary.total_tokens} / "
            f"{summary.token_budget} tokens"
        )
    if scoring is not None:
        lines += [
            f"  scored:              {scoring.scored}",
            f"  alerts raised:       {scoring.alerts_raised}",
        ]
    return "\n".join(lines)


def format_health_report(statuses: list[TargetStatus]) -> str:
    return "\n".join(
        f"[{'OK' if s.ok else 'FAIL'}] {s.name}: {s.detail}" for s in statuses
    )
