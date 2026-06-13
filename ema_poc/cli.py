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
    build_dashboard: Callable | None = None
    serve_app: Callable | None = None


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
    from ema_poc.dashboard.build import build_dashboard
    from ema_poc.scoring.pipeline import score_pending

    def _serve_app(app, *, host, port):
        import uvicorn
        uvicorn.run(app, host=host, port=port)

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
        build_dashboard=build_dashboard,
        serve_app=_serve_app,
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
    p_run.add_argument("--run-id", dest="run_id", default=None,
                       help="Resume an existing run by id (re-dispatches only uncaptured work)")
    p_run.add_argument("--score", action="store_true", help="Score responses after the run")

    sub.add_parser("dry-run", help="Validate config + target connectivity (no writes)")
    sub.add_parser("score", help="Score unscored responses")
    sub.add_parser("healthcheck", help="Check connectivity to all targets")

    p_imp = sub.add_parser("import-questions", help="Import questions from CSV/Excel")
    p_imp.add_argument("path")

    p_dash = sub.add_parser("dashboard", help="Generate the self-contained HTML dashboard")
    p_dash.add_argument("--out", default="dashboard.html")

    p_serve = sub.add_parser("serve", help="Launch the real-time playground web UI")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)

    return parser.parse_args(argv)


def _open_db(deps: Deps, config):
    conn = deps.connect(config.settings.db_path)
    deps.init_schema(conn)
    return conn


def main(argv=None, deps: Deps | None = None) -> int:
    deps = deps or default_deps()
    args = _parse_args(argv)
    config = deps.load_config(args.config_dir)

    if args.command in ("run", "dry-run", "score", "healthcheck", "serve"):
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

    if args.command == "dashboard":
        conn = _open_db(deps, config)
        path = deps.build_dashboard(conn, args.out)
        deps.out(f"Dashboard written to {path}")
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

    if args.command == "serve":
        from ema_poc.web.app import create_app, WebDeps
        from ema_poc.config import AppConfig
        from ema_poc.scoring.scorer import score_response

        def build_adapters_for(names):
            if names:
                wanted = set(names)
                filtered = [t for t in config.targets if t.name in wanted and t.enabled]
            else:
                filtered = [t for t in config.targets if t.enabled]
            sub_cfg = AppConfig(settings=config.settings, brands=config.brands, targets=filtered)
            return deps.build_adapters(sub_cfg, deps.env)

        web_deps = WebDeps(
            config=config,
            build_adapters_for=build_adapters_for,
            scoring_client=deps.make_scoring_client(deps.env),
            scorer=score_response,
            db_path=config.settings.db_path,
        )
        app = create_app(web_deps)
        deps.out(f"Playground on http://{args.host}:{args.port} (Ctrl-C to stop)")
        deps.serve_app(app, host=args.host, port=args.port)
        return 0

    # run
    conn = _open_db(deps, config)
    adapters = deps.build_adapters(config, deps.env)
    summary = deps.run(
        conn, adapters, config,
        run_id=args.run_id,
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
