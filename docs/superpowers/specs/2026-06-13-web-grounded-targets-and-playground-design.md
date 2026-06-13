# Web-Grounded Targets & Real-Time Playground — Design

**Date:** 2026-06-13
**Status:** Approved
**Builds on:** `2026-06-13-evidence-monitoring-agent-poc-design.md` (the EMA POC)

## Goal

Add two capabilities to the Evidence Monitoring Agent:

1. **Web-grounded LLM targets with citations** — variants of each provider that
   answer using live web search and return source citations, available in both
   the scheduled daily run and the new playground.
2. **Real-time playground web UI** — a local web app where a user types an
   arbitrary question and watches each model's answer (with citations and a live
   sentiment/positioning score) stream in as it completes.

## Decomposition

Built as two sequential plans. The UI depends on the grounded plumbing, so:

- **Plan 1 — Grounded targets & citations** (foundation)
- **Plan 2 — Real-time playground web UI** (consumes Plan 1)

Both follow existing project conventions: lazy vendor-SDK imports (no SDK at
module top level), dependency injection for tests, append-only storage, and
self-contained frontends.

---

## Plan 1 — Grounded Targets & Citations

### Config schema

`LLMTargetConfig` gains a field:

```python
grounded: bool = False
```

Three new targets are added to `config/llm_targets.yaml`, each `grounded: true`
and `enabled: true` (they run in the daily job by default):

- `GPT-4o-Grounded` (adapter `openai`)
- `Gemini-2.5-Pro-Grounded` (adapter `gemini`)
- `Claude-Opus-4.8-Grounded` (adapter `claude`)

A comment in the config notes that grounded targets roughly double per-run cost
and can be disabled via `enabled: false` if desired.

### Adapters

Each adapter, when its target's `grounded` flag is true, enables that provider's
native web-search tool:

| Adapter | Grounding mechanism | Citation source |
|---|---|---|
| `openai` | Responses API `web_search` tool | `url_citation` annotations |
| `gemini` | `google_search` grounding tool | `grounding_metadata.grounding_chunks` |
| `claude` | server-side `web_search` tool | `web_search_tool_result` blocks / `cited_text` |

Adapters keep their lazy-import structure. Grounding only changes the request
(tool declaration) and the response parsing (citation extraction); the
ungrounded path is unchanged.

### Normalized citation type

A shared model carried end to end:

```python
class Citation(BaseModel):
    title: str
    url: str
    snippet: str | None = None
```

`LLMResponse` (the adapter return type) gains `citations: list[Citation] = []`.
Each adapter maps its provider's native citation format into this shape.

### Storage (FR-304 — append-only)

New insert-only table:

```
response_citations(
    citation_id   TEXT PRIMARY KEY,
    response_id   TEXT NOT NULL REFERENCES responses(response_id),
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    snippet       TEXT,
    created_at    TEXT NOT NULL
)
```

`responses` rows stay immutable; citations are appended as child rows. The
responses repository's save path writes any citations from the `LLMResponse`.
A repository helper lists citations for a response (for the dashboard / future
use).

### Dashboard

No structural change required: grounded targets are distinct `llm_name`s, so the
existing "sentiment by LLM" and "positioning by LLM" aggregations include them
automatically, giving grounded-vs-ungrounded comparison. (Optional, low-priority:
a 🌐 marker next to grounded target names — included only if trivial.)

---

## Plan 2 — Real-Time Playground Web UI

### Stack

New package `ema_poc/web/`:

- `app.py` — FastAPI application factory with injectable dependencies
- `static/index.html` — single self-contained page (inline CSS/JS)

New dependencies: `fastapi`, `uvicorn` (and `httpx` for the test client).
Launched by a new CLI command: `ema serve --host 127.0.0.1 --port 8000`.

The app binds to `127.0.0.1` only — a local tool, no auth for the POC.

### Sandbox storage (isolated from monitoring)

Three new tables, fully separate from the approval-gated monitoring tables:

