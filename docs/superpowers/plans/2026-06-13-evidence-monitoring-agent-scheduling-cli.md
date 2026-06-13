# Evidence Monitoring Agent — Scheduling & CLI Implementation Plan (Phase 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the operator CLI and scheduling surface that wires the whole pipeline together: scheduled/ad-hoc and subset runs, a dry-run/health-check connectivity probe, a standalone scoring command, question import, a run-summary report, an optional run-completion notification webhook, and cron documentation (FR-209/210/501/502/506, NF-008/009, FR-505).

**Architecture:** A single `ema_poc/cli.py` with an argparse dispatcher whose collaborators are bundled in an injectable `Deps` dataclass (real implementations by default; fakes in tests) — so the command dispatch is fully testable without network or vendor SDKs. Supporting modules: `connectivity.py` (probe each adapter), `reporting.py` (format run/health reports), `notify.py` (optional webhook). Subset filtering is a backward-compatible addition to the merged `runner.run`. No vendor SDK is imported at module load; the scoring client and adapters are built lazily only on real runs.

**Tech Stack:** Python 3.11+, stdlib `argparse` + `urllib`, Phases 1–5 (merged to `develop`). Tests use fake adapters/clients/deps — the suite runs without the vendor SDKs installed.

**Spec:** `docs/superpowers/specs/2026-06-13-evidence-monitoring-agent-poc-design.md` (§3 cli, FR-2/5, NF-008/009).

**Conventions:**
- CLI command logic is exercised via `main(argv, deps=...)` with a fake `Deps`; `default_deps()` (real wiring) is thin glue.
- Connectivity probes and notification use injectable callables so tests don't hit the network.
- Activate the venv with `. .venv/bin/activate` before pytest.

---

### Task 1: Subset filtering in the runner

**Files:**
- Modify: `ema_poc/agent/runner.py` (add filter params to `run`)
- Test: `tests/agent/test_runner_filters.py`

- [ ] **Step 1: Write the failing test**

`tests/agent/test_runner_filters.py`:
```python
from ema_poc.adapters.base import LLMResponse
from ema_poc.agent.runner import run
from ema_poc.config import (
    AppConfig, BrandConfig, LLMTargetConfig, PricingConfig, RateLimitConfig, Settings,
)
from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import add_question, approve_question
from ema_poc.repositories.responses import query_responses

NOW = "2026-06-13T02:00:00+00:00"


class _Adapter:
    model_version = "m"

    def __init__(self, name):
        self.name = name

    def query(self, system_prompt, question_text):
        return LLMResponse("x", "stop", "SUCCESS", prompt_tokens=1, completion_tokens=1)


def _config():
    return AppConfig(
        settings=Settings(system_prompts={"default": "ctx"}),
        brands=BrandConfig(),
        targets=[LLMTargetConfig(
            name="GPT-4o", adapter="openai", model_version="m", api_key_env="K",
            pricing=PricingConfig(input_per_1k=0.0, output_per_1k=0.0),
            rate_limit=RateLimitConfig(requests_per_minute=60, tokens_per_minute=1000),
        )],
    )


def _ids():
    n = {"i": 0}

    def f():
        n["i"] += 1
        return f"id-{n['i']}"

    return f


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def _seed(conn):
    add_question(conn, question_id="P1", question_text="a", persona="Provider",
                 domain="Safety", therapeutic_area="Immunology", now=NOW)
    approve_question(conn, "P1", approver_name="R", now=NOW)
    add_question(conn, question_id="P2", question_text="b", persona="Patient",
                 domain="Efficacy", therapeutic_area="Oncology", now=NOW)
    approve_question(conn, "P2", approver_name="R", now=NOW)


def test_run_filters_by_persona(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    run(conn, [_Adapter("GPT-4o")], _config(), run_id="run-1", persona="Provider",
        id_factory=_ids(), now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    qids = {r.question_id for r in query_responses(conn)}
    assert qids == {"P1"}  # only the Provider question ran
    conn.close()


def test_run_filters_by_domain_and_ta(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    run(conn, [_Adapter("GPT-4o")], _config(), run_id="run-1", domain="Efficacy",
        id_factory=_ids(), now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    assert {r.question_id for r in query_responses(conn)} == {"P2"}
    conn.close()


def test_run_no_filter_runs_all(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    run(conn, [_Adapter("GPT-4o")], _config(), run_id="run-1",
        id_factory=_ids(), now_factory=lambda: NOW, rate_limiters={}, sleep=lambda d: None)
    assert {r.question_id for r in query_responses(conn)} == {"P1", "P2"}
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/agent/test_runner_filters.py -v`
Expected: FAIL — `run()` does not accept `persona`/`domain` keyword args (TypeError).

