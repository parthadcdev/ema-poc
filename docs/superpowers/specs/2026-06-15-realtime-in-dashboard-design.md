# Fold Realtime Playground Runs into the Dashboard Analytics — Design

**Date:** 2026-06-15
**Status:** Approved
**Goal:** Make realtime playground (sandbox) runs appear in the dashboard analytics
alongside the curated monitoring data, with a Source filter to tell them apart.

## Problem

`collect_dataset` (dashboard/dataset.py) reads ONLY the monitoring tables
(`responses`/`scores`/`questions`/`alerts`/`hallucination_checks`). Realtime
playground questions write to the isolated `sandbox_*` tables, so they never reach
the dashboard — they only show in the playground's "Recent questions" panel. The
product owner expects the questions they ask to be reflected in the dashboard.

## Decisions (confirmed)

- **Fold realtime into the main analytics** — sandbox runs become dashboard records.
- **Persist `brand_mentions` for realtime** so Share of Voice works for new runs
  (the scorer already computes them; today they're discarded). Existing test runs
  won't have them — acceptable, no backfill.
- **Add a Source filter** — every record tagged `source: "monitoring" | "realtime"`;
  a dashboard filter (All / Monitoring / Realtime, default All) so the ad-hoc realtime
  data is distinguishable from the curated monitoring data and can be isolated.

## How sandbox fields fold into the existing charts

The dashboard JS aggregates client-side over the records. Sandbox runs already carry
the fields these charts need, EXCEPT where noted:

| Chart / view | Keys off | Realtime support |
|---|---|---|
| Positioning mix | `brand_focus`, `competitive_position` | ✅ present |
| Therapy×Model heatmap | `brand_focus`, `llm_name`, `sentiment_score` | ✅ present |
| Sentiment trend | `llm_name`, `date`, `sentiment_score` | ✅ present |
| "Scored" counts / overview | `sentiment_score != null` | ✅ present |
| Filters (brand/llm/persona/date) | those fields | ✅ present |
| Share of Voice | `therapeutic_area` + `brand_mentions` | ⚠ needs brand_mentions (this design) |
| Therapeutic-area dimension | `therapeutic_area` | realtime has none → `(none)` bucket |

Realtime questions are free-form and have no therapeutic area; they land in the
`(none)` TA bucket in SoV/TA views. That is honest and acceptable.

## Components

### 1. Persist brand_mentions on sandbox responses
- **Schema** (`db.py`): add `("sandbox_responses", "brand_mentions", "TEXT")` to
  `_ADDITIVE_COLUMNS` (nullable; JSON-encoded list of brand strings, like the
  monitoring `scores.brand_mentions` column).
- **Repo** (`repositories/sandbox.py`): `set_response_score` gains a
  `brand_mentions: list[str] | None = None` param; stores `json.dumps(brand_mentions)`
  (or NULL) into the new column. Other behavior unchanged.
- **Service** (`playground/service.py`): pass `brand_mentions=result.brand_mentions`
  (the scorer result already has it) into `set_response_score`.

### 2. Union sandbox records into the dataset (`dashboard/dataset.py`)
- Tag every existing monitoring record with `"source": "monitoring"`.
- After the monitoring records are assembled, query the sandbox tables and append
  one record per sandbox response, in the SAME record shape, with `"source": "realtime"`:
  ```sql
  SELECT sr.sandbox_response_id, sr.query_id, sr.llm_name, sr.grounded,
         sr.answer_text, sr.status, sr.sentiment_score, sr.competitive_position,
         sr.scoring_rationale, sr.brand_mentions, sr.created_at,
         q.timestamp_utc, q.question_text, q.persona, q.brand_focus
  FROM sandbox_responses sr
  JOIN sandbox_queries q ON sr.query_id = q.query_id
  ORDER BY q.timestamp_utc ASC, sr.sandbox_response_id ASC
  ```
  Mapping per sandbox response:
  - `response_id` = `"sb-" + sandbox_response_id` (namespaced; avoids any collision
    with monitoring response_ids and marks provenance)
  - `timestamp_utc` = `q.timestamp_utc`; `date` = `timestamp_utc[:10]`
  - `llm_name` = `sr.llm_name`; `grounded` = `bool(sr.grounded)` (explicit column,
    not the name-suffix heuristic monitoring uses)
  - `persona` = `q.persona`; `question_id` = `q.query_id`;
    `question_text` = `q.question_text`
  - `therapeutic_area` = `None`; `domain` = `None` (free-form realtime)
  - `brand_focus` = `q.brand_focus`
  - `status` = `sr.status`; `response_text` = `sr.answer_text`
  - `sentiment_score` = float or None; `competitive_position` = value or None
  - `confidence_level` = None; `citation_quality` = None
  - `brand_mentions` = parsed JSON list from `sr.brand_mentions` (or `[]`),
    same parse/guard as the monitoring path
  - `scoring_rationale` = value or None
  - `hallucination_risk` = None; `hallucination_flags` = []
  - `alert_reasons` = []; `alert_triggered` = False
  - `source` = `"realtime"`
- Sandbox tables always exist after `init_schema` (the route calls it first), so no
  existence guard is needed; an empty sandbox simply appends nothing.

### 3. Source filter in the dashboard (`dashboard/render.py`)
- Add a `Source` `<select id="f-source">` to the filter bar with options
  `All` (value ""), `Monitoring`, `Realtime`.
- In the record filter predicate add: `if (source && r.source !== source) return false;`
  (read from `f-source`, included in the reset handler).
- Show provenance in the **Responses** detail list: a small `source` badge
  (`Monitoring` / `Realtime`) on each row, styled in the existing theme.
- All other charts pick up realtime automatically because they aggregate over the
  filtered record set.

## Error handling / edge cases
- Sandbox response with no score (FAILED / unscored) → `sentiment_score=None`,
  `brand_mentions=[]`; appears in counts but not sentiment charts, exactly like an
  unscored monitoring response.
- Malformed `brand_mentions` JSON → treated as `[]` (same guard as the monitoring path).
- `therapeutic_area=None` renders as the existing `(none)` bucket in SoV/TA.

## Testing (offline, fakes — no SDK/network)
- **schema** (`tests/test_schema_jobs.py` or a new test): `sandbox_responses` has a
  `brand_mentions` column after `init_schema`, incl. on a pre-existing DB.
- **repo** (`tests/repositories/test_sandbox_jobs.py`): `set_response_score(...,
  brand_mentions=["Skyrizi"])` stores JSON; reading the row back yields the list.
- **service** (`tests/playground/test_*`): a playground run whose scorer returns
  `brand_mentions=["Skyrizi"]` persists them on the sandbox response.
- **dataset** (`tests/dashboard/test_dataset.py` or new): a DB with one monitoring
  scored response and one sandbox scored response → `collect_dataset` returns both;
  monitoring record `source=="monitoring"`, sandbox record `source=="realtime"`,
  `response_id` starts `"sb-"`, `therapeutic_area is None`, `brand_mentions` parsed,
  `grounded` from the column. Existing dataset tests still pass (the added `source`
  key doesn't break field-level assertions).
- **render** (`tests/dashboard/test_dashboard_render.py`): output contains
  `id="f-source"` with Monitoring/Realtime options, the filter predicate references
  `r.source`, a source badge appears in the Responses section, and the dashboard
  stays self-contained.

## Out of scope (deferrable)
- Backfilling `brand_mentions` for the 2 existing realtime test runs.
- Deriving a therapeutic area for realtime questions (kept as `(none)`).
- Hallucination/drift/consensus over sandbox runs (those pipelines remain
  monitoring-only).
- Per-source styling beyond the Responses badge (e.g. coloring chart segments).
