from ema_poc.db import connect, init_schema
from ema_poc.models import Response
from ema_poc.repositories.responses import (
    count_responses,
    query_responses,
    save_response,
)
from ema_poc.repositories.runs import create_run

T1 = "2026-06-13T01:00:00+00:00"
T2 = "2026-06-13T02:00:00+00:00"
T3 = "2026-06-13T03:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=T1)
    return conn


def _save(
    conn,
    response_id,
    *,
    llm="GPT-4o",
    persona="Provider",
    ta="Immunology",
    brand="Skyrizi",
    domain="Safety",
    ts=T1,
    sentiment=None,
    alert=False,
    status="SUCCESS",
    text="ans",
    question_id="Q1",
):
    r = Response(
        response_id=response_id, run_id="r1", timestamp_utc=ts, llm_name=llm,
        llm_model_version="m", persona=persona, question_id=question_id,
        question_text="q", therapeutic_area=ta, brand_focus=brand, domain=domain,
        response_text=text, response_tokens=10, finish_reason="stop", status=status,
        sentiment_score=sentiment, alert_triggered=alert, created_at=ts,
    )
    save_response(conn, r)


def test_query_all_ordered_by_timestamp(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "a", ts=T2)
    _save(conn, "b", ts=T1)
    _save(conn, "c", ts=T3)
    ids = [r.response_id for r in query_responses(conn)]
    assert ids == ["b", "a", "c"]  # ascending by timestamp
    conn.close()


def test_filter_by_llm_persona_domain(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "a", llm="GPT-4o", persona="Provider", domain="Safety")
    _save(conn, "b", llm="Gemini", persona="Patient", domain="Efficacy")
    assert [r.response_id for r in query_responses(conn, llm="Gemini")] == ["b"]
    assert [r.response_id for r in query_responses(conn, persona="Provider")] == ["a"]
    assert [r.response_id for r in query_responses(conn, domain="Efficacy")] == ["b"]
    conn.close()


def test_filter_by_date_range(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "a", ts=T1)
    _save(conn, "b", ts=T2)
    _save(conn, "c", ts=T3)
    got = [r.response_id for r in query_responses(conn, date_from=T2, date_to=T3)]
    assert got == ["b", "c"]
    conn.close()


def test_filter_by_sentiment_range_and_alert(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "a", sentiment=-0.5, alert=True)
    _save(conn, "b", sentiment=0.2, alert=False)
    _save(conn, "c", sentiment=None, alert=False)
    neg = [r.response_id for r in query_responses(conn, sentiment_max=-0.3)]
    assert neg == ["a"]
    alerted = [r.response_id for r in query_responses(conn, alert_triggered=True)]
    assert alerted == ["a"]
    conn.close()


def test_filter_by_ta_brand_status(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "a", ta="Immunology", brand="Skyrizi", status="SUCCESS")
    _save(conn, "b", ta="Oncology", brand="Venclexta", status="BLOCKED")
    assert [r.response_id for r in query_responses(conn, therapeutic_area="Oncology")] == ["b"]
    assert [r.response_id for r in query_responses(conn, brand_focus="Skyrizi")] == ["a"]
    assert [r.response_id for r in query_responses(conn, status="BLOCKED")] == ["b"]
    conn.close()


def test_pagination_and_count(tmp_path):
    conn = _conn(tmp_path)
    for i, ts in enumerate([T1, T2, T3]):
        _save(conn, f"r{i}", ts=ts)
    assert count_responses(conn) == 3
    page = query_responses(conn, limit=2, offset=0)
    assert [r.response_id for r in page] == ["r0", "r1"]
    page2 = query_responses(conn, limit=2, offset=2)
    assert [r.response_id for r in page2] == ["r2"]
    assert count_responses(conn, llm="Gemini") == 0
    conn.close()


def test_combined_filters_apply_as_and(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "a", llm="GPT-4o", domain="Safety")
    _save(conn, "b", llm="GPT-4o", domain="Efficacy")
    _save(conn, "c", llm="Gemini", domain="Safety")
    got = [r.response_id for r in query_responses(conn, llm="GPT-4o", domain="Safety")]
    assert got == ["a"]  # only the row matching BOTH filters
    conn.close()