- [ ] **Step 3: Modify `ema_poc/agent/runner.py`**

In the `run` signature, add four keyword-only filter params immediately after `config: AppConfig,` and before `run_id`:
```python
    persona=None,
    therapeutic_area: str | None = None,
    brand_focus: str | None = None,
    domain=None,
```
Then, immediately after the line `questions = active_approved(conn)`, insert the filter block:
```python
        def _ev(x):
            return x.value if hasattr(x, "value") else x

        if persona is not None:
            questions = [q for q in questions if q.persona.value == _ev(persona)]
        if therapeutic_area is not None:
            questions = [q for q in questions if q.therapeutic_area == therapeutic_area]
        if brand_focus is not None:
            questions = [q for q in questions if q.brand_focus == brand_focus]
        if domain is not None:
            questions = [q for q in questions if q.domain.value == _ev(domain)]
```
(Match the existing indentation of the surrounding function body — the `questions = active_approved(conn)` line is at one indent level inside `run`; the filter block goes at that same level.)

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/agent/test_runner_filters.py -v`
Expected: PASS (3 passed). Then `. .venv/bin/activate && pytest -q` to confirm no regression.

- [ ] **Step 5: Commit**

```bash
git add ema_poc/agent/runner.py tests/agent/test_runner_filters.py
git commit -m "feat: subset run filters (persona/TA/brand/domain) in runner"
```

---

### Task 2: Target connectivity check

**Files:**
- Create: `ema_poc/connectivity.py`
- Test: `tests/test_connectivity.py`

- [ ] **Step 1: Write the failing test**

`tests/test_connectivity.py`:
```python
from ema_poc.adapters.base import LLMResponse
from ema_poc.connectivity import TargetStatus, check_targets


class _OK:
    name = "GPT-4o"

    def query(self, system_prompt, question_text):
        return LLMResponse("pong", "stop", "SUCCESS")


class _Blocked:
    name = "Gemini"

    def query(self, system_prompt, question_text):
        return LLMResponse("", "blocked", "BLOCKED")


class _Down:
    name = "Claude"

    def query(self, system_prompt, question_text):
        raise RuntimeError("connection refused")


def test_check_targets_reports_status_per_adapter():
    statuses = check_targets([_OK(), _Blocked(), _Down()])
    by_name = {s.name: s for s in statuses}
    assert by_name["GPT-4o"].ok is True
    assert by_name["Gemini"].ok is True   # got a response (BLOCKED) -> reachable
    assert by_name["Claude"].ok is False  # raised -> unreachable
    assert "connection refused" in by_name["Claude"].detail
    assert isinstance(statuses[0], TargetStatus)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/test_connectivity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.connectivity'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/connectivity.py`:
```python
"""Probe each configured LLM target for reachability (FR-209 dry-run, NF-009
health-check). A probe that returns ANY response means the target is reachable;
an exception means it is not. Does not write to the repository."""

from __future__ import annotations

from dataclasses import dataclass

_PROBE_SYSTEM = "You are a connectivity probe. Reply with a single short word."
_PROBE_QUESTION = "ping"


@dataclass
class TargetStatus:
    name: str
    ok: bool
    detail: str


def check_targets(adapters) -> list[TargetStatus]:
    statuses: list[TargetStatus] = []
    for adapter in adapters:
        try:
            resp = adapter.query(_PROBE_SYSTEM, _PROBE_QUESTION)
            statuses.append(TargetStatus(adapter.name, True, resp.status))
        except Exception as exc:  # transport / auth failure -> unreachable
            statuses.append(TargetStatus(adapter.name, False, f"error: {exc}"))
    return statuses
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/test_connectivity.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/connectivity.py tests/test_connectivity.py
git commit -m "feat: target connectivity check for dry-run/health-check"
```

---

### Task 3: Run + health report formatting

**Files:**
- Create: `ema_poc/reporting.py`
- Test: `tests/test_reporting.py`

