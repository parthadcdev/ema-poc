"""Operator CLI (FR-209/210/501/506, NF-008/009).

Command logic dispatches through an injectable Deps bundle so it can be tested
without network or vendor SDKs. default_deps() wires the real implementations;
vendor SDKs are imported lazily only when a real run/score happens."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date

from ema_poc.config import ConfigError
from ema_poc.coverage import format_coverage_report
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
    coverage: Callable | None = None
    freeze_baseline: Callable | None = None
    detect_drift: Callable | None = None
    make_embedding_client: Callable | None = None
    check_hallucinations: Callable | None = None
    load_reference_corpus: Callable | None = None
    compute_consensus: Callable | None = None
    generate_questions: Callable | None = None


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
    from ema_poc.coverage import question_effectiveness
    from ema_poc.dashboard.build import build_dashboard
    from ema_poc.scoring.pipeline import score_pending
    from ema_poc.drift.baseline import freeze_baseline
    from ema_poc.drift.detector import detect_drift
    from ema_poc.drift.embeddings import default_embedding_client
    from ema_poc.hallucination.pipeline import check_pending
    from ema_poc.hallucination.corpus import load_reference_corpus
    from ema_poc.consensus.compute import compute_consensus
    from ema_poc.suggest.pipeline import generate_and_store

    def _serve_app(app, *, host, port):
        import uvicorn
        uvicorn.run(app, host=host, port=port)

    def _make_embedding_client(env, config):
        key = env.get(config.drift.embedding_api_key_env)
        return default_embedding_client(key, config.drift.embedding_model)

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
        coverage=question_effectiveness,
        freeze_baseline=freeze_baseline,
        detect_drift=detect_drift,
        make_embedding_client=_make_embedding_client,
        check_hallucinations=check_pending,
        load_reference_corpus=load_reference_corpus,
        compute_consensus=compute_consensus,
        generate_questions=generate_and_store,
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
    p_run.add_argument("--backfill-for", dest="backfill_for", default=None,
                       help="Tag this run as a backfill for a missed date (YYYY-MM-DD)")
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

    p_cov = sub.add_parser("coverage", help="Flag low-value questions (chronic NOT_MENTIONED)")
    p_cov.add_argument("--min-responses", type=int, default=3)
    p_cov.add_argument("--not-mentioned-threshold", type=float, default=0.8)

    p_bf = sub.add_parser("baseline-freeze", help="Freeze the v0 drift baseline (one-time)")
    p_bf.add_argument("--force", action="store_true", help="Re-freeze existing baselines")

    sub.add_parser("drift", help="Detect semantic drift vs the frozen baseline and raise alerts")

    sub.add_parser("check-hallucinations", help="Flag responses that contradict the reference corpus")

    sub.add_parser("consensus", help="Compute majority-vote consensus across samples + variance alerts")

    p_sug = sub.add_parser("suggest-questions", help="Propose new questions for coverage gaps (stored PENDING for Medical Affairs)")
    p_sug.add_argument("--count", type=int, default=10)

    return parser.parse_args(argv)


def _open_db(deps: Deps, config):
    conn = deps.connect(config.settings.db_path)
    deps.init_schema(conn)
    return conn


def main(argv=None, deps: Deps | None = None) -> int:
    deps = deps or default_deps()
    args = _parse_args(argv)
    config = deps.load_config(args.config_dir)

    backfill_for = getattr(args, "backfill_for", None)
    if backfill_for is not None:
        try:
            args.backfill_for = date.fromisoformat(backfill_for).isoformat()
        except ValueError:
            raise ConfigError(
                f"Invalid --backfill-for date: {backfill_for!r} (expected YYYY-MM-DD)"
            )

    if args.command in ("run", "dry-run", "score", "healthcheck", "serve", "drift", "check-hallucinations", "suggest-questions"):
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
        from datetime import datetime, timezone
        path = deps.build_dashboard(
            conn, args.out,
            abbvie_brands=config.brands.abbvie_brands,
            competitor_brands=config.brands.competitor_brands,
            now=datetime.now(timezone.utc).isoformat(),
        )
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

    if args.command == "coverage":
        conn = _open_db(deps, config)
        items = deps.coverage(
            conn,
            min_responses=args.min_responses,
            not_mentioned_threshold=args.not_mentioned_threshold,
        )
        deps.out(format_coverage_report(items))
        return 0

    if args.command == "baseline-freeze":
        conn = _open_db(deps, config)
        from datetime import datetime, timezone
        n = deps.freeze_baseline(conn, now=datetime.now(timezone.utc).isoformat(), force=args.force)
        deps.out(f"Froze {n} baseline(s).")
        return 0

    if args.command == "drift":
        conn = _open_db(deps, config)
        from datetime import datetime, timezone
        client = deps.make_embedding_client(deps.env, config)
        summary = deps.detect_drift(conn, client=client, config=config,
                                    now=datetime.now(timezone.utc).isoformat())
        deps.out(f"Drift: compared {summary.compared}, drifted {summary.drifted}.")
        return 0

    if args.command == "check-hallucinations":
        conn = _open_db(deps, config)
        corpus = deps.load_reference_corpus(args.config_dir)
        client = deps.make_scoring_client(deps.env)
        summary = deps.check_hallucinations(conn, client=client, config=config, corpus=corpus)
        deps.out(f"Checked {summary.checked}, alerts raised {summary.alerts_raised}.")
        return 0

    if args.command == "consensus":
        conn = _open_db(deps, config)
        summary = deps.compute_consensus(conn)
        deps.out(f"Consensus: {summary.groups} group(s), variance alerts {summary.alerts_raised}.")
        return 0

    if args.command == "suggest-questions":
        conn = _open_db(deps, config)
        client = deps.make_scoring_client(deps.env)
        summary, proposals = deps.generate_questions(conn, client=client, config=config, count=args.count)
        deps.out(
            f"Proposed {summary.proposed}, stored {summary.stored} PENDING, "
            f"skipped {summary.skipped} duplicate(s)."
        )
        for p in proposals:
            deps.out(f"  [{p.persona}/{p.domain}/{p.brand_focus}] {p.question_text}")
            deps.out(f"      rationale: {p.rationale}")
        return 0

    # run
    conn = _open_db(deps, config)
    adapters = deps.build_adapters(config, deps.env)
    summary = deps.run(
        conn, adapters, config,
        run_id=args.run_id,
        persona=args.persona, therapeutic_area=args.therapeutic_area,
        brand_focus=args.brand_focus, domain=args.domain,
        backfill_for=args.backfill_for,
    )
    scoring = None
    if args.score:
        client = deps.make_scoring_client(deps.env)
        scoring = deps.score_pending(conn, client=client, config=config)
    deps.out(format_run_report(summary, scoring))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
