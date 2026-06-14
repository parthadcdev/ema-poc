# Audience-Split Analytics Dashboard — Design

**Date:** 2026-06-13
**Status:** Approved
**Addresses:** Stakeholder feedback #4 (SHOULD) — tailor the dashboard to Medical
Affairs vs Commercial; surface the signals built since launch (confidence_level,
citation_quality, hallucination flags/risk, DRIFT alerts).

## Goal

Replace the single static dashboard with a self-contained, navigable analytics
app: a left side-nav, a global filter bar that drives every section, a
marketing-grade **Marketing Analytics** view for the Commercial team, a
**Medical Affairs** review view, plus Overview and Responses.

## Approach

Move from server-rendered aggregates to a **client-side app**: Python emits the
row-level dataset as one inline JSON blob; inline JS filters + re-aggregates +
renders on every filter change. Still fully self-contained (inline CSS/JS, inline
SVG for the trend line, no external resources).

## Layout

- **Left side-nav:** Overview · Marketing Analytics · Medical Affairs · Responses
- **Global filter bar:** therapeutic area · brand (brand_focus) · LLM · persona ·
  date range. Filters apply to every section.

## Dataset contract (the Python↔JS interface)

`collect_dataset(conn) -> dict`, embedded as `<script type="application/json"
id="ema-data">…</script>`:

```jsonc
{
  "generated_at": "<ISO>",
  "abbvie_brands": ["Skyrizi", ...],       // from config (for share-of-voice classification)
  "competitor_brands": ["Stelara", ...],
  "records": [{
    "response_id", "timestamp_utc", "date",          // date = YYYY-MM-DD
    "llm_name", "grounded",                            // grounded = name endswith "-Grounded"
    "persona", "question_id", "question_text",
    "therapeutic_area", "brand_focus", "domain",
    "status", "response_text",
    "sentiment_score", "competitive_position",         // null until scored
    "confidence_level", "citation_quality",            // null until scored
    "brand_mentions",                                  // list[str] from scores.brand_mentions (JSON)
    "alert_triggered", "alert_reasons",                // list[str]; DRIFT:/HALLUCINATION:/sentiment
    "hallucination_risk", "hallucination_flags",       // risk str|null; flags list[{claim,conflicts_with,severity}]
    "scoring_rationale"
  }]
}
```

All section aggregation happens in JS from `records` (so filters recompute live).
`config` brand lists are passed into `collect_dataset` (the builder reads them
from `AppConfig`).

## Sections

### Marketing Analytics (Commercial)
- **Share of Voice** — per therapeutic area, AbbVie vs competitor brand-mention
  share (count mentions in `brand_mentions` classified against the brand lists) —
  CSS stacked bars.
- **Competitive Positioning Mix** — per `brand_focus`, the % distribution across
  FIRST_LINE_RECOMMENDED / AMONG_OPTIONS / SECOND_LINE / NOT_RECOMMENDED /
  NOT_MENTIONED — 100% stacked bars.
- **Therapy × Model favorability heatmap** — rows = brand_focus, cols = llm_name,
  cell = avg sentiment, colored on a diverging scale — HTML grid of colored cells.
- **Sentiment trend over time** — avg sentiment per brand across `date`, one
  polyline per brand — inline SVG (empty state until ≥2 run dates exist).

### Medical Affairs
- **Review queue** — responses with any alert (sentiment / DRIFT / HALLUCINATION)
  or hallucination risk MEDIUM+; each row: question, LLM, brand, risk badges,
  expandable full response text + flagged claims (claim → conflicts_with,
  severity) + scoring rationale + confidence/citation.
- Read-only: approval stays out-of-band via the `ema`/question repo; this surfaces
  the queue to act on.

### Overview
- Stat tiles (responses, scored, alerts, hallucination-HIGH, drift) + headline
  alert list + a compact positioning-mix chart.

### Responses
- The filterable responses table, with added columns: confidence, citation
  quality, hallucination risk; expandable detail (question, response, rationale).

## Charts technique (self-contained)
- CSS bars (stacked / 100%-stacked) for share-of-voice and positioning mix.
- HTML grid of colored `<div>` cells for the heatmap.
- Inline SVG `<polyline>` for the sentiment trend (the only SVG; the self-contained
  test is relaxed to permit the `http://www.w3.org/2000/svg` namespace URI while
  still forbidding external `<script src>` / `<link>` / other resources).

## Components
- `ema_poc/dashboard/dataset.py` — `collect_dataset(conn, *, abbvie_brands, competitor_brands) -> dict`.
- `ema_poc/dashboard/render.py` — rewritten: page shell (side-nav, filter bar,
  section containers), CSS, embedded dataset JSON, and the inline JS app
  (filter engine + nav + per-section renderers).
- `ema_poc/dashboard/build.py` — `build_dashboard(conn, out_path, *, config)` now
  passes the brand lists through.
- CLI `dashboard` command passes `config` to the builder.

## Testing
- `dataset.py`: `collect_dataset` produces the record fields, classifies
  brand_mentions, includes hallucination risk/flags + alert_reasons (incl DRIFT/
  HALLUCINATION), and the brand lists. Offline, seeded DB.
- `render.py`: the page embeds the JSON blob, contains each section container +
  the nav + filter controls, and is self-contained (no external `<script src>`/
  `<link>`; SVG namespace allowed).
- Update existing dashboard tests for the new structure.

## Out of scope (deferrable)
- Write-back approval actions (dashboard stays read-only).
- Per-user auth / saved filter presets.
- Two physically separate files (one tabbed/side-nav file serves both audiences).