- [ ] **Step 1: Write the failing test**

`tests/test_reporting.py`:
```python
from ema_poc.agent.runner import RunSummary
from ema_poc.connectivity import TargetStatus
from ema_poc.reporting import format_health_report, format_run_report
from ema_poc.scoring.pipeline import ScoringSummary


def _run_summary():
    return RunSummary(
        run_id="run-1", questions_attempted=100, responses_captured=300,
        by_status={"SUCCESS": 290, "FAILED": 5, "TRUNCATED": 3, "BLOCKED": 2},
        failure_count=5, total_tokens=123456, est_cost=1.2345,
    )


def test_format_run_report_includes_counts_and_cost():
    text = format_run_report(_run_summary())
    assert "run-1" in text
    assert "300" in text  # responses captured
    assert "SUCCESS" in text
    assert "$1.2345" in text  # est cost formatted
    assert "scored" not in text  # no scoring summary given


def test_format_run_report_with_scoring():
    text = format_run_report(_run_summary(), ScoringSummary(scored=290, alerts_raised=12))
    assert "scored" in text
    assert "290" in text
    assert "12" in text  # alerts


def test_format_health_report():
    text = format_health_report([
        TargetStatus("GPT-4o", True, "SUCCESS"),
        TargetStatus("Claude", False, "error: timeout"),
    ])
    assert "OK" in text and "GPT-4o" in text
    assert "FAIL" in text and "Claude" in text
    assert "timeout" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/test_reporting.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.reporting'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/reporting.py`:
```python
"""Human-readable run-summary and health-check reports (NF-008, NF-009)."""

from __future__ import annotations

from ema_poc.agent.runner import RunSummary
from ema_poc.connectivity import TargetStatus
from ema_poc.scoring.pipeline import ScoringSummary


def format_run_report(
    summary: RunSummary, scoring: ScoringSummary | None = None
) -> str:
    lines = [
        f"Run {summary.run_id}",
        f"  questions attempted: {summary.questions_attempted}",
        f"  responses captured:  {summary.responses_captured}",
        f"  by status:           {summary.by_status}",
        f"  failures:            {summary.failure_count}",
        f"  total tokens:        {summary.total_tokens}",
        f"  estimated cost:      ${summary.est_cost:.4f}",
    ]
    if scoring is not None:
        lines += [
            f"  scored:              {scoring.scored}",
            f"  alerts raised:       {scoring.alerts_raised}",
        ]
    return "\n".join(lines)


def format_health_report(statuses: list[TargetStatus]) -> str:
    return "\n".join(
        f"[{'OK' if s.ok else 'FAIL'}] {s.name}: {s.detail}" for s in statuses
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/test_reporting.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/reporting.py tests/test_reporting.py
git commit -m "feat: run-summary and health-check report formatting"
```

---

### Task 4: Optional run-completion notification

**Files:**
- Modify: `ema_poc/config.py` (add `notify_webhook` to `Settings`)
- Create: `ema_poc/notify.py`
- Test: `tests/test_notify.py`

- [ ] **Step 1: Write the failing test**

`tests/test_notify.py`:
```python
from ema_poc.config import Settings
from ema_poc.notify import send_summary


def test_send_summary_posts_payload_via_injected_poster():
    captured = {}

    def poster(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return 200

    status = send_summary("https://hook.example/notify",
                          {"run_id": "run-1", "alerts": 3}, poster=poster)
    assert status == 200
    assert captured["url"] == "https://hook.example/notify"
    assert captured["payload"]["run_id"] == "run-1"


def test_settings_notify_webhook_defaults_none():
    assert Settings().notify_webhook is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/test_notify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.notify'`.

- [ ] **Step 3: Add `notify_webhook` to `Settings` in `ema_poc/config.py`**

In the `Settings` class, add (after `system_prompts`):
```python
    notify_webhook: str | None = None
```

- [ ] **Step 4: Write `ema_poc/notify.py`**

```python
"""Prototype run-completion notification (FR-505).

POSTs a JSON summary to a configured webhook. The poster is injectable so tests
don't hit the network; the default uses stdlib urllib."""

from __future__ import annotations


def _default_post(url: str, payload: dict) -> int:
    import json
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (configured URL)
        return resp.status


def send_summary(url: str, payload: dict, *, poster=_default_post) -> int:
    """POST `payload` to `url`, returning the HTTP status. Caller decides whether
    to send (only when a webhook is configured)."""
    return poster(url, payload)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/test_notify.py -v`
