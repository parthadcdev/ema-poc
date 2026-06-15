import uuid

from ema_poc.db import connect, init_schema
from ema_poc.playground.service import run_playground
from ema_poc.repositories import sandbox as S
from ema_poc.adapters.base import LLMResponse


class FakeAdapter:
    name = "A"; model_version = "v"; grounded = False
    def query(self, sp, q):
        return LLMResponse(text="ans", finish_reason="stop", status="SUCCESS",
                           completion_tokens=3)


class FakeScore:
    sentiment_score = 0.5; competitive_position = "AMONG_OPTIONS"; scoring_rationale = "r"


def test_run_playground_uses_provided_query_id(tmp_path):
    c = connect(str(tmp_path / "s.sqlite")); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None, now="t0",
                         status="RUNNING", target_count=1, started_at="t0")
    events = list(run_playground(
        c, query_id=qid, adapters=[FakeAdapter()], scoring_client=object(),
        scorer=lambda *a, **k: FakeScore(), abbvie_brands=[], competitor_brands=[],
        system_prompts={"default": "x"}, question_text="q", persona=None,
        brand_focus=None, model="m", id_factory=lambda: uuid.uuid4().hex,
        now="t1", max_retries=0, backoff=[0]))
    # No NEW query row created; the provided id is reused.
    assert events[0] == {"event": "query", "query_id": qid}
    assert len(S.list_query_responses(c, qid)) == 1
    assert c.execute("SELECT COUNT(*) FROM sandbox_queries").fetchone()[0] == 1


def test_run_playground_self_creates_running_row_when_no_query_id(tmp_path):
    c = connect(str(tmp_path / "s.sqlite")); init_schema(c)
    events = list(run_playground(
        c, adapters=[FakeAdapter()], scoring_client=object(),
        scorer=lambda *a, **k: FakeScore(), abbvie_brands=[], competitor_brands=[],
        system_prompts={"default": "x"}, question_text="q", persona=None,
        brand_focus=None, model="m", id_factory=lambda: uuid.uuid4().hex,
        now="t1", max_retries=0, backoff=[0]))
    qid = events[0]["query_id"]
    row = S.get_query(c, qid)
    assert row.status == "RUNNING"
    assert row.target_count == 1
    assert row.started_at == "t1"
