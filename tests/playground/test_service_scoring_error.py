from ema_poc.db import connect, init_schema
from ema_poc.playground.service import run_playground
from ema_poc.repositories import sandbox as S
from ema_poc.adapters.base import LLMResponse


class FakeAdapter:
    name = "A"; model_version = "v"; grounded = False
    def query(self, sp, q):
        return LLMResponse(text="ans", finish_reason="stop", status="SUCCESS",
                           completion_tokens=3)


def _boom_scorer(*a, **k):
    raise RuntimeError("credit balance too low")


def test_scoring_failure_is_persisted_not_swallowed(tmp_path):
    c = connect(str(tmp_path / "s.sqlite")); init_schema(c)
    list(run_playground(
        c, adapters=[FakeAdapter()], scoring_client=object(), scorer=_boom_scorer,
        abbvie_brands=[], competitor_brands=[], system_prompts={"default": "x"},
        question_text="q", persona=None, brand_focus=None, model="m",
        id_factory=lambda: __import__("uuid").uuid4().hex, now="t1",
        max_retries=0, backoff=[0]))
    row = c.execute("SELECT sentiment_score, scoring_error FROM sandbox_responses").fetchone()
    assert row[0] is None                       # still unscored
    assert "credit balance too low" in (row[1] or "")
