# Audience-Split Analytics Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** A self-contained, navigable dashboard app: side-nav + global filters driving a Marketing Analytics view (4 charts), a Medical Affairs review view, Overview, and Responses — surfacing confidence/citation/hallucination/drift signals.

**Approach:** Python emits the row-level dataset as inline JSON; inline JS filters + re-aggregates + renders. Self-contained (inline CSS/JS, inline SVG for the trend).

**Branch:** `feature/audience-dashboard`. **Spec:** `docs/superpowers/specs/2026-06-13-audience-dashboard-design.md`.

**Dataset contract** (see spec) is the Python↔JS interface — every task must honor the exact record field names.

---

### Task 1: Data layer — `collect_dataset`

**Files:** `ema_poc/dashboard/dataset.py` (create), `tests/dashboard/test_dataset.py` (create).

- `collect_dataset(conn, *, abbvie_brands, competitor_brands) -> dict` returning `{generated_at, abbvie_brands, competitor_brands, records}` per the spec's contract.
- One record per `responses` row. Join the latest score (sentiment_score, competitive_position, confidence_level, citation_quality, brand_mentions[JSON→list], scoring_rationale), the latest `hallucination_checks.risk_level` + `hallucination_flags` list, and `alert_reasons` (all `alerts.reason` for the response's scores, via alerts→scores→responses; includes `DRIFT:`/`HALLUCINATION:`/sentiment reasons). `grounded` = `llm_name.endswith("-Grounded")`. `date` = `timestamp_utc[:10]`. `alert_triggered` = `len(alert_reasons) > 0` (don't rely solely on the responses cache).
- `generated_at`: accept an injected `now` param (default a fixed-safe `""` or pass through) — do NOT call datetime.now in a way that breaks determinism in tests; accept `now: str = ""` param and let the builder pass the timestamp. Actually: add `now: str = ""` to the signature and include it as `generated_at`.
- Tests (seed a run + responses + scores + a hallucination_check/flags + a DRIFT alert + a sentiment alert): assert records carry sentiment/position/confidence/citation/brand_mentions(list)/hallucination_risk/hallucination_flags(list of dicts)/alert_reasons(list incl the DRIFT and HALLUCINATION reasons); brand lists echoed; `grounded` true for a "-Grounded" llm_name. Assert the result is JSON-serializable (`json.dumps(collect_dataset(...))` succeeds).

### Task 2: Page shell + JS core + Overview + Responses

**Files:** rewrite `ema_poc/dashboard/render.py`; update `tests/dashboard/test_render.py` (or the existing render test).

- `render_dashboard_html(dataset: dict) -> str` produces a self-contained page:
  - `<head>`: inline `<style>` (side-nav layout, filter bar, cards, tables, chips, bars — reuse/evolve the current CSS aesthetic).
  - Left **side-nav** with items Overview / Marketing Analytics / Medical Affairs / Responses (data-section attributes).
  - **Filter bar**: selects for therapeutic area, brand (brand_focus), LLM, persona, + two date inputs (from/to). Options derived in JS from the dataset.
  - Section containers: `<section id="view-overview">`, `view-marketing`, `view-medical`, `view-responses` (only the active one shown).
  - Embedded data: `<script type="application/json" id="ema-data">` + `html.escape`-safe JSON (use `json.dumps`; escape `</` to `<\/` to avoid breaking the script tag).
  - Inline `<script>` JS app:
    - parse `#ema-data`; `STATE.filters`; `applyFilters(records)` → filtered list (match each active filter; date range inclusive on `date`).
    - nav click → show that section, hide others, set active; re-render the active section.
    - filter change → re-render the active section.
    - `escapeHtml()` helper (reuse the safe-escaping approach from the playground).
    - **Overview renderer**: stat tiles (total responses, scored count, total alerts, hallucination-HIGH count, drift-alert count) + a headline alert list (question + llm + reasons).
    - **Responses renderer**: filterable table — columns Time, Question(id+text), LLM, Persona, Brand, Status, Sentiment, Position, Confidence, Citation, Halluc-risk; click row → expandable detail (full question, response_text, rationale, flagged claims). All dynamic values escaped.
- Keep all dynamic text escaped (no XSS). No external resources.
- Tests: the page contains the 4 section container ids, the side-nav items, the filter controls (`id="f-ta"` etc.), the embedded `id="ema-data"` JSON, `EMA`/app markers, and is self-contained — assert no `<script src` and no `<link ` and (for now) no `http`/`https` except inside the embedded JSON data (adjust the existing self-contained assertion to scan only the non-data markup, OR defer the SVG-namespace allowance to Task 3 where SVG is introduced).
- Regenerate `dashboard.html` (via build, after Task 5 wiring) — for now assert via a unit test that `render_dashboard_html(<small dataset>)` returns valid HTML with the sections.

