import sqlite3

import pytest

from ema_poc.db import connect, init_schema
from ema_poc.models import Alert, Response, Score
from ema_poc.repositories.alerts import list_alerts, save_alert
from ema_poc.repositories.responses import save_response
from ema_poc.repositories.runs import create_run
from ema_poc.repositories.scores import save_score

NOW = "2026-06-13T02:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=NOW)
    # Parent response + two score rows so the alerts FK (score_id -> scores) is satisfied.
    save_response(conn, Response(
        response_id="resp-1", run_id="r1", timestamp_utc=NOW, llm_name="GPT-4o",
        llm_model_version="m", persona="Provider", question_id="Q1",
        question_text="q", domain="Safety", response_text="a", response_tokens=1,
        finish_reason="stop", status="SUCCESS", created_at=NOW,
    ))
    for sid, version in (("s-1", 1), ("s-2", 2)):
        save_score(conn, Score(
            score_id=sid, response_id="resp-1", version=version,
            sentiment_score=-0.5, competitive_position="NOT_RECOMMENDED",
            brand_mentions=[], key_claims=[], scoring_rationale="r",
            scoring_model="claude-opus-4-8", created_at=NOW,
        ))
    return conn


def test_save_and_list_alerts(tmp_path):
    conn = _conn(tmp_path)
    save_alert(conn, Alert(alert_id="al-1", score_id="s-1",
                           reason="SENTIMENT_BELOW_THRESHOLD", created_at=NOW))
    save_alert(conn, Alert(alert_id="al-2", score_id="s-2",
                           reason="COMPETITIVE_POSITION_NOT_RECOMMENDED", created_at=NOW))
    alerts = list_alerts(conn)
    assert [a.alert_id for a in alerts] == ["al-1", "al-2"]
    assert alerts[0].reason == "SENTIMENT_BELOW_THRESHOLD"
    conn.close()


def test_save_alert_rejects_unknown_score_id(tmp_path):
    # Proves the FK is enforced (save_alert must NOT disable foreign_keys).
    conn = _conn(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        save_alert(conn, Alert(alert_id="al-x", score_id="does-not-exist",
                               reason="X", created_at=NOW))
    conn.close()
