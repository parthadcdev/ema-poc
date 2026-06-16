# Per-Response Rescore (Dashboard) — Design

**Date:** 2026-06-16
**Status:** Approved
**Goal:** Let a user rescore a single realtime (sandbox) response from the dashboard
Responses view — e.g. to retry a response that failed scoring once the cause (credits)
is fixed.

## Decisions (confirmed)

- The control lives in the **Dashboard Responses view** (a "Rescore" button per
  realtime response in the detail panel).
- **Realtime (sandbox) responses only.** Monitoring responses keep using the existing
  `ema score` pipeline (the `scores` table) — they have no sandbox id.
- Clicking updates the current page's in-memory `DATA` and re-renders, so the new
  score (or failure) refreshes the row **and** the charts live (no page reload). The
  DB is updated, so any fresh load reflects it.

## Components

### 1. Rescore one response (`ema_poc/playground/rescore.py`)
`rescore_one(conn, sandbox_response_id, *, scoring_client, scorer, config) -> bool`:
- Read the response's `answer_text` and its query's `brand_focus`
  (`SELECT sr.answer_text, q.brand_focus FROM sandbox_responses sr JOIN sandbox_queries
  q ON sr.query_id = q.query_id WHERE sr.sandbox_response_id = ?`).
- If no row → raise `KeyError(sandbox_response_id)` (the API maps this to 404).
- Call `scorer(scoring_client, response_text=..., brand_focus=...,
  abbvie_brands=config.brands.abbvie_brands,
  competitor_brands=config.brands.competitor_brands,
  model=config.settings.scoring_model)`.
  - On success → `S.set_response_score(..., brand_mentions=result.brand_mentions)`
    (clears `scoring_error`); return `True`.
  - On `Exception as exc` → `S.set_response_scoring_error(..., error=str(exc)[:500])`;
    return `False`. (Same per-item contract as `rescore_sandbox`; never raises on a
    scoring failure — only on not-found.)

### 2. Repo read-back (`ema_poc/repositories/sandbox.py`)
`get_sandbox_response(conn, sandbox_response_id) -> SandboxResponse | None` — single-row
fetch built like `list_query_responses` (includes `scoring_error`, citations). Used by
the endpoint to return the post-rescore state.

### 3. API (`ema_poc/web/app.py`)
`POST /api/responses/{sandbox_response_id}/rescore`:
- Auth is app-wide (inherited). Rate-limit with the existing `_check_rate` + the same
  per-IP cap as `/api/ask` (`PLAYGROUND_MAX_QUERIES_PER_HOUR`) — it is a paid scoring
  call. On exceed → 429 before any work.
- `conn = connect(db_path)`, `init_schema`. In a `try/finally` that closes the conn:
  - `try: rescore.rescore_one(conn, sandbox_response_id, scoring_client=deps.scoring_client,
    scorer=deps.scorer, config=deps.config) except KeyError: raise HTTPException(404)`.
  - `r = S.get_sandbox_response(conn, sandbox_response_id)`.
- Return `{"sentiment_score": r.sentiment_score, "competitive_position":
  r.competitive_position, "scoring_rationale": r.scoring_rationale,
  "scoring_error": r.scoring_error}` (200 — a scoring failure is reported via the
  `scoring_error` field, not an HTTP error, so the UI can show it).

### 4. Dashboard UI (`ema_poc/dashboard/render.py`, `renderResponses` detail)
- In the per-row detail panel, when `r.source === 'realtime'`, render a **Rescore**
  button with `data-id` = the sandbox id (`r.response_id` with the leading `sb-`
  stripped).
- A delegated click handler (added once, like the existing row-toggle handler):
  1. Disable the button, set its text to "Rescoring…".
  2. `fetch('/api/responses/' + id + '/rescore', {method:'POST'})`.
  3. On a non-ok response → show a small inline error, restore the button.
  4. On ok → read `{sentiment_score, competitive_position, scoring_rationale,
     scoring_error}`; find the `DATA.records` entry with `response_id === 'sb-'+id`,
     update those four fields on it, then call `render()` to refresh the active
     section (row + charts reflect the new score / failure).
- Button shown only for realtime rows; monitoring rows get nothing.
- Self-contained; `esc()`/existing helpers intact; minimal `.rescore-btn` CSS in theme.

## Error handling
- Unknown id → 404.
- Over rate cap → 429 (before the scoring call).
- Scoring failure (e.g. credits) → 200 with `scoring_error` set; the UI shows
  "⚠ Scoring failed: <reason>" (consistent with the playground card / Responses detail
  already added). `set_response_score` having cleared/`set_response_scoring_error`
  having set the column means the DB and the returned state agree.
- `rescore_one` never raises on a scoring failure — only on not-found.

## Testing (offline, fakes)
- **repo** (`tests/repositories/test_sandbox_jobs.py`): `get_sandbox_response` returns
  the row with `scoring_error`/score fields; `None` for an unknown id.
- **rescore** (`tests/playground/test_rescore.py`): `rescore_one` scores + clears error
  (returns True); records error on scorer failure (returns False); raises `KeyError`
  for an unknown id.
- **api** (`tests/web/test_jobs_api.py`): seed a sandbox response; `POST
  /api/responses/{id}/rescore` with an inline fake scorer → 200 + returned
  sentiment/cleared error and the DB updated; a raising fake scorer → 200 with
  `scoring_error` set; unknown id → 404; over cap → 429; auth enforced when
  `APP_PASSWORD` set. (Inject `deps.scorer` = a fake returning a score / raising.)
- **render** (`tests/dashboard/test_dashboard_render.py`): the Responses detail
  includes a Rescore control gated on realtime (`r.source === 'realtime'`), references
  `/api/responses/` and `render()`; self-contained preserved.

## Out of scope (deferrable)
- Rescoring monitoring responses (use `ema score`).
- Bulk "rescore all failed" button (the `ema rescore-sandbox` CLI already does the
  batch).
- Optimistic concurrency / locking (single-instance app; last write wins).
