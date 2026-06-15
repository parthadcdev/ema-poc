# Deployable Unified App (Auth + Nav + Fly.io) — Design

**Date:** 2026-06-15
**Status:** Approved
**Goal:** Publish the playground + dashboard as one seamless, password-protected
web app on Fly.io for a product-owner test.

## Decisions
- Full interactive app (playground + live dashboard).
- **HTTP Basic Auth** on all routes (env-configured; off when unset for local/tests).
- **Per-client query cap** on the ask endpoint (cost guard).
- **Unified top nav** (Playground · Dashboard) on both views.
- Host: **Fly.io**. **Repo gets code only** — demo data (`ema_demo.sqlite`) + `.env`
  never committed; the data is baked into the image from the local build context
  at `fly deploy` time. Secrets are Fly secrets only.

## 1. Auth (`ema_poc/web/app.py`)
- A FastAPI dependency `require_auth` (or middleware) applied to ALL routes
  (`/`, `/dashboard`, `/api/*`). Reads `APP_USER` (default "abbvie") and
  `APP_PASSWORD` from env (the env is read via `WebDeps`/an injected getter so
  tests control it). If `APP_PASSWORD` is unset/empty → **auth disabled** (local
  `ema serve` + tests unaffected). If set → enforce HTTP Basic, constant-time
  compare (`secrets.compare_digest`), 401 + `WWW-Authenticate: Basic realm="EMA"`
  on failure.
- `WebDeps` gains `auth: tuple[str|None, str|None]` (user, password) or reads from
  an injected `env` mapping; `create_app` wires the dependency. Default_deps/CLI
  pass `os.environ`.

## 2. Per-client query cap (`ema_poc/web/app.py`)
- A small in-memory rolling-window limiter on `GET /api/ask/stream`, keyed by
  client IP (`request.client.host`). Config via env `PLAYGROUND_MAX_QUERIES_PER_HOUR`
  (default 60; `0`/unset = unlimited). On exceed → HTTP 429 with a clear message
  (before any LLM call). Window = 1 hour rolling. In-memory dict (per-process; fine
  for a single-instance Fly app).

## 3. Unified top nav
- A shared **app bar** at the very top of BOTH the playground (`index.html`) and
  the dashboard (`render.py`): the app title "Evidence Monitoring Agent" + two tabs
  **Playground** (`/`) and **Dashboard** (`/dashboard`), with the current one
  marked active. Styled in the AbbVie theme, consistent across both. The dashboard
  keeps its existing left section side-nav below the app bar. Replaces/absorbs the
  existing ad-hoc cross-links (`navlink`/`backlink`). All existing ids/markers
  preserved.

## 4. Serve / container
- `ema serve` already binds `--host`/`--port`. Container CMD:
  `ema serve --config-dir config_deploy --host 0.0.0.0 --port 8080`.
- `config_deploy/` = a committed config dir (copy of config_demo: GPT-5.5 + gemini
  + claude targets, demo brands, reference corpus) whose `settings.yaml` `db_path`
  points at the baked demo DB path (e.g. `/app/data/ema_demo.sqlite`). Config has
  no secrets (api_key_env names only) → safe to commit.

## 5. Deploy artifacts (committed except the data)
- `Dockerfile` — `python:3.12-slim`; `pip install .`; copy `ema_poc/`, `config_deploy/`,
  and `ema_demo.sqlite` (from build context — gitignored but present locally) to
  `/app/data/`; expose 8080; `CMD ["ema","serve","--config-dir","config_deploy",
  "--host","0.0.0.0","--port","8080"]`.
- `.dockerignore` — exclude `.git`, `.venv`, tests, `__pycache__`, `.env`, other
  `*.sqlite` EXCEPT `ema_demo.sqlite` (so the demo data IS included in the build).
- `fly.toml` — app name placeholder, `internal_port = 8080`, `force_https = true`,
  auto-stop/start machines, 1 shared-cpu instance, `[env]` PORT=8080.
- `DEPLOY.md` — exact commands: install flyctl, `fly launch --no-deploy`,
  `fly secrets set OPENAI_API_KEY=… ANTHROPIC_API_KEY=… GOOGLE_API_KEY=…
  APP_USER=… APP_PASSWORD=…`, `fly deploy`, then open the URL + share the password.
  Includes the compliance/cost caveats and how to scale down / destroy.

## Testing (offline)
- Auth: with `APP_PASSWORD` set, requests without/with-wrong Basic creds → 401;
  correct creds → 200; with `APP_PASSWORD` unset → all routes open (no auth).
  TestClient with `auth=` and headers.
- Query cap: with `PLAYGROUND_MAX_QUERIES_PER_HOUR=2`, the 3rd ask within the
  window → 429 (inject a fake clock / monotonic so the test is deterministic; cap
  logic takes an injectable `now`/counter store).
- Nav: index + `/dashboard` both contain the app-bar with Playground + Dashboard
  links; active state correct. Self-contained preserved.
- All existing web/dashboard tests stay green.

## Security / compliance caveats (documented in DEPLOY.md)
- Public URL spends real API budget — auth-gated + query-capped, but the password
  holder can spend. Don't share the password widely.
- Third-party host (Fly) + AbbVie demo data: POC tradeoff; no PII/PHI; not for
  production data (SE-004). Secrets only as Fly secrets; data not in the repo.

## Out of scope (deferrable)
- Real user accounts / SSO; per-user quotas; a persistent Fly volume (demo data
  resets to the baked snapshot on redeploy — acceptable for a test).