Expected: PASS (2 passed). Then `. .venv/bin/activate && pytest -q`.

- [ ] **Step 6: Commit**

```bash
git add ema_poc/config.py ema_poc/notify.py tests/test_notify.py
git commit -m "feat: optional run-completion notification webhook"
```

---

### Task 5: CLI dispatcher

**Files:**
- Create: `ema_poc/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
from dataclasses import dataclass

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.cli'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/cli.py`:
```python
"""Operator CLI (FR-209/210/501/506, NF-008/009).

Command logic dispatches through an injectable Deps bundle so it can be tested
without network or vendor SDKs. default_deps() wires the real implementations;
vendor SDKs are imported lazily only when a real run/score happens."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ema_poc.reporting import format_health_report, format_run_report


@dataclass
class Deps:
    load_config: Callable
    connect: Callable
    init_schema: Callable
    validate_credentials: Callable
    build_adapters: Callable
    make_scoring_client: Callable
    run: Callable
    score_pending: Callable
    check_targets: Callable
    import_csv: Callable
    import_excel: Callable
    env: Mapping
    out: Callable


def _make_scoring_client(env):
    import anthropic

    return anthropic.Anthropic(api_key=env.get("ANTHROPIC_API_KEY"))


def default_deps() -> Deps:
    import os

    from ema_poc.adapters.registry import build_adapters
    from ema_poc.agent.runner import run
    from ema_poc.config import load_config, validate_credentials
    from ema_poc.connectivity import check_targets
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories.questions import (
        import_questions_csv,
        import_questions_excel,
    )
    from ema_poc.scoring.pipeline import score_pending

    return Deps(
        load_config=load_config,
        connect=connect,
        init_schema=init_schema,
        validate_credentials=validate_credentials,
        build_adapters=build_adapters,
        make_scoring_client=_make_scoring_client,
        run=run,
        score_pending=score_pending,
        check_targets=check_targets,
        import_csv=import_questions_csv,
        import_excel=import_questions_excel,
        env=os.environ,
        out=print,
    )


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="ema", description="Evidence Monitoring Agent")
    parser.add_argument("--config-dir", default="config")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run the question bank against all targets")
    p_run.add_argument("--persona")
    p_run.add_argument("--ta", dest="therapeutic_area")
    p_run.add_argument("--brand", dest="brand_focus")
    p_run.add_argument("--domain")
    p_run.add_argument("--score", action="store_true", help="Score responses after the run")

    sub.add_parser("dry-run", help="Validate config + target connectivity (no writes)")
    sub.add_parser("score", help="Score unscored responses")
    sub.add_parser("healthcheck", help="Check connectivity to all targets")

    p_imp = sub.add_parser("import-questions", help="Import questions from CSV/Excel")
    p_imp.add_argument("path")

    return parser.parse_args(argv)


def _open_db(deps: Deps, config):
    conn = deps.connect(config.settings.db_path)
    deps.init_schema(conn)
    return conn


def main(argv=None, deps: Deps | None = None) -> int:
    deps = deps or default_deps()
    args = _parse_args(argv)
    config = deps.load_config(args.config_dir)

    if args.command in ("run", "dry-run", "score", "healthcheck"):
        deps.validate_credentials(config, deps.env)

    if args.command == "import-questions":
        conn = _open_db(deps, config)
        path = args.path
        n = (
            deps.import_excel(conn, path)
            if path.lower().endswith((".xlsx", ".xls"))
            else deps.import_csv(conn, path)
        )
        deps.out(f"Imported {n} questions from {path}")
        return 0

    if args.command in ("dry-run", "healthcheck"):
        adapters = deps.build_adapters(config, deps.env)
        statuses = deps.check_targets(adapters)
        deps.out(format_health_report(statuses))
        return 0 if all(s.ok for s in statuses) else 1

    if args.command == "score":
        conn = _open_db(deps, config)
        client = deps.make_scoring_client(deps.env)
        scoring = deps.score_pending(conn, client=client, config=config)
        deps.out(f"Scored {scoring.scored}, alerts raised {scoring.alerts_raised}")
        return 0

    # run
    conn = _open_db(deps, config)
    adapters = deps.build_adapters(config, deps.env)
    summary = deps.run(
        conn, adapters, config,
        persona=args.persona, therapeutic_area=args.therapeutic_area,
        brand_focus=args.brand_focus, domain=args.domain,
    )
    scoring = None
    if args.score:
        client = deps.make_scoring_client(deps.env)
        scoring = deps.score_pending(conn, client=client, config=config)
    deps.out(format_run_report(summary, scoring))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/test_cli.py -v`