### Task 3: Marketing Analytics — the 4 charts (JS)

**Files:** extend `ema_poc/dashboard/render.py` (the JS app); update `tests/dashboard/test_render.py`.

Add a **Marketing renderer** that, from the filtered records, renders into `#view-marketing`:
- **Share of Voice**: for each therapeutic_area, count brand mentions in `brand_mentions` classified as AbbVie (in abbvie_brands) vs competitor (in competitor_brands); render a 100% stacked CSS bar (AbbVie vs competitor) per area, with counts.
- **Competitive Positioning Mix**: for each brand_focus, count records per competitive_position; render a 100% stacked CSS bar across the 5 positions (fixed color per position), legend.
- **Therapy × Model heatmap**: grid rows = brand_focus, cols = distinct llm_name; cell = avg sentiment (records with that brand+llm and non-null sentiment), colored on a diverging green→amber→oxblood scale; empty cells muted; numeric label in cell.
- **Sentiment trend**: for each brand_focus, average sentiment per `date` (sorted dates on x); render an **inline SVG** with one `<polyline>` per brand + axis labels; show an empty-state message when fewer than 2 distinct dates exist.

Introduce the inline SVG here. **Update the self-contained test** to permit the SVG namespace URI `http://www.w3.org/2000/svg` while still forbidding `<script src`, `<link `, and other `http(s)://` external references (i.e., allow only the w3.org SVG/xlink namespace literals).

Tests: render a dataset spanning ≥2 brands, ≥2 LLMs, ≥2 dates; assert the marketing section markup includes the SoV/positioning/heatmap/trend container markers and an `<svg` element; assert still self-contained under the updated rule.

### Task 4: Medical Affairs review view (JS)

**Files:** extend `ema_poc/dashboard/render.py`; update `tests/dashboard/test_render.py`.

Add a **Medical Affairs renderer** into `#view-medical`:
- **Review queue**: filtered records where `alert_triggered` OR `hallucination_risk in (MEDIUM, HIGH)`. Sort HIGH-risk / most-flagged first. Each item: question (id + text), LLM, brand, badges for each alert reason type (Sentiment / DRIFT / Hallucination-<risk>), and an expandable panel with: full response_text, the flagged claims (each `claim` → `conflicts_with` + severity badge), scoring rationale, confidence_level, citation_quality.
- A small summary header: counts of hallucination risk levels + drift alerts + sentiment alerts in the filtered set.
- All escaped; read-only (note: "approve via the ema CLI" hint text).

Tests: seed a dataset with a HIGH-hallucination record (with flags) and a DRIFT alert record; assert the medical section renders the flagged-claim text, the risk badge, and the review-queue container; assert the queue excludes clean records.

### Task 5: Build/CLI wiring + final self-contained test + regenerate

**Files:** `ema_poc/dashboard/build.py`, `ema_poc/cli.py`, tests, regenerate `dashboard.html`.

- `build_dashboard(conn, out_path, *, abbvie_brands, competitor_brands, now="")` calls `collect_dataset(...)` then `render_dashboard_html(...)`. (Remove/retire the old `build_dashboard_data`/`DashboardData` path and the old `render_dashboard_html(DashboardData)` signature — or keep `data.py` only if still referenced; prefer deleting dead code.)
- CLI `dashboard` branch: pass `abbvie_brands=config.brands.abbvie_brands, competitor_brands=config.brands.competitor_brands` and a UTC `now`.
- Update `Deps.build_dashboard` default + the CLI test to the new signature.
- Delete now-dead `dashboard/data.py` (DashboardData/build_dashboard_data) and its tests if fully superseded; update any imports.
- Run the FULL suite; fix any dashboard tests referencing the old structure.
- Regenerate against the live DB:
  `source .venv/bin/activate && set -a; . ./.env; set +a && ema dashboard --out dashboard.html` and confirm it opens and is self-contained (grep: no `<script src`, no `<link `, no external `http(s)://` outside the embedded JSON + the SVG namespace).

---

## Self-Review Notes (author)
- The dataset contract is the single source of truth; Tasks 2–4 consume the exact field names from Task 1.
- Self-contained rule evolves in Task 3 (allow SVG namespace) — both render tests and any build-level assertion must use the same relaxed rule afterward.
- Read-only: no write-back; MA approval stays via the ema CLI/question repo.
- XSS: every dynamic value escaped in JS (reuse the playground's esc()).
- Charts are CSS bars + HTML grid + one inline SVG — no JS chart library, no external resources.
