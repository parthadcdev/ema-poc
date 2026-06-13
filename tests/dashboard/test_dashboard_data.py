from ema_poc.dashboard.data import build_dashboard_data
from ema_poc.db import connect, init_schema
from ema_poc.models import Alert, Response, Score
from ema_poc.repositories.alerts import save_alert
from ema_poc.repositories.responses import save_response, update_response_scoring
from ema_poc.repositories.runs import create_run
from ema_poc.repositories.scores import save_score

T1 = "2026-06-13T01:00:00+00:00"
T2 = "2026-06-14T02:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=T1)
    return conn


def _resp(conn, rid, *, llm, ts, brand, text="ans"):
    save_response(conn, Response(
        response_id=rid, run_id="r1", timestamp_utc=ts, llm_name=llm,
        llm_model_version="m", persona="Provider", question_id="Q1",
        question_text="q", therapeutic_area="Immunology", brand_focus=brand,
        domain="Safety", response_text=text, response_tokens=1,
        finish_reason="stop", status="SUCCESS", created_at=ts,
    ))


def _score_and_denorm(conn, rid, *, sentiment, position, alert, rationale="why"):
    save_score(conn, Score(
        score_id=f"{rid}-s1", response_id=rid, version=1, sentiment_score=sentiment,
        competitive_position=position, brand_mentions=["Skyrizi"], key_claims=["c"],
        scoring_rationale=rationale, scoring_model="claude-opus-4-8", created_at=T1,
    ))
    update_response_scoring(conn, rid, sentiment_score=sentiment,
                            competitive_position=position, alert_triggered=alert)


def test_build_dashboard_data_aggregates(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "a", llm="GPT-4o", ts=T1, brand="Skyrizi")
    _score_and_denorm(conn, "a", sentiment=0.8, position="FIRST_LINE_RECOMMENDED", alert=False)
    _resp(conn, "b", llm="Gemini", ts=T1, brand="Skyrizi")
    _score_and_denorm(conn, "b", sentiment=-0.6, position="NOT_RECOMMENDED", alert=True,
                      rationale="negative")
    save_alert(conn, Alert(alert_id="al-1", score_id="b-s1",
                           reason="SENTIMENT_BELOW_THRESHOLD", created_at=T1))
    _resp(conn, "c", llm="GPT-4o", ts=T2, brand="Rinvoq")
    _score_and_denorm(conn, "c", sentiment=0.2, position="AMONG_OPTIONS", alert=False)

    data = build_dashboard_data(conn)

    assert data.total_responses == 3
    assert data.total_alerts == 1
    assert data.sentiment_by_llm["GPT-4o"] == 0.5
    assert data.sentiment_by_llm["Gemini"] == -0.6
    assert round(data.sentiment_by_therapy["Skyrizi"], 3) == round((0.8 + -0.6) / 2, 3)
    assert data.sentiment_by_therapy["Rinvoq"] == 0.2
    assert data.position_by_llm["GPT-4o"]["FIRST_LINE_RECOMMENDED"] == 1
    assert data.position_by_llm["GPT-4o"]["AMONG_OPTIONS"] == 1
    assert data.position_by_llm["Gemini"]["NOT_RECOMMENDED"] == 1
    assert data.volume_by_date["2026-06-13"] == 2
    assert data.volume_by_date["2026-06-14"] == 1
    assert data.alerts[0]["response_id"] == "b"
    assert data.alerts[0]["reason"] == "SENTIMENT_BELOW_THRESHOLD"
    row_b = next(r for r in data.rows if r["response_id"] == "b")
    assert row_b["scoring_rationale"] == "negative"

    conn.close()