Expected: PASS (6 passed). Then `. .venv/bin/activate && pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add ema_poc/cli.py tests/test_cli.py
git commit -m "feat: operator CLI (run/dry-run/score/import/healthcheck)"
```

---

### Task 6: CLI entry point, cron docs, and integration

**Files:**
- Modify: `pyproject.toml` (add console script + ensure package discovery)
- Modify: `README.md` (CLI usage + cron schedule)
- Test: `tests/test_cli_integration.py`

- [ ] **Step 1: Write the integration test**

`tests/test_cli_integration.py`:
```python
"""Drive the CLI end-to-end against a real temp DB with fake adapters/scorer:
import questions -> run -> score, asserting persisted responses, scores, and
that the run command reports a summary."""

from ema_poc.adapters.base import LLMResponse
from ema_poc.cli import Deps, main
from ema_poc.config import AppConfig, BrandConfig, Settings
from ema_poc.connectivity import check_targets
from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import approve_question, list_questions
from ema_poc.repositories.responses import query_responses
from ema_poc.repositories.scores import latest_score
from ema_poc.scoring.pipeline import score_pending
from ema_poc.scoring.scorer import ScoreResult


class _Adapter:
    model_version = "m"

    def __init__(self, name):
        self.name = name

    def query(self, system_prompt, question_text):
        return LLMResponse("Skyrizi is first-line.", "stop", "SUCCESS",
                           prompt_tokens=10, completion_tokens=20)


CSV = (
    "question_id,question_text,persona,domain,therapeutic_area,brand_focus\n"
    "Q1,Is Skyrizi first-line?,Provider,Comparative,Immunology,Skyrizi\n"
)


def _config():
    return AppConfig(
        settings=Settings(db_path="unused", system_prompts={"default": "ctx"},
                          scoring_model="claude-opus-4-8"),
        brands=BrandConfig(abbvie_brands=["Skyrizi"], competitor_brands=["Humira"]),
        targets=[],
    )


def _fake_scorer(client, *, response_text, **kw):
    return ScoreResult(
        sentiment_score=0.6, competitive_position="FIRST_LINE_RECOMMENDED",
        brand_mentions=["Skyrizi"], key_claims=["effective"], scoring_rationale="r",
    )


def test_cli_import_run_score_end_to_end(tmp_path):
    db_path = str(tmp_path / "ema.sqlite")
    conn = connect(db_path)
    init_schema(conn)
    out = []

    config = _config()

    def _score(c, *, client, config):
        return score_pending(c, client=client, config=config, scorer=_fake_scorer)

    deps = Deps(
        load_config=lambda d: config,
        connect=lambda p: conn,           # reuse the one temp connection
        init_schema=lambda c: None,        # already initialized
        validate_credentials=lambda config, env: None,
        build_adapters=lambda config, env: [_Adapter("GPT-4o")],
        make_scoring_client=lambda env: object(),
        run=__import__("ema_poc.agent.runner", fromlist=["run"]).run,
        score_pending=_score,
        check_targets=check_targets,
        import_csv=__import__("ema_poc.repositories.questions",
                              fromlist=["import_questions_csv"]).import_questions_csv,
        import_excel=lambda conn, path: 0,
        env={"ANTHROPIC_API_KEY": "k"},
        out=out.append,
    )

    # 1. import a question
    csv_path = tmp_path / "q.csv"
    csv_path.write_text(CSV)
    assert main(["import-questions", str(csv_path)], deps=deps) == 0
    assert [q.question_id for q in list_questions(conn)] == ["Q1"]

    # approve it so the runner will dispatch it
    approve_question(conn, "Q1", approver_name="Dr. A",
                     now="2026-06-13T00:00:00+00:00")

    # 2. run + score in one command
    assert main(["run", "--score"], deps=deps) == 0
    assert any("Run " in line for line in out)

    # response persisted and scored
    responses = query_responses(conn)
    assert len(responses) == 1
    assert latest_score(conn, responses[0].response_id).sentiment_score == 0.6

    conn.close()
```

