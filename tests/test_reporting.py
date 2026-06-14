from ema_poc.agent.runner import RunSummary
from ema_poc.connectivity import TargetStatus
from ema_poc.reporting import format_health_report, format_run_report
from ema_poc.scoring.pipeline import ScoringSummary


def _run_summary():
    return RunSummary(
        run_id="run-1", questions_attempted=100, responses_captured=300,
        by_status={"SUCCESS": 290, "FAILED": 5, "TRUNCATED": 3, "BLOCKED": 2},
        failure_count=5, total_tokens=123456, est_cost=1.2345,
    )


def test_format_run_report_includes_counts_and_cost():
    text = format_run_report(_run_summary())
    assert "run-1" in text
    assert "300" in text  # responses captured
    assert "SUCCESS" in text
    assert "$1.2345" in text  # est cost formatted
    assert "scored" not in text  # no scoring summary given


def test_format_run_report_with_scoring():
    text = format_run_report(_run_summary(), ScoringSummary(scored=290, alerts_raised=12))
    assert "scored" in text
    assert "290" in text
    assert "12" in text  # alerts


def test_format_health_report():
    text = format_health_report([
        TargetStatus("GPT-4o", True, "SUCCESS"),
        TargetStatus("Claude", False, "error: timeout"),
    ])
    assert "OK" in text and "GPT-4o" in text
    assert "FAIL" in text and "Claude" in text
    assert "timeout" in text


def test_format_run_report_shows_backfill_for_when_set():
    summary = RunSummary(
        run_id="run-bf", questions_attempted=1, responses_captured=1,
        by_status={"SUCCESS": 1, "FAILED": 0, "TRUNCATED": 0, "BLOCKED": 0},
        failure_count=0, total_tokens=10, est_cost=0.001,
        backfill_for="2026-06-10",
    )
    text = format_run_report(summary)
    assert "backfill for" in text
    assert "2026-06-10" in text


def test_format_run_report_omits_backfill_for_when_none():
    summary = RunSummary(
        run_id="run-nobf", questions_attempted=1, responses_captured=1,
        by_status={"SUCCESS": 1, "FAILED": 0, "TRUNCATED": 0, "BLOCKED": 0},
        failure_count=0, total_tokens=10, est_cost=0.001,
        backfill_for=None,
    )
    text = format_run_report(summary)
    assert "backfill for" not in text


def test_format_run_report_shows_budget_line_when_exceeded():
    summary = RunSummary(
        run_id="run-budget", questions_attempted=5, responses_captured=5,
        by_status={"SUCCESS": 5, "FAILED": 0, "TRUNCATED": 0, "BLOCKED": 0},
        failure_count=0, total_tokens=1200, est_cost=0.05,
        budget_exceeded=True, token_budget=1000,
    )
    text = format_run_report(summary)
    assert "budget exceeded" in text
    assert "1200" in text
    assert "1000" in text


def test_format_run_report_omits_budget_line_when_not_exceeded():
    summary = RunSummary(
        run_id="run-nobudget", questions_attempted=5, responses_captured=5,
        by_status={"SUCCESS": 5, "FAILED": 0, "TRUNCATED": 0, "BLOCKED": 0},
        failure_count=0, total_tokens=800, est_cost=0.03,
        budget_exceeded=False, token_budget=1000,
    )
    text = format_run_report(summary)
    assert "budget exceeded" not in text
