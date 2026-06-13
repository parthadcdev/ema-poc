"""FastAPI playground app. All collaborators are injected via WebDeps so the
app is testable with fakes and no network."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

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

    app.state.deps = deps
    return app
