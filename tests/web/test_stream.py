import json
from fastapi.testclient import TestClient

from ema_poc.web.app import create_app, WebDeps, _check_rate
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


# ---------------------------------------------------------------------------
# Rate-limiting tests (route level)
# ---------------------------------------------------------------------------

def _deps_with_env(tmp_path, env):
    """Return WebDeps with the given env mapping."""
    deps = _deps(tmp_path)
    deps.env = env
    return deps


def test_query_cap_returns_429_over_limit(tmp_path):
    """First two calls succeed; third call within the hour returns 429."""
    app = create_app(_deps_with_env(tmp_path, {"PLAYGROUND_MAX_QUERIES_PER_HOUR": "2"}))
    client = TestClient(app)
    r1 = client.get("/api/ask/stream", params={"question": "hi"})
    r2 = client.get("/api/ask/stream", params={"question": "hi"})
    r3 = client.get("/api/ask/stream", params={"question": "hi"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429


def test_query_cap_unlimited_when_zero(tmp_path):
    """Cap of 0 means unlimited — all calls should succeed."""
    app = create_app(_deps_with_env(tmp_path, {"PLAYGROUND_MAX_QUERIES_PER_HOUR": "0"}))
    client = TestClient(app)
    for _ in range(5):
        r = client.get("/api/ask/stream", params={"question": "hi"})
        assert r.status_code != 429


# ---------------------------------------------------------------------------
# Unit tests for _check_rate helper
# ---------------------------------------------------------------------------

def test__check_rate_unit_cap_enforced():
    """Third call with cap=2 within the window should be rejected."""
    store = {}
    now = 1000.0
    assert _check_rate(store, "1.2.3.4", cap=2, now=now) is True
    assert _check_rate(store, "1.2.3.4", cap=2, now=now + 1) is True
    assert _check_rate(store, "1.2.3.4", cap=2, now=now + 2) is False


def test__check_rate_unit_unlimited_when_zero():
    """cap=0 always allows."""
    store = {}
    for i in range(10):
        assert _check_rate(store, "1.2.3.4", cap=0, now=float(i)) is True


def test__check_rate_unit_old_entries_pruned():
    """Hits older than the window (3600 s) do not count; allow again after window."""
    store = {}
    # Fill cap=2 at t=0
    _check_rate(store, "1.2.3.4", cap=2, now=0.0)
    _check_rate(store, "1.2.3.4", cap=2, now=1.0)
    # Still blocked at t=100 (within window)
    assert _check_rate(store, "1.2.3.4", cap=2, now=100.0) is False
    # After the window expires (t=3601), old hits are gone → allowed again
    assert _check_rate(store, "1.2.3.4", cap=2, now=3601.0) is True
