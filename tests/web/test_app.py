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


def test_index_has_xss_escaping_helpers(tmp_path):
    from fastapi.testclient import TestClient
    app = create_app(_deps(tmp_path))
    html = TestClient(app).get("/").text
    assert "function esc(" in html
    assert "function safeUrl(" in html
    # citations and message must not interpolate raw values
    assert "esc(c.title" in html
    assert "safeUrl(c.url" in html


def test_index_has_markdown_renderer(tmp_path):
    from fastapi.testclient import TestClient
    html = TestClient(create_app(_deps(tmp_path))).get("/").text
    # the markdown renderer is present and applied to the answer card
    assert "function renderMarkdown" in html
    assert "renderMarkdown(ev.answer_text" in html


def test_index_is_self_contained(tmp_path):
    from fastapi.testclient import TestClient
    html = TestClient(create_app(_deps(tmp_path))).get("/").text
    # no external scripts or stylesheets — page must be self-contained
    assert "<script src" not in html
    assert "<link " not in html


def test_dashboard_route_serves_html(tmp_path):
    from fastapi.testclient import TestClient
    r = TestClient(create_app(_deps(tmp_path))).get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "id='view-overview'" in body or 'id="view-overview"' in body
    # shared app-nav bar with the Playground tab as the cross-nav back-link
    assert 'class="appbar"' in body
    assert 'class="apptab active">Dashboard' in body
    assert 'href="/"' in body


def test_index_has_dashboard_link(tmp_path):
    from fastapi.testclient import TestClient
    body = TestClient(create_app(_deps(tmp_path))).get("/").text
    # the Dashboard tab href still lives in the shared app bar
    assert 'href="/dashboard"' in body


def test_index_has_appbar_with_active_playground_tab(tmp_path):
    from fastapi.testclient import TestClient
    body = TestClient(create_app(_deps(tmp_path))).get("/").text
    assert 'class="appbar"' in body
    assert 'href="/"' in body
    assert 'href="/dashboard"' in body
    # Playground tab is active on the index
    assert 'class="apptab active">Playground' in body


# ---------------------------------------------------------------------------
# HTTP Basic Auth tests
# ---------------------------------------------------------------------------

def _deps_auth(tmp_path, env):
    """Like _deps but with an env mapping for auth configuration."""
    return WebDeps(
        config=_config(),
        build_adapters_for=lambda names: [],
        scoring_client=object(),
        scorer=lambda *a, **k: None,
        db_path=str(tmp_path / "w.sqlite"),
        env=env,
    )


def test_auth_required_when_password_set(tmp_path):
    from fastapi.testclient import TestClient
    env = {"APP_PASSWORD": "pw", "APP_USER": "abbvie"}
    app = create_app(_deps_auth(tmp_path, env))
    client = TestClient(app, raise_server_exceptions=False)

    # No credentials → 401
    r = client.get("/")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == 'Basic realm="EMA"'

    # Wrong password → 401
    r = client.get("/", auth=("abbvie", "wrong"))
    assert r.status_code == 401

    # Correct credentials → 200
    r = client.get("/", auth=("abbvie", "pw"))
    assert r.status_code == 200


def test_auth_protects_all_routes(tmp_path):
    from fastapi.testclient import TestClient
    env = {"APP_PASSWORD": "secret", "APP_USER": "abbvie"}
    app = create_app(_deps_auth(tmp_path, env))
    client = TestClient(app, raise_server_exceptions=False)

    # /api/targets without creds → 401
    assert client.get("/api/targets").status_code == 401

    # /dashboard without creds → 401
    assert client.get("/dashboard").status_code == 401

    # /api/targets with correct creds → 200
    assert client.get("/api/targets", auth=("abbvie", "secret")).status_code == 200

    # /dashboard with correct creds → 200
    assert client.get("/dashboard", auth=("abbvie", "secret")).status_code == 200

    # /api/ask without creds → 401
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 401

    # /api/ask with correct creds → not 401 (202)
    assert client.post("/api/ask", json={"question": "hi"}, auth=("abbvie", "secret")).status_code != 401


def test_auth_protects_ask_route(tmp_path):
    from fastapi.testclient import TestClient
    env = {"APP_PASSWORD": "pw", "APP_USER": "abbvie"}
    app = create_app(_deps_auth(tmp_path, env))
    client = TestClient(app, raise_server_exceptions=False)

    # No credentials → 401
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 401

    # Wrong password → 401
    assert client.post("/api/ask", json={"question": "hi"}, auth=("abbvie", "wrong")).status_code == 401

    # Correct credentials → auth passes (202, not 401)
    assert client.post("/api/ask", json={"question": "hi"}, auth=("abbvie", "pw")).status_code != 401


def test_auth_disabled_when_no_password(tmp_path):
    from fastapi.testclient import TestClient

    # Empty env dict → auth disabled
    app = create_app(_deps_auth(tmp_path, {}))
    client = TestClient(app)
    assert client.get("/").status_code == 200

    # env=None → auth disabled (existing tests path)
    app2 = create_app(_deps_auth(tmp_path, None))
    client2 = TestClient(app2)
    assert client2.get("/").status_code == 200
