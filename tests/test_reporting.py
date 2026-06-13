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
