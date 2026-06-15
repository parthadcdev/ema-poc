# Deployable Unified App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Password-protected, cost-capped, unified playground+dashboard app, Fly.io-deployable. **Repo = code only** (no data/secrets).

**Branch:** `feature/deployable-app`. **Spec:** `docs/superpowers/specs/2026-06-15-deployable-app-design.md`.

---

### Task 1: HTTP Basic Auth (env-configured, off when unset)

**Files:** `ema_poc/web/app.py`, `ema_poc/cli.py` (pass env into WebDeps), `tests/web/test_app.py`.

- READ `ema_poc/web/app.py` (`WebDeps`, `create_app`, the routes) and the cli `serve` branch that builds WebDeps.
- `WebDeps`: add `env: object = None` (a Mapping; default None). In the cli `serve` branch, pass `env=deps.env` (os.environ). Tests pass a dict.
- In `create_app(deps)`: build an auth dependency:
```python
import secrets as _secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
_security = HTTPBasic(auto_error=False)

def _auth_dep(credentials: HTTPBasicCredentials | None = Depends(_security)):
    env = deps.env or {}
    password = env.get("APP_PASSWORD") or ""
    if not password:
        return  # auth disabled when no password configured
    user = env.get("APP_USER") or "abbvie"
    ok = credentials is not None and _secrets.compare_digest(credentials.username, user) \
         and _secrets.compare_digest(credentials.password, password)
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized", headers={"WWW-Authenticate": 'Basic realm="EMA"'})
```
  Apply it to ALL routes by adding `dependencies=[Depends(_auth_dep)]` to the `FastAPI(...)` constructor (app-wide) OR to each route. App-wide is cleanest: `app = FastAPI(title="EMA Playground", dependencies=[Depends(_auth_dep)])`. (Verify the SSE route still streams under an app-wide dependency — it runs the dependency once before streaming, which is correct.)
- Tests (`tests/web/test_app.py`): build deps with `env={"APP_PASSWORD": "pw", "APP_USER": "abbvie"}`:
  - `GET /` with no auth → 401; with wrong creds → 401; with `auth=("abbvie","pw")` → 200.
  - `GET /api/targets` and `GET /dashboard` likewise require auth.
  - With `env={}` (no password) → `GET /` returns 200 without creds (auth disabled). This keeps ALL existing tests (which build WebDeps without env) working — ensure WebDeps.env default None → `{}` → disabled.
- Confirm the full existing web test-suite still passes (they construct WebDeps without env → auth disabled).

### Task 2: Per-client query cap on the ask endpoint

**Files:** `ema_poc/web/app.py`, `tests/web/test_stream.py`.

