from ema_poc.db import connect, init_schema
from ema_poc.repositories import sandbox as S
from ema_poc.dashboard.dataset import collect_dataset

ABBVIE = ["Skyrizi"]
COMP = ["Humira"]


def _seed_one_monitoring(conn):
    conn.execute("INSERT INTO questions (question_id, question_text, persona, therapeutic_area, "
                 "brand_focus, domain, created_at, updated_at) VALUES "
                 "('Q1','q','Provider','Immunology','Skyrizi','Efficacy',"
                 "'2026-06-01T00:00:00+00:00','2026-06-01T00:00:00+00:00')")
    conn.execute("INSERT INTO runs (run_id, started_at) VALUES "
                 "('run1','2026-06-01T00:00:00+00:00')")
    conn.execute("INSERT INTO responses (response_id, run_id, question_id, timestamp_utc, "
                 "llm_name, llm_model_version, persona, question_text, therapeutic_area, "
                 "brand_focus, domain, status, response_text, created_at) VALUES "
                 "('m1','run1','Q1','2026-06-01T00:00:00+00:00','GPT','v','Provider','q',"
                 "'Immunology','Skyrizi','Efficacy','SUCCESS','txt','2026-06-01T00:00:00+00:00')")
    conn.commit()


def _seed_one_realtime(conn):
    qid = S.create_query(conn, question_text="rt q", persona="Patient",
                         brand_focus="Skyrizi", now="2026-06-02T00:00:00+00:00",
                         status="DONE", target_count=1, started_at="2026-06-02T00:00:00+00:00")
    rid = S.save_response(conn, query_id=qid, llm_name="Claude-Opus-4.8", llm_model_version="v",
                          grounded=True, answer_text="rt ans", response_tokens=2,
                          finish_reason="stop", status="SUCCESS", now="2026-06-02T00:00:00+00:00")
    S.set_response_score(conn, sandbox_response_id=rid, sentiment_score=0.7,
                         competitive_position="LEADER", scoring_rationale="rt r",
                         brand_mentions=["Skyrizi"])
    return rid


def _ds(tmp_path):
    c = connect(str(tmp_path / "d.sqlite")); init_schema(c)
    _seed_one_monitoring(c)
    rid = _seed_one_realtime(c)
    return collect_dataset(c, abbvie_brands=ABBVIE, competitor_brands=COMP), rid


def test_monitoring_record_tagged_source(tmp_path):
    ds, _ = _ds(tmp_path)
    mon = next(r for r in ds["records"] if r["response_id"] == "m1")
    assert mon["source"] == "monitoring"


def test_realtime_record_present_and_tagged(tmp_path):
    ds, rid = _ds(tmp_path)
    rt = next(r for r in ds["records"] if r["response_id"] == "sb-" + rid)
    assert rt["source"] == "realtime"
    assert rt["llm_name"] == "Claude-Opus-4.8"
    assert rt["grounded"] is True
    assert rt["brand_focus"] == "Skyrizi"
    assert rt["persona"] == "Patient"
    assert rt["therapeutic_area"] is None
    assert rt["sentiment_score"] == 0.7
    assert rt["competitive_position"] == "LEADER"
    assert rt["brand_mentions"] == ["Skyrizi"]
    assert rt["response_text"] == "rt ans"
    assert rt["date"] == "2026-06-02"
    assert rt["hallucination_flags"] == [] and rt["alert_reasons"] == []


def test_both_sources_counted(tmp_path):
    ds, _ = _ds(tmp_path)
    assert len(ds["records"]) == 2
