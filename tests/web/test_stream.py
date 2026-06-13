import json
from fastapi.testclient import TestClient

from ema_poc.web.app import create_app, WebDeps
from ema_poc.config import AppConfig, Settings, BrandConfig, LLMTargetConfig
from ema_poc.adapters.base import LLMResponse


class FakeAdapter:
    def __init__(self, name, grounded=False):
        self.name = name
        self.model_version = name + "-v"
        self.grounded = grounded

    def query(self, system_prompt, question_text):
        return LLMResponse(text=f"{self.name} ans", finish_reason="stop",
                           status="SUCCESS", completion_tokens=5)


class FakeScore:
    sentiment_score = 0.5
    competitive_position = "AMONG_OPTIONS"
    brand_mentions: list = []
    key_claims: list = []
    scoring_rationale = "r"


def _deps(tmp_path):
    cfg = AppConfig(
        settings=Settings(system_prompts={"default": "x"}),
        brands=BrandConfig(),
        targets=[LLMTargetConfig(
            name="GPT-4o", adapter="openai", model_version="gpt-4o",
            api_key_env="OPENAI_API_KEY",
            pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
            rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1})],
    )
    return WebDeps(
        config=cfg,
        build_adapters_for=lambda names: [FakeAdapter("GPT-4o")],
        scoring_client=object(),
        scorer=lambda *a, **k: FakeScore(),
        db_path=str(tmp_path / "w.sqlite"),
    )


def _parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        line = block.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:"):].strip()))
    return events


def test_ask_stream_emits_answer_score_done(tmp_path):
    app = create_app(_deps(tmp_path))
    client = TestClient(app)
    with client.stream("GET", "/api/ask/stream",
                       params={"question": "What treats psoriasis?",
                               "persona": "Provider", "brand_focus": "Skyrizi"}) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        body = "".join(chunk for chunk in r.iter_text())
    events = _parse_sse(body)
    kinds = [e["event"] for e in events]
    assert kinds[0] == "query"
    assert "answer" in kinds and "score" in kinds
    assert kinds[-1] == "done"


def test_ask_stream_requires_question(tmp_path):
    app = create_app(_deps(tmp_path))
    client = TestClient(app)
    r = client.get("/api/ask/stream", params={"question": "  "})
    assert r.status_code == 400