```
sandbox_queries(
    query_id      TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    question_text TEXT NOT NULL,
    persona       TEXT,
    brand_focus   TEXT
)

sandbox_responses(
    sandbox_response_id  TEXT PRIMARY KEY,
    query_id             TEXT NOT NULL REFERENCES sandbox_queries(query_id),
    llm_name             TEXT NOT NULL,
    llm_model_version    TEXT NOT NULL,
    grounded             INTEGER NOT NULL,
    answer_text          TEXT,
    response_tokens      INTEGER,
    finish_reason        TEXT,
    status               TEXT NOT NULL,
    sentiment_score      REAL,
    competitive_position TEXT,
    scoring_rationale    TEXT,
    created_at           TEXT NOT NULL
)

sandbox_citations(
    citation_id          TEXT PRIMARY KEY,
    sandbox_response_id  TEXT NOT NULL REFERENCES sandbox_responses(sandbox_response_id),
    title                TEXT NOT NULL,
    url                  TEXT NOT NULL,
    snippet              TEXT,
    created_at           TEXT NOT NULL
)
```

These bypass SE-002 (no approval gate) by design — they are a sandbox, not the
official monitoring record, and never feed the monitoring dashboard.

### Endpoints

- `GET /` → serves `index.html`
- `GET /api/targets` → JSON list of available targets (name, adapter, grounded)
  for rendering the checkboxes
- `GET /api/ask/stream` → **Server-Sent Events**. Query params: `question`
  (required), `persona` (optional), `brand_focus` (optional), `targets`
  (optional comma list; default = all enabled).

### Request flow (`/api/ask/stream`)

1. Validate credentials (reuse `validate_credentials`); if missing, emit an
   `error` event and stop.
2. Create a `sandbox_queries` row.
3. Fan out across the selected targets concurrently (reuse the existing
   `ThreadPoolExecutor`-based executor). For each target, as it completes:
   - emit `answer` event: `{llm_name, grounded, status, answer_text, citations,
     finish_reason, tokens}`
   - run the live Claude scorer on the answer; emit `score` event:
     `{llm_name, sentiment_score, competitive_position, scoring_rationale}`
   - persist a `sandbox_responses` row (+ `sandbox_citations`)
4. Emit `done` when all targets are finished.

Sync vendor SDK calls run in worker threads; results are bridged to the async
SSE generator via a queue, yielding events in completion order (not submission
order) so the fastest model shows first.

### UI behavior

`index.html` renders:

- a question textarea (required)
- persona selector (Prospect / Provider / Patient / none)
- brand_focus text input (optional)
- target checkboxes (grounded variants badged 🌐), all checked by default
- a "Run" button that opens the SSE stream

Result cards stream in live, one per target as its `answer` event arrives, each
card showing: answer text, a citations list (for grounded targets), and a
sentiment/positioning chip that fills in when the `score` event arrives. A
collapsible "Recent queries" panel lists prior sandbox queries (read-only).

---

## Cross-Cutting

### Testing

Mirrors the existing approach — the full suite runs with **no real SDKs and no
network**:

- **Adapters:** fake vendor SDK objects assert (a) the web-search tool is
  declared when `grounded` is true, (b) citations are parsed from each provider's
  native format, (c) the ungrounded path is unchanged.
- **Citation storage:** insert + list round-trip; FK enforced.
- **Sandbox repo:** CRUD for queries/responses/citations; FK enforced.
- **Web app:** FastAPI `TestClient` with **injected fake adapters + fake scorer**
  asserts the SSE event sequence (`answer` → `score` per target, then `done`),
  error event on missing credentials, and that sandbox rows are written.

### Security & constraints

- Web UI binds to `127.0.0.1` only; no auth (local POC tool).
- Credentials continue to come from environment / `.env`; never logged
  (existing redaction applies).
- Sandbox data is isolated from the immutable, approval-gated monitoring tables
  (SE-002 / FR-304 preserved).
- No PII/PHI is introduced by the system; user-entered questions are the user's
  responsibility (a short note in the UI reminds testers not to enter PII/PHI,
  per SE-001).

### Dependencies added

`fastapi`, `uvicorn`, `httpx` (test client). Added to `pyproject.toml`.

## Out of Scope

- Token-by-token answer streaming (cards stream per-model on completion instead).
- Authentication / multi-user accounts for the playground.
- Persisting playground results into the official monitoring dataset.
- Editing or re-scoring sandbox results.
