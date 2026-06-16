"""FastAPI playground app. All collaborators are injected via WebDeps so the
app is testable with fakes and no network."""

from __future__ import annotations

import secrets as _secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from ema_poc.dashboard.dataset import collect_dataset
from ema_poc.dashboard.render import render_dashboard_html
from ema_poc.db import connect, init_schema
from ema_poc.playground.jobs import JobManager
from ema_poc.repositories import sandbox as S

_STATIC = Path(__file__).parent / "static"


def _check_rate(store: dict, ip: str, cap: int, now: float, window: float = 3600.0) -> bool:
    """Return True if allowed (and record the hit); False if over cap.
    cap <= 0 means unlimited. store maps ip -> list[timestamps]."""
    if cap <= 0:
        return True
    hits = [t for t in store.get(ip, []) if now - t < window]
    if len(hits) >= cap:
        store[ip] = hits
        return False
    hits.append(now)
    store[ip] = hits
    return True


@dataclass
class WebDeps:
    config: object                 # AppConfig
    build_adapters_for: Callable   # (selected_names: list[str]|None) -> list[adapter]
    scoring_client: object         # Anthropic client (or fake)
    scorer: Callable               # score_response-compatible callable
    db_path: str
    env: object = None             # Mapping of env vars; None means auth disabled
    job_submit_fn: object = None   # inject inline executor in tests; None = real threads


class AskBody(BaseModel):
    question: str
    persona: str | None = None
    brand_focus: str | None = None
    targets: list[str] | None = None


def create_app(deps: WebDeps) -> FastAPI:
    _security = HTTPBasic(auto_error=False)

    def _auth_dep(credentials: HTTPBasicCredentials | None = Depends(_security)):
        env = deps.env or {}
        password = env.get("APP_PASSWORD") or ""
        if not password:
            return  # auth disabled when no password configured
        user = env.get("APP_USER") or "abbvie"
        ok = (credentials is not None
              and _secrets.compare_digest(credentials.username, user)
              and _secrets.compare_digest(credentials.password, password))
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
                headers={"WWW-Authenticate": 'Basic realm="EMA"'},
            )

    app = FastAPI(title="EMA Playground", dependencies=[Depends(_auth_dep)])
    app.state.rate_store = {}

    @app.middleware("http")
    async def _no_store(request, call_next):
        # Every route here is dynamic + auth-gated: the dashboard is rebuilt per
        # request from live data, and responses may contain pharma content. Tell the
        # browser never to cache, so a stale or partial cached copy (e.g. one cut off
        # during a redeploy) can't be re-served — which would render empty dropdowns
        # and analytics.
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.state.jobs = JobManager(
        db_path=deps.db_path, build_adapters_for=deps.build_adapters_for,
        scoring_client=deps.scoring_client, scorer=deps.scorer, config=deps.config,
        id_factory=lambda: uuid4().hex,
        now_factory=lambda: datetime.now(timezone.utc).isoformat(),
        max_concurrent=int((deps.env or {}).get("PLAYGROUND_MAX_CONCURRENT_JOBS", "2") or "2"),
        submit_fn=deps.job_submit_fn)

    # Startup sweep: any RUNNING row is from a process that is no longer alive.
    _sweep_conn = connect(deps.db_path)
    try:
        init_schema(_sweep_conn)
        S.sweep_stale_running(_sweep_conn, finished_at=datetime.now(timezone.utc).isoformat())
    finally:
        _sweep_conn.close()

    @app.get("/")
    def index():
        return FileResponse(str(_STATIC / "index.html"))

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard():
        conn = connect(deps.db_path)
        try:
            init_schema(conn)
            dataset = collect_dataset(
                conn,
                abbvie_brands=deps.config.brands.abbvie_brands,
                competitor_brands=deps.config.brands.competitor_brands,
            )
        finally:
            conn.close()
        return HTMLResponse(render_dashboard_html(dataset, playground_url="/"))

    @app.get("/api/targets")
    def targets():
        return JSONResponse({
            "targets": [
                {"name": t.name, "adapter": t.adapter, "grounded": t.grounded}
                for t in deps.config.targets if t.enabled
            ]
        })

    @app.post("/api/ask", status_code=status.HTTP_202_ACCEPTED)
    def ask(request: Request, body: AskBody):
        if not body.question or not body.question.strip():
            raise HTTPException(status_code=400, detail="question is required")
        cap = int((deps.env or {}).get("PLAYGROUND_MAX_QUERIES_PER_HOUR", "60") or "60")
        ip = request.client.host if request.client else "unknown"
        if not _check_rate(app.state.rate_store, ip, cap, time.time()):
            raise HTTPException(status_code=429, detail="Query limit reached — try again later.")
        query_id = app.state.jobs.submit(
            question=body.question.strip(), persona=body.persona,
            brand_focus=body.brand_focus, selected_targets=body.targets)
        return {"query_id": query_id}

    @app.get("/api/queries")
    def list_queries():
        conn = connect(deps.db_path)
        try:
            init_schema(conn)
            rows = S.list_recent_queries(conn)
        finally:
            conn.close()
        return {"queries": [
            {"query_id": q.query_id, "question_text": q.question_text, "persona": q.persona,
             "brand_focus": q.brand_focus, "timestamp_utc": q.timestamp_utc,
             "status": q.status, "done_count": q.done_count, "total_count": q.total_count}
            for q in rows]}

    @app.get("/api/queries/{query_id}")
    def query_detail(query_id: str):
        conn = connect(deps.db_path)
        try:
            init_schema(conn)
            q = S.get_query(conn, query_id)
            if q is None:
                raise HTTPException(status_code=404, detail="query not found")
            responses = S.list_query_responses(conn, query_id)
        finally:
            conn.close()
        return {
            "query": {"query_id": q.query_id, "question_text": q.question_text,
                      "persona": q.persona, "brand_focus": q.brand_focus,
                      "status": q.status, "target_count": q.target_count,
                      "timestamp_utc": q.timestamp_utc, "error_text": q.error_text},
            "responses": [
                {"llm_name": r.llm_name, "grounded": r.grounded, "status": r.status,
                 "answer_text": r.answer_text, "tokens": r.response_tokens,
                 "finish_reason": r.finish_reason, "sentiment_score": r.sentiment_score,
                 "competitive_position": r.competitive_position,
                 "scoring_rationale": r.scoring_rationale,
                 "citations": [{"title": c.title, "url": c.url, "snippet": c.snippet}
                               for c in r.citations]}
                for r in responses]}

    app.state.deps = deps
    return app