- Add an in-memory rolling-window limiter for `GET /api/ask/stream`, keyed by `request.client.host`. Read `int(env.get("PLAYGROUND_MAX_QUERIES_PER_HOUR", "60"))`; `0` = unlimited.
- Implementation: a dict on `app.state` mapping ip -> list[timestamps]; on each ask, drop timestamps older than 3600s, if `len >= cap` → `raise HTTPException(429, "Query limit reached, try again later.")` BEFORE opening the DB / building adapters; else append now and proceed. Inject the clock for tests: `app.state.now = time.monotonic` (or accept via a module-level overridable). Simplest testable design: a small helper `_check_rate(app, ip, cap, now)` pure function + the route calls it with `time.time()`; tests call the helper directly OR set a tiny cap and call the route repeatedly (the route needs the `request` to get the ip — use FastAPI `Request`).
- The route gains a `request: Request` param to read `request.client.host`.
- Tests (`tests/web/test_stream.py`): with `env={"PLAYGROUND_MAX_QUERIES_PER_HOUR": "2"}` and the existing fake-adapters deps, call `/api/ask/stream` 3x; the 3rd → 429. With `"0"` → no limit (many calls OK). Use TestClient (same client = same ip). Keep the existing happy-path SSE test passing (default cap 60 won't trip it). If determinism on the rolling window is tricky, make the window/cap logic accept an injected `now` and unit-test `_check_rate` directly for the boundary, plus one route-level 429 test at cap=1.

### Task 3: Unified top app-nav (both views)

**Files:** `ema_poc/web/static/index.html`, `ema_poc/dashboard/render.py`, `tests/web/test_app.py`, `tests/dashboard/test_dashboard_render.py`.

- Add a shared **app bar** as the first element in `<body>` of BOTH:
  - Markup (same on both): `<div class="appbar"><span class="appbar-title">Evidence Monitoring Agent</span><nav class="apptabs"><a href="/" class="apptab{active}">Playground</a><a href="/dashboard" class="apptab{active}">Dashboard</a></nav></div>`. On the playground, the Playground tab is active; on the dashboard, the Dashboard tab is active.
  - Replace the existing ad-hoc `navlink` (playground header → Dashboard) and `backlink` (dashboard → Playground) with this unified bar. KEEP a `/dashboard` link on the playground and a `/` link on the dashboard (tests + nav depend on these hrefs existing). The dashboard's `render_dashboard_html(dataset, *, playground_url=None)` signature stays; when `playground_url` is set (served route) the Playground tab points to it, else to `/`.
  - Style `.appbar`/`.apptab` in BOTH files' CSS in the AbbVie theme (navy bar, magenta active underline/state), consistent. Keep self-contained.
- The dashboard's existing left section side-nav (Overview/Marketing/Medical/Responses) stays BELOW the app bar (unchanged ids/data-section).
- Tests: index contains `class="appbar"` + `href="/dashboard"` + `href="/"`; dashboard output contains `class="appbar"` + both tab hrefs; the Dashboard tab is active on the dashboard and Playground tab active on the index. Existing self-contained + marker tests pass. (If a test asserted the old `navlink`/`backlink` text, update it to the appbar.)

### Task 4: Deploy artifacts (Dockerfile, fly.toml, config_deploy, DEPLOY.md)

**Files:** create `Dockerfile`, `.dockerignore`, `fly.toml`, `config_deploy/` (copy of config_demo with db_path), `DEPLOY.md`. Modify `.gitignore` only if needed (do NOT unignore ema_demo.sqlite — it must stay out of git but IN the docker build).

- `config_deploy/` = copy `config_demo/*` (settings.yaml, llm_targets.yaml, reference_corpus.yaml). Set `config_deploy/settings.yaml` `db_path: /app/data/ema_demo.sqlite`. (This dir is config only → safe to commit.)
- `Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY ema_poc ./ema_poc
RUN pip install --no-cache-dir .
COPY config_deploy ./config_deploy
COPY ema_demo.sqlite /app/data/ema_demo.sqlite
ENV PORT=8080
EXPOSE 8080
CMD ["ema","serve","--config-dir","config_deploy","--host","0.0.0.0","--port","8080"]
```
  (If `pip install .` needs the README/license referenced by pyproject, COPY those too — read pyproject for any `readme`/dynamic fields and copy what's required so the build succeeds.)
- `.dockerignore`:
```
.git
.venv
tests
**/__pycache__
*.pyc
.env
.env.*
docs
dashboard*.html
seed_questions.csv
questions_full.csv
demo_questions.csv
# keep ema_demo.sqlite (baked); exclude other sqlite/db artifacts:
ema.sqlite
*.db
.coverage
.pytest_cache
```
  (Do NOT list `ema_demo.sqlite` here — it must be in the build context.)
- `fly.toml`:
```toml
app = "ema-poc"   # change to your unique app name
primary_region = "iad"
[build]
[env]
  PORT = "8080"
  PLAYGROUND_MAX_QUERIES_PER_HOUR = "60"
[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0
[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```
- `DEPLOY.md`: prerequisites (flyctl, a Fly account), then:
  1. `fly launch --no-deploy --copy-config` (or `fly apps create <name>`), pick a unique app name + region.
  2. `fly secrets set OPENAI_API_KEY=... ANTHROPIC_API_KEY=... GOOGLE_API_KEY=... APP_USER=abbvie APP_PASSWORD=<choose-a-strong-password>`
  3. `fly deploy` (builds from the local dir → bakes in ema_demo.sqlite + config_deploy).
  4. `fly open` → share the https URL + the APP_PASSWORD with the product owner.
  Include: the cost caveat (auth-gated + capped via PLAYGROUND_MAX_QUERIES_PER_HOUR), the compliance caveat (third-party host, demo data only, no PII/PHI, not production secrets), how to change the cap, `fly scale count 0` to pause, and `fly apps destroy <name>` to tear down.
- Local Docker smoke (optional, document it): `docker build -t ema . && docker run -p 8080:8080 -e APP_PASSWORD=test -e OPENAI_API_KEY=... ema` then hit http://localhost:8080 (requires auth).

Run the FULL suite after each code task. No tests for the deploy artifacts (static infra files) beyond confirming config_deploy loads: `python -c "from ema_poc.config import load_config; print(load_config('config_deploy').settings.db_path)"` → `/app/data/ema_demo.sqlite`.

Commit per task.

---

## Self-Review Notes (author)
- Auth off when APP_PASSWORD unset → local/tests unaffected; on + constant-time compare when set.
- Query cap in-memory per-ip rolling hour; 429 before any LLM call; configurable; 0=off.
- Unified app bar on both; dashboard keeps section side-nav; render signature unchanged.
- Repo = code only: ema_demo.sqlite stays gitignored but is baked into the image via build context (NOT in .dockerignore); .env never copied (in .dockerignore + gitignore).
- DEPLOY.md = the human-run fly steps + caveats.
