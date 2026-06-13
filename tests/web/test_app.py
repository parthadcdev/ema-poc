from fastapi.testclient import TestClient

from ema_poc.web.app import create_app, WebDeps
from ema_poc.config import AppConfig, Settings, BrandConfig, LLMTargetConfig


def _config():
    targets = [
        LLMTargetConfig(name="GPT-4o", adapter="openai", model_version="gpt-4o",
                        api_key_env="OPENAI_API_KEY",
                        pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
                        rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1}),
        LLMTargetConfig(name="Claude-Grounded", adapter="claude", model_version="claude-opus-4-8",
                        api_key_env="ANTHROPIC_API_KEY", grounded=True,
                        pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
                        rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1}),
    ]
    return AppConfig(settings=Settings(), brands=BrandConfig(), targets=targets)


def _deps(tmp_path):
    return WebDeps(
        config=_config(),
        build_adapters_for=lambda names: [],
        scoring_client=object(),
        scorer=lambda *a, **k: None,
        db_path=str(tmp_path / "w.sqlite"),
    )


def test_index_served(tmp_path):
    app = create_app(_deps(tmp_path))
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_targets_endpoint_lists_all_targets(tmp_path):
    app = create_app(_deps(tmp_path))
    client = TestClient(app)
    r = client.get("/api/targets")
    assert r.status_code == 200
    data = r.json()
    names = {t["name"]: t for t in data["targets"]}
    assert names["GPT-4o"]["grounded"] is False
    assert names["Claude-Grounded"]["grounded"] is True


def test_targets_endpoint_excludes_disabled(tmp_path):
    from fastapi.testclient import TestClient
    deps = _deps(tmp_path)
    deps.config.targets.append(
        __import__("ema_poc.config", fromlist=["LLMTargetConfig"]).LLMTargetConfig(
            name="Disabled-One", adapter="openai", model_version="m",
            api_key_env="OPENAI_API_KEY", enabled=False,
            pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
            rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1}))
    client = TestClient(create_app(deps))
    names = {t["name"] for t in client.get("/api/targets").json()["targets"]}
    assert "Disabled-One" not in names


def test_index_contains_playground_markers(tmp_path):
    from fastapi.testclient import TestClient
    app = create_app(_deps(tmp_path))
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="question"' in html
    assert "EventSource" in html
    assert "/api/ask/stream" in html
    assert "/api/targets" in html
