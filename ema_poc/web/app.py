"""FastAPI playground app. All collaborators are injected via WebDeps so the
app is testable with fakes and no network."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ema_poc.db import connect, init_schema
from ema_poc.playground.service import run_playground

_STATIC = Path(__file__).parent / "static"


@dataclass
class WebDeps:
    config: object                 # AppConfig
    build_adapters_for: Callable   # (selected_names: list[str]|None) -> list[adapter]
    scoring_client: object         # Anthropic client (or fake)
    scorer: Callable               # score_response-compatible callable
    db_path: str


def create_app(deps: WebDeps) -> FastAPI:
    app = FastAPI(title="EMA Playground")

    @app.get("/")
    def index():
        return FileResponse(str(_STATIC / "index.html"))

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
        question: str = Query(...),
        persona: str | None = Query(None),
        brand_focus: str | None = Query(None),
        selected_targets: str | None = Query(None, alias="targets"),
    ):
        if not question or not question.strip():
            raise HTTPException(status_code=400, detail="question is required")

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
