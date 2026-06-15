"""FastAPI playground app. All collaborators are injected via WebDeps so the
app is testable with fakes and no network."""

from __future__ import annotations

import json
import secrets as _secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from ema_poc.dashboard.dataset import collect_dataset
from ema_poc.dashboard.render import render_dashboard_html
from ema_poc.db import connect, init_schema
from ema_poc.playground.service import run_playground

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

    @app.get("/api/ask/stream")
    def ask_stream(
        request: Request,
        question: str = Query(...),
        persona: str | None = Query(None),
        brand_focus: str | None = Query(None),
        selected_targets: str | None = Query(None, alias="targets"),
    ):
        if not question or not question.strip():
            raise HTTPException(status_code=400, detail="question is required")

        cap = int((deps.env or {}).get("PLAYGROUND_MAX_QUERIES_PER_HOUR", "60") or "60")
        ip = request.client.host if request.client else "unknown"
        if not _check_rate(app.state.rate_store, ip, cap, time.time()):
            raise HTTPException(status_code=429, detail="Query limit reached — try again later.")

        selected = [t.strip() for t in selected_targets.split(",")] if selected_targets else None
        cfg = deps.config
        now = datetime.now(timezone.utc).isoformat()

        def event_stream():
            conn = connect(deps.db_path)
            init_schema(conn)
            try:
                adapters = deps.build_adapters_for(selected)
                gen = run_playground(
                    conn, adapters=adapters, scoring_client=deps.scoring_client,
                    scorer=deps.scorer,
                    abbvie_brands=cfg.brands.abbvie_brands,
                    competitor_brands=cfg.brands.competitor_brands,
                    system_prompts=cfg.settings.system_prompts,
                    question_text=question.strip(), persona=persona, brand_focus=brand_focus,
                    model=cfg.settings.scoring_model,
                    id_factory=lambda: uuid4().hex,
                    now=now,
                    max_retries=cfg.settings.max_retries,
                    backoff=cfg.settings.backoff_seconds,
                )
                for event in gen:
                    yield "data: " + json.dumps(event) + "\n\n"
            finally:
                conn.close()

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    app.state.deps = deps
    return app
