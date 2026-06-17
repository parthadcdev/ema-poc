from ema_poc.db import connect, init_schema
from ema_poc.repositories import sandbox as S
from ema_poc.playground.rescore import rescore_sandbox, RescoreResult
from ema_poc.config import AppConfig, Settings, BrandConfig


class FakeScore:
    sentiment_score = 0.5; competitive_position = "AMONG_OPTIONS"
    scoring_rationale = "r"; brand_mentions = ["Skyrizi"]


def _cfg():
    return AppConfig(settings=Settings(system_prompts={"default": "x"}),
                     brands=BrandConfig(abbvie_brands=["Skyrizi"], competitor_brands=[]),
                     targets=[])


def _seed_unscored(tmp_path):
    c = connect(str(tmp_path / "r.sqlite")); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus="Skyrizi",
                         now="t0", status="DONE", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="ans", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1")
    return c, rid


def test_rescore_scores_unscored_and_clears_error(tmp_path):
    c, rid = _seed_unscored(tmp_path)
    S.set_response_scoring_error(c, sandbox_response_id=rid, error="old failure")
    res = rescore_sandbox(c, scoring_client=object(), scorer=lambda *a, **k: FakeScore(),
                          config=_cfg())
    assert res == RescoreResult(scored=1, failed=0)
    got = S.list_query_responses(c, S.list_recent_queries(c)[0].query_id)[0]
    assert got.sentiment_score == 0.5 and got.scoring_error is None


def test_rescore_records_error_on_failure(tmp_path):
    c, rid = _seed_unscored(tmp_path)
    def boom(*a, **k): raise RuntimeError("still no credits")
    res = rescore_sandbox(c, scoring_client=object(), scorer=boom, config=_cfg())
    assert res == RescoreResult(scored=0, failed=1)
    row = c.execute("SELECT sentiment_score, scoring_error FROM sandbox_responses").fetchone()
    assert row[0] is None and "still no credits" in row[1]


def test_rescore_idempotent_when_nothing_unscored(tmp_path):
    c, _ = _seed_unscored(tmp_path)
    rescore_sandbox(c, scoring_client=object(), scorer=lambda *a, **k: FakeScore(), config=_cfg())
    res = rescore_sandbox(c, scoring_client=object(), scorer=lambda *a, **k: FakeScore(), config=_cfg())
    assert res == RescoreResult(scored=0, failed=0)


def test_rescore_mixed_batch_isolates_per_item(tmp_path):
    c = connect(str(tmp_path / "m.sqlite")); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus="Skyrizi",
                         now="t0", status="DONE", target_count=2, started_at="t0")
    good = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                           grounded=False, answer_text="good answer", response_tokens=1,
                           finish_reason="stop", status="SUCCESS", now="t1")
    bad = S.save_response(c, query_id=qid, llm_name="B", llm_model_version="v",
                          grounded=False, answer_text="bad answer", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1")

    def scorer(client, *, response_text, **k):
        if response_text == "bad answer":
            raise RuntimeError("scorer blew up")
        return FakeScore()

    res = rescore_sandbox(c, scoring_client=object(), scorer=scorer, config=_cfg())
    assert res == RescoreResult(scored=1, failed=1)
    rows = {r["sandbox_response_id"]: r for r in
            c.execute("SELECT sandbox_response_id, sentiment_score, scoring_error FROM sandbox_responses")}
    assert rows[good]["sentiment_score"] == 0.5 and rows[good]["scoring_error"] is None
    assert rows[bad]["sentiment_score"] is None and "scorer blew up" in rows[bad]["scoring_error"]


from ema_poc.playground.rescore import rescore_one


def test_rescore_one_scores_and_clears(tmp_path):
    c, rid = _seed_unscored(tmp_path)
    S.set_response_scoring_error(c, sandbox_response_id=rid, error="old")
    ok = rescore_one(c, rid, scoring_client=object(),
                     scorer=lambda *a, **k: FakeScore(), config=_cfg())
    assert ok is True
    got = S.get_sandbox_response(c, rid)
    assert got.sentiment_score == 0.5 and got.scoring_error is None


def test_rescore_one_records_error(tmp_path):
    c, rid = _seed_unscored(tmp_path)
    def boom(*a, **k): raise RuntimeError("still no credits")
    ok = rescore_one(c, rid, scoring_client=object(), scorer=boom, config=_cfg())
    assert ok is False
    got = S.get_sandbox_response(c, rid)
    assert got.sentiment_score is None and "still no credits" in got.scoring_error


def test_rescore_one_unknown_id_raises_keyerror(tmp_path):
    c, _ = _seed_unscored(tmp_path)
    import pytest
    with pytest.raises(KeyError):
        rescore_one(c, "nope", scoring_client=object(),
                    scorer=lambda *a, **k: FakeScore(), config=_cfg())