- [ ] **Step 2: Run the integration test**

Run: `. .venv/bin/activate && pytest tests/test_cli_integration.py -v`
Expected: PASS (1 passed). If it fails, the failure points at a real wiring gap — fix the referenced module, do not weaken the test.

- [ ] **Step 3: Add the console script to `pyproject.toml`**

After the `[project.optional-dependencies]` section, add:
```toml
[project.scripts]
ema = "ema_poc.cli:main"

[tool.setuptools.packages.find]
include = ["ema_poc*"]
```
And ensure the `[build-system]` table exists at the top of the file (add it if missing):
```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 4: Append CLI + cron docs to `README.md`**

Add this section to `README.md` (use real triple-backtick fences):
```markdown
## CLI

After `pip install -e .`, the `ema` command is available:

- `ema run` — run the full approved question bank against all enabled targets.
- `ema run --persona Provider --domain Safety --score` — subset run, then score.
- `ema dry-run` — validate config + target connectivity without writing.
- `ema score` — score any unscored responses.
- `ema healthcheck` — check connectivity to all configured LLM APIs.
- `ema import-questions path/to/questions.csv` — import a question bank (CSV or .xlsx).

All commands accept `--config-dir` (default `config`). Required API keys come
from the environment (see `.env.example`).

## Scheduling (daily run)

The POC runs unattended via OS cron. Example crontab entry for a daily run at
02:00 UTC that also scores results:

```
0 2 * * *  cd /path/to/ema-poc && . .venv/bin/activate && ema run --score >> logs/cron.log 2>&1
```

Runs are resumable: re-invoking `ema run` continues an interrupted run without
re-submitting already-captured responses.
```

- [ ] **Step 5: Run the whole suite with coverage**

Run: `. .venv/bin/activate && pytest -q --cov` and `. .venv/bin/activate && pytest -q -W error::ResourceWarning`.
Expected: all green; no ResourceWarning. Note the coverage for `ema_poc/cli.py`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml README.md tests/test_cli_integration.py
git commit -m "feat: ema console script + cron docs; CLI integration test"
```

---

## Self-Review

**Spec coverage (Phase 6 scope):**
- FR-501/502 scheduled unattended daily run → cron docs + `ema run` entrypoint → Task 6.
- FR-506 ad-hoc/on-demand runs via CLI → `ema run` → Tasks 5, 6.
- FR-210 subset runs by persona/TA/brand/domain → runner filters + `ema run --persona/--ta/--brand/--domain` → Tasks 1, 5.
- FR-209 dry-run validates connectivity + config without writing → `ema dry-run` → `check_targets` → Tasks 2, 5.
- NF-009 health-check verifies connectivity, returns status → `ema healthcheck` → Tasks 2, 5.
- NF-008 run summary report → `format_run_report` printed by `ema run` → Tasks 3, 5.
- NF-014 estimated cost in summary → already computed by the runner; surfaced in the report → Task 3.
- FR-505 run-completion notification (prototype) → `notify.send_summary` webhook (config'd, off by default) → Task 4.
- FR-105 import without DB access → `ema import-questions` → Tasks 5, 6.

Deferred (correctly out of scope): the `ema dashboard` command + the dashboard itself (Phase 7); wiring `notify.send_summary` into `ema run` automatically (the prototype function + config flag exist; auto-invocation is a thin follow-on and the webhook is off by default per POC scope). The `_iso` helper extraction noted in Phase 5 remains a tracked cleanup.

**Placeholder scan:** No "TBD"/"add error handling"/"similar to" placeholders — every code and test step is complete.

**Type/name consistency:** `run`'s new filter kwargs (Task 1) match how `main` passes them (Task 5) and the CLI tests. `TargetStatus`/`check_targets` (Task 2) used by `reporting.format_health_report` (Task 3) and the CLI (Task 5). `format_run_report(RunSummary, ScoringSummary|None)` / `format_health_report(list[TargetStatus])` signatures match the CLI calls. `Deps` field names match `default_deps()` and the fake deps in tests. `send_summary(url, payload, *, poster)` matches its test. `Settings.notify_webhook` defaults None.
