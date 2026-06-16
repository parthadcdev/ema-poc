# Surface Scoring Failures + Sandbox Rescore — Design

**Date:** 2026-06-16
**Status:** Approved
**Goal:** Stop silently swallowing playground scoring failures — record and show the
reason — and provide a tool to rescore the sandbox responses that were left unscored.

## Problem

`run_playground` (service.py) scores each successful response inside a broad
`try/except`. When scoring fails (e.g. the Anthropic API returned 400 "credit balance
too low"), the exception is swallowed: the response is saved **unscored** (`sentiment_
score = NULL`) with **no record of why**. The failure is invisible in the playground
and the dashboard, and there is no way to rescore those responses once the cause is
fixed. (This exact failure mode hid an out-of-credits incident.)

## Decisions (confirmed)

- Persist a `scoring_error` reason on the sandbox response; stop swallowing silently.
- Surface it in BOTH the playground answer card and the dashboard Responses view.
- Add a CLI `rescore-sandbox` command to (re)score unscored SUCCESS sandbox responses
  (run against the deployed app via `fly ssh console -C "ema --config-dir config_deploy
  rescore-sandbox"`). CLI, not a dashboard button — consistent with `ema score`.

## Components

### 1. Schema (`db.py`)
Additive nullable column via `_ADDITIVE_COLUMNS`:
`("sandbox_responses", "scoring_error", "TEXT")`.

### 2. Repository (`repositories/sandbox.py`)
- `set_response_score(...)` SET clause also sets `scoring_error = NULL` (a successful
  score clears any prior error).
- New `set_response_scoring_error(conn, *, sandbox_response_id, error, commit=True)` →
  `UPDATE ... SET scoring_error = ?` (rowcount-guarded, like the other setters).
- `SandboxResponse` dataclass gains `scoring_error: str | None`; `list_query_responses`
  (`SELECT *`) populates it.
- New `list_unscored_sandbox(conn) -> list[Row]` — the rescore candidates: join
  `sandbox_responses sr` to `sandbox_queries q` where `sr.status = 'SUCCESS'` AND
  `sr.sentiment_score IS NULL` AND `TRIM(COALESCE(sr.answer_text,'')) <> ''`; returns
  `sandbox_response_id, answer_text, q.brand_focus`.

### 3. Service (`playground/service.py`)
In the scoring `except` block, persist the reason before/with yielding the event:
```python
except Exception as exc:
    S.set_response_scoring_error(conn, sandbox_response_id=rid, error=str(exc)[:500])
    yield {"event": "score_error", "llm_name": adapter.name, "message": str(exc)}
```

### 4. Rescore module + CLI (`playground/rescore.py`, `cli.py`)
- `rescore_sandbox(conn, *, scoring_client, scorer, config) -> RescoreResult` where
  `RescoreResult` is a small dataclass `(scored: int, failed: int)`. For each candidate
  from `list_unscored_sandbox`: call `scorer(scoring_client, response_text=...,
  brand_focus=..., abbvie_brands=cfg.brands.abbvie_brands, competitor_brands=
  cfg.brands.competitor_brands, model=cfg.settings.scoring_model)`; on success
  `S.set_response_score(..., brand_mentions=result.brand_mentions)` (clears the error)
  and `scored += 1`; on `Exception as exc`
  `S.set_response_scoring_error(..., error=str(exc)[:500])` and `failed += 1`. Never
  raises on a per-item failure.
- CLI: a new `rescore-sandbox` subcommand. In `main`, mirror the `score` branch:
  `conn = _open_db(deps, config)`, `client = deps.make_scoring_client(deps.env)`,
  `from ema_poc.scoring.scorer import score_response`, then
  `r = rescore_sandbox(conn, scoring_client=client, scorer=score_response, config=config)`,
  `deps.out(f"Rescored {r.scored}, still failed {r.failed}")`. Add it to the command
  list in `_build_parser` and to the credential-required command set (line ~215 group)
  so credentials are validated.

### 5. API (`web/app.py`)
`GET /api/queries/{query_id}` — add `"scoring_error": r.scoring_error` to each entry
in the `responses` list.

### 6. Playground UI (`web/static/index.html`)
In `renderAnswerCard(ev)`: when `ev.scoring_error` is present (and there is no score),
render a `⚠ Scoring failed: <reason>` line via `esc(ev.scoring_error)` in place of the
score block. Existing score rendering unchanged when a score exists.

### 7. Dashboard (`dashboard/dataset.py`, `dashboard/render.py`)
- `dataset.py`: realtime records include `"scoring_error": <sr.scoring_error or None>`
  read from the sandbox row; monitoring records include `"scoring_error": None`
  (key parity — record key count 24 → 25; update the exact-key contract in
  `tests/dashboard/test_dataset.py`). The sandbox SELECT adds `sr.scoring_error`.
- `render.py` `renderResponses` detail panel: when `r.scoring_error` is set, add a
  `Scoring failed` row showing `esc(r.scoring_error)` (reuse `.dl`/`.dv`).

## Error handling
- `scoring_error` truncated to ~500 chars.
- Rescore is idempotent (only unscored SUCCESS rows); safe to run repeatedly. If the
  underlying cause persists (still no credits), it simply re-records the error and
  reports it in the `failed` count — never crashes.
- A FAILED response (no text) is never a rescore candidate.

## Testing (offline, fakes — no SDK/network)
- **schema** (`tests/test_schema_jobs.py` or similar): `sandbox_responses` has a
  `scoring_error` column after `init_schema` (incl. pre-existing DB).
- **repo** (`tests/repositories/test_sandbox_jobs.py`): `set_response_scoring_error`
  stores; `set_response_score` clears it to NULL; `list_query_responses` exposes it;
  `list_unscored_sandbox` returns only SUCCESS + null-sentiment + non-empty-text rows.
- **service** (`tests/playground/test_*`): a scorer that raises → the response row has
  `scoring_error` set (and sentiment still NULL).
- **rescore** (`tests/playground/test_rescore.py`): unscored candidate + a fake scorer
  → scored (sentiment set, error cleared), `RescoreResult.scored == 1`; a raising
  scorer → `scoring_error` set, `failed == 1`; idempotent (no candidates → 0/0).
- **cli** (`tests/test_cli*.py`): `rescore-sandbox` wires `_open_db` +
  `make_scoring_client` + `rescore_sandbox` and prints the summary; it's in the
  credential-required set.
- **api** (`tests/web/test_jobs_api.py`): `/api/queries/{id}` response entries include
  `scoring_error`.
- **dataset** (`tests/dashboard/test_dataset_realtime.py` + contract): realtime record
  carries `scoring_error`; monitoring record has `scoring_error=None`; key parity
  holds; exact-key contract updated to 25.
- **render/index** (`tests/dashboard/test_dashboard_render.py`, web index test):
  `renderResponses` shows a scoring-failed line; `index.html` `renderAnswerCard` shows
  the failure line; both stay self-contained.

## Out of scope (deferrable)
- Rescoring monitoring responses (the existing `ema score` path covers that pipeline).
- Auto-retry/backoff for scoring at run time (the `rescore-sandbox` command is the
  manual retry).
- A dashboard "rescore" button or scoring-cost reduction (e.g. cheaper scoring model) —
  separate concerns.
