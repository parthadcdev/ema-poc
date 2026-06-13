from ema_poc.agent.runner import RunSummary
from ema_poc.cli import Deps, main
from ema_poc.connectivity import TargetStatus
from ema_poc.scoring.pipeline import ScoringSummary


class _Config:
    class settings:
        db_path = "ema.sqlite"


def _fake_deps(**overrides):
    out_lines = []
    calls = {"run": None, "score": None, "validated": False, "imported": None}

    def _run(conn, adapters, config, **kw):
        calls["run"] = kw
        return RunSummary("run-1", 2, 4, {"SUCCESS": 4, "FAILED": 0,
                          "TRUNCATED": 0, "BLOCKED": 0}, 0, 40, 0.01)

    def _score(conn, *, client, config):
        calls["score"] = True
        return ScoringSummary(scored=4, alerts_raised=1)

    def _validate(config, env):
        calls["validated"] = True

    def _import_csv(conn, path):
        calls["imported"] = path
        return 7

    deps = Deps(
        load_config=lambda d: _Config(),
        connect=lambda p: "CONN",
        init_schema=lambda c: None,
        validate_credentials=_validate,
        build_adapters=lambda config, env: ["A1", "A2"],
        make_scoring_client=lambda env: "CLIENT",
        run=_run,
        score_pending=_score,
        check_targets=lambda adapters: [TargetStatus("GPT-4o", True, "SUCCESS")],
        import_csv=_import_csv,
        import_excel=lambda conn, path: 9,
        env={"ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k"},
        out=out_lines.append,
    )
    for k, v in overrides.items():
        setattr(deps, k, v)
    return deps, out_lines, calls


def test_run_command_executes_and_reports():
    deps, out, calls = _fake_deps()
    rc = main(["run"], deps=deps)
    assert rc == 0
    assert calls["validated"] is True
    assert calls["run"] is not None
    assert any("Run run-1" in line for line in out)


def test_run_with_filters_and_score():
    deps, out, calls = _fake_deps()
    rc = main(["run", "--persona", "Provider", "--score"], deps=deps)
    assert rc == 0
    assert calls["run"]["persona"] == "Provider"
    assert calls["score"] is True
    assert any("scored" in line for line in out)


def test_healthcheck_returns_zero_when_all_ok():
    deps, out, calls = _fake_deps()
    rc = main(["healthcheck"], deps=deps)
    assert rc == 0
    assert any("OK" in line and "GPT-4o" in line for line in out)


def test_healthcheck_returns_one_when_a_target_down():
    deps, out, calls = _fake_deps(
        check_targets=lambda adapters: [TargetStatus("Claude", False, "error: x")]
    )
    rc = main(["healthcheck"], deps=deps)
    assert rc == 1


def test_score_command():
    deps, out, calls = _fake_deps()
    rc = main(["score"], deps=deps)
    assert rc == 0
    assert calls["score"] is True
    assert any("Scored 4" in line for line in out)


def test_import_questions_csv():
    deps, out, calls = _fake_deps()
    rc = main(["import-questions", "questions.csv"], deps=deps)
    assert rc == 0
    assert calls["imported"] == "questions.csv"
    assert any("Imported 7" in line for line in out)


def test_dry_run_does_not_open_db_and_returns_one_when_down():
    opened = {"connect": False}

    def _connect(p):
        opened["connect"] = True
        return "CONN"

    deps, out, calls = _fake_deps(
        connect=_connect,
        check_targets=lambda adapters: [TargetStatus("Claude", False, "error: x")],
    )
    rc = main(["dry-run"], deps=deps)
    assert rc == 1  # a target is down
    assert opened["connect"] is False  # dry-run never opens the DB
    assert any("FAIL" in line for line in out)


def test_run_with_run_id_resumes():
    deps, out, calls = _fake_deps()
    rc = main(["run", "--run-id", "run-xyz"], deps=deps)
    assert rc == 0
    assert calls["run"]["run_id"] == "run-xyz"


def test_serve_builds_app_and_binds_localhost(tmp_path):
    from ema_poc.cli import main
    from ema_poc.config import AppConfig, Settings, BrandConfig, LLMTargetConfig, PricingConfig, RateLimitConfig

    recorded = {}

    def fake_serve_app(app, *, host, port):
        recorded["host"] = host
        recorded["port"] = port
        recorded["has_stream_route"] = any(
            getattr(r, "path", None) == "/api/ask/stream" for r in app.routes
        )

    target = LLMTargetConfig(
        name="fake-target",
        adapter="openai",
        model_version="gpt-4o",
        api_key_env="OPENAI_API_KEY",
        enabled=True,
        grounded=False,
        pricing=PricingConfig(input_per_1k=0.01, output_per_1k=0.03),
        rate_limit=RateLimitConfig(requests_per_minute=60, tokens_per_minute=100000),
    )
    config = AppConfig(
        settings=Settings(db_path=str(tmp_path / "ema.sqlite")),
        brands=BrandConfig(),
        targets=[target],
    )

    deps, out_lines, calls = _fake_deps(
        load_config=lambda d: config,
        build_adapters=lambda cfg, env: [],
        make_scoring_client=lambda env: "FAKE_CLIENT",
    )
    deps.serve_app = fake_serve_app

    rc = main(["serve", "--port", "9999"], deps=deps)
    assert rc == 0
    assert recorded["host"] == "127.0.0.1"
    assert recorded["port"] == 9999
    assert recorded["has_stream_route"] is True
