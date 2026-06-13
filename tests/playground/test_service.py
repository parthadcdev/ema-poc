from ema_poc.db import connect, init_schema
from ema_poc.adapters.base import Citation, LLMResponse
from ema_poc.playground.service import run_playground
from ema_poc.repositories import sandbox as S


class FakeAdapter:
    def __init__(self, name, grounded=False, citations=None):
        self.name = name
        self.model_version = name + "-v"
        self.grounded = grounded
        self._citations = citations or []

    def query(self, system_prompt, question_text):
        return LLMResponse(
            text=f"{self.name} answer", finish_reason="stop", status="SUCCESS",
            completion_tokens=7, citations=self._citations,
        )


class FakeScoreResult:
    def __init__(self):
        self.sentiment_score = 0.5
        self.competitive_position = "AMONG_OPTIONS"
        self.brand_mentions = ["Skyrizi"]
        self.key_claims = []
        self.scoring_rationale = "because"


def fake_scorer(client, *, response_text, brand_focus, abbvie_brands,
                competitor_brands, model):
    return FakeScoreResult()


def test_run_playground_emits_answer_then_score_per_target_and_persists(tmp_path):
    conn = connect(str(tmp_path / "p.sqlite"))
    init_schema(conn)
    adapters = [
        FakeAdapter("GPT-4o"),
        FakeAdapter("Claude-Grounded", grounded=True,
                    citations=[Citation(title="Src", url="https://s")]),
    ]
    events = list(run_playground(
        conn, adapters=adapters, scoring_client=object(), scorer=fake_scorer,
        abbvie_brands=["Skyrizi"], competitor_brands=["Stelara"],
        system_prompts={"default": "You are helpful."},
        question_text="What treats psoriasis?", persona="Provider",
        brand_focus="Skyrizi", model="claude-opus-4-8",
        id_factory=iter([f"id{i}" for i in range(50)]).__next__,
        now="2026-01-01T00:00:00+00:00",
        max_retries=0, backoff=[1],
    ))
    kinds = [e["event"] for e in events]
    assert kinds[0] == "query"
    assert kinds.count("answer") == 2
    assert kinds.count("score") == 2
    assert kinds[-1] == "done"

    grounded_answer = next(e for e in events if e["event"] == "answer" and e["grounded"])
    assert grounded_answer["citations"] == [{"title": "Src", "url": "https://s", "snippet": None}]

    query_id = events[0]["query_id"]
    rows = S.list_query_responses(conn, query_id)
    assert {r.llm_name for r in rows} == {"GPT-4o", "Claude-Grounded"}
    assert all(r.sentiment_score == 0.5 for r in rows)
    grounded_row = next(r for r in rows if r.grounded)
    assert [c.url for c in grounded_row.citations] == ["https://s"]


def test_run_playground_emits_error_on_no_adapters(tmp_path):
    conn = connect(str(tmp_path / "p.sqlite"))
    init_schema(conn)
    events = list(run_playground(
        conn, adapters=[], scoring_client=object(), scorer=fake_scorer,
        abbvie_brands=[], competitor_brands=[], system_prompts={"default": "x"},
        question_text="q", persona=None, brand_focus=None, model="m",
        id_factory=iter(["id0"]).__next__, now="2026-01-01T00:00:00+00:00",
        max_retries=0, backoff=[1],
    ))
    assert events[-1]["event"] == "error"
