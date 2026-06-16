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


def test_monitoring_and_realtime_records_have_identical_keys(tmp_path):
    ds, rid = _ds(tmp_path)
    mon = next(r for r in ds["records"] if r["response_id"] == "m1")
    rt = next(r for r in ds["records"] if r["response_id"] == "sb-" + rid)
    assert set(mon.keys()) == set(rt.keys())


def test_records_carry_scoring_error_key(tmp_path):
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories import sandbox as S
    from ema_poc.dashboard.dataset import collect_dataset
    c = connect(str(tmp_path / "se.sqlite")); init_schema(c)
    _seed_one_monitoring(c)
    qid = S.create_query(c, question_text="rt", persona=None, brand_focus=None,
                         now="2026-06-02T00:00:00+00:00", status="DONE",
                         target_count=1, started_at="2026-06-02T00:00:00+00:00")
    rid = S.save_response(c, query_id=qid, llm_name="X", llm_model_version="v",
                          grounded=False, answer_text="a", response_tokens=1,
                          finish_reason="stop", status="SUCCESS",
                          now="2026-06-02T00:00:00+00:00")
    S.set_response_scoring_error(c, sandbox_response_id=rid, error="credit balance too low")
    ds = collect_dataset(c, abbvie_brands=ABBVIE, competitor_brands=COMP)
    rt = next(r for r in ds["records"] if r["response_id"] == "sb-" + rid)
    mon = next(r for r in ds["records"] if r["response_id"] == "m1")
    assert rt["scoring_error"] == "credit balance too low"
    assert mon["scoring_error"] is None
    assert set(mon.keys()) == set(rt.keys())     # key parity preserved


def test_realtime_question_id_is_bank_style(tmp_path):
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories import sandbox as S
    from ema_poc.dashboard.dataset import collect_dataset
    c = connect(str(tmp_path / "qid.sqlite")); init_schema(c)
    q1 = S.create_query(c, question_text="q1", persona="Prospect", brand_focus=None,
                        now="2026-06-01T00:00:00+00:00", status="DONE", target_count=1,
                        started_at="2026-06-01T00:00:00+00:00")
    r1 = S.save_response(c, query_id=q1, llm_name="A", llm_model_version="v", grounded=False,
                         answer_text="a", response_tokens=1, finish_reason="stop",
                         status="SUCCESS", now="2026-06-01T00:00:00+00:00")
    q2 = S.create_query(c, question_text="q2", persona="Patient", brand_focus=None,
                        now="2026-06-02T00:00:00+00:00", status="DONE", target_count=1,
                        started_at="2026-06-02T00:00:00+00:00")
    r2 = S.save_response(c, query_id=q2, llm_name="B", llm_model_version="v", grounded=False,
                         answer_text="b", response_tokens=1, finish_reason="stop",
                         status="SUCCESS", now="2026-06-02T00:00:00+00:00")
    q3 = S.create_query(c, question_text="q3", persona=None, brand_focus=None,
                        now="2026-06-03T00:00:00+00:00", status="DONE", target_count=1,
                        started_at="2026-06-03T00:00:00+00:00")
    r3 = S.save_response(c, query_id=q3, llm_name="C", llm_model_version="v", grounded=False,
                         answer_text="c", response_tokens=1, finish_reason="stop",
                         status="SUCCESS", now="2026-06-03T00:00:00+00:00")
    ds = collect_dataset(c, abbvie_brands=[], competitor_brands=[])
    by_resp = {r["response_id"]: r for r in ds["records"]}
    assert by_resp["sb-" + r1]["question_id"] == "RLT-PRO-001"   # Prospect, first
    assert by_resp["sb-" + r2]["question_id"] == "RLT-PAT-002"   # Patient, second
    assert by_resp["sb-" + r3]["question_id"] == "RLT-GEN-003"   # no persona -> GEN
