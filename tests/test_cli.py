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


# ---------------------------------------------------------------------------
# coverage command tests
# ---------------------------------------------------------------------------

def test_coverage_command_returns_zero_and_prints_report():
    from ema_poc.coverage import QuestionEffectiveness

    stub_items = [
        QuestionEffectiveness(
            question_id="Q1",
            question_text="Does BrandX help with asthma?",
            brand_focus="BrandX",
            total_scored=4,
            not_mentioned=4,
            not_mentioned_rate=1.0,
            low_value=True,
        ),
        QuestionEffectiveness(
            question_id="Q2",
            question_text="What are the benefits of BrandY?",
            brand_focus="BrandY",
            total_scored=3,
            not_mentioned=1,
            not_mentioned_rate=1 / 3,
            low_value=False,
        ),
    ]

    def _fake_coverage(conn, *, min_responses, not_mentioned_threshold):
        return stub_items

    deps, out, calls = _fake_deps(coverage=_fake_coverage)
    rc = main(["coverage"], deps=deps)

    assert rc == 0
    full_output = "\n".join(out)
    assert "LOW-VALUE" in full_output
    assert "Q1" in full_output
    assert "Q2" in full_output
    assert "flagged low-value" in full_output


def test_coverage_command_passes_cli_args_to_function():
    received = {}

    def _fake_coverage(conn, *, min_responses, not_mentioned_threshold):
        received["min_responses"] = min_responses
        received["not_mentioned_threshold"] = not_mentioned_threshold
        return []

    deps, out, _ = _fake_deps(coverage=_fake_coverage)
    rc = main(
        ["coverage", "--min-responses", "5", "--not-mentioned-threshold", "0.9"],
        deps=deps,
    )

    assert rc == 0
    assert received["min_responses"] == 5
    assert abs(received["not_mentioned_threshold"] - 0.9) < 1e-9
    full_output = "\n".join(out)
    assert "No scored responses" in full_output


def test_coverage_command_does_not_validate_credentials():
    """coverage is read-only — it must NOT call validate_credentials."""
    validated = {"called": False}

    def _validate(config, env):
        validated["called"] = True

    deps, out, _ = _fake_deps(
        validate_credentials=_validate,
        coverage=lambda conn, **kw: [],
    )
    main(["coverage"], deps=deps)
    assert validated["called"] is False


# ---------------------------------------------------------------------------
# baseline-freeze command tests
# ---------------------------------------------------------------------------

def test_baseline_freeze_calls_freeze_and_prints_count():
    """baseline-freeze calls freeze_baseline and prints the count."""
    deps, out, _ = _fake_deps(
        freeze_baseline=lambda conn, **k: 5,
    )
    rc = main(["baseline-freeze"], deps=deps)
    assert rc == 0
    assert any("5" in line for line in out)


def test_baseline_freeze_forwards_force_flag():
    """--force is forwarded to freeze_baseline as force=True."""
    captured = {}

    def _fake_freeze(conn, *, now, force=False):
        captured["force"] = force
        return 3

    deps, out, _ = _fake_deps(freeze_baseline=_fake_freeze)
    rc = main(["baseline-freeze", "--force"], deps=deps)
    assert rc == 0
    assert captured["force"] is True


def test_baseline_freeze_without_force_passes_false():
    """Without --force, force kwarg is False."""
    captured = {}

    def _fake_freeze(conn, *, now, force=False):
        captured["force"] = force
        return 2

    deps, out, _ = _fake_deps(freeze_baseline=_fake_freeze)
    rc = main(["baseline-freeze"], deps=deps)
    assert rc == 0
    assert captured["force"] is False


def test_baseline_freeze_does_not_require_credentials():
    """baseline-freeze is local/read-only — no credential validation needed."""
    validated = {"called": False}

    def _validate(config, env):
        validated["called"] = True

    deps, out, _ = _fake_deps(
        validate_credentials=_validate,
        freeze_baseline=lambda conn, **k: 0,
        # Remove API keys to show credentials aren't checked
        env={},
    )
    rc = main(["baseline-freeze"], deps=deps)
    assert rc == 0
    assert validated["called"] is False


# ---------------------------------------------------------------------------
# drift command tests
# ---------------------------------------------------------------------------

def test_drift_builds_client_and_calls_detect():
    """drift calls make_embedding_client and detect_drift, prints compared/drifted."""
    from types import SimpleNamespace

    client_built = {}

    def _make_client(env, config):
        client_built["called"] = True
        return object()

    def _detect(conn, *, client, config, now):
        return SimpleNamespace(compared=3, drifted=1)

    deps, out, _ = _fake_deps(
        make_embedding_client=_make_client,
        detect_drift=_detect,
    )
    rc = main(["drift"], deps=deps)
    assert rc == 0
    assert client_built.get("called") is True
    full_output = "\n".join(out)
    assert "3" in full_output
    assert "1" in full_output


def test_drift_validates_credentials():
    """drift is in the credential-validation tuple."""
    validated = {"called": False}

    def _validate(config, env):
        validated["called"] = True

    from types import SimpleNamespace

    deps, out, _ = _fake_deps(
        validate_credentials=_validate,
        make_embedding_client=lambda env, config: object(),
        detect_drift=lambda conn, **k: SimpleNamespace(compared=0, drifted=0),
    )
    main(["drift"], deps=deps)
    assert validated["called"] is True
