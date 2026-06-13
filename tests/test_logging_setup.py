import json
import logging

from ema_poc.logging_setup import JsonFormatter, RedactionFilter, redact


def test_redact_masks_known_secret_patterns():
    assert "sk-ABCDEF1234567890" not in redact("key=sk-ABCDEF1234567890")
    assert "AIzaABCDEF1234567890" not in redact("g=AIzaABCDEF1234567890")
    assert "REDACTED" in redact("Authorization: Bearer abcdef1234567890")


def test_json_formatter_emits_parseable_json_with_context():
    record = logging.LogRecord(
        name="ema",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="dispatched",
        args=(),
        exc_info=None,
    )
    record.context = {"llm_name": "GPT-4o", "question_id": "Q1"}
    out = JsonFormatter().format(record)
    parsed = json.loads(out)
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "dispatched"
    assert parsed["llm_name"] == "GPT-4o"
    assert parsed["question_id"] == "Q1"


def test_redaction_filter_scrubs_message():
    record = logging.LogRecord(
        name="ema",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="using key sk-SECRET1234567890",
        args=(),
        exc_info=None,
    )
    RedactionFilter().filter(record)
    assert "sk-SECRET1234567890" not in record.msg
