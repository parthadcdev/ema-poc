import json
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
    sentiment_score = 0.5
    competitive_position = "AMONG_OPTIONS"
    scoring_rationale = "r"
    brand_mentions = ["Skyrizi"]


def test_run_playground_persists_brand_mentions(tmp_path):
    c = connect(str(tmp_path / "s.sqlite")); init_schema(c)
    list(run_playground(
        c, adapters=[FakeAdapter()], scoring_client=object(),
        scorer=lambda *a, **k: FakeScore(), abbvie_brands=["Skyrizi"],
        competitor_brands=[], system_prompts={"default": "x"}, question_text="q",
        persona=None, brand_focus="Skyrizi", model="m",
        id_factory=lambda: __import__("uuid").uuid4().hex, now="t1",
        max_retries=0, backoff=[0]))
    raw = c.execute("SELECT brand_mentions FROM sandbox_responses").fetchone()[0]
    assert json.loads(raw) == ["Skyrizi"]
