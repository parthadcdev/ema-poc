# Dashboard Text Search — Design

**Date:** 2026-06-15
**Status:** Approved
**Goal:** Add a global free-text search to the dashboard that filters records across
all text fields and is honored by every section.

## Decision

A **single global search box** in the existing filter bar, wired into the existing
client-side `applyFilters()` predicate — exactly like the dropdown/date filters. Every
section already aggregates over the filtered record set, so one search box manifests
"at each page's level" automatically:
- **Overview / Marketing** — charts (Share of Voice, positioning, heatmap, trend,
  counts) recompute over the matching records.
- **Medical Affairs** — the review queue narrows to matching records.
- **Responses** — the table shows only matching rows.

Not per-page search boxes (inconsistent with the global filter model, more clutter).

## Behavior

- **Matches** a case-insensitive concatenation of ALL text fields per record:
  `question_text`, `response_text`, `scoring_rationale`, `brand_focus`, `llm_name`,
  `persona`, `therapeutic_area`, `domain`, `competitive_position`, `status`, and
  `brand_mentions` (array joined). Substring match (`indexOf`), not regex — no
  injection risk and no special-char surprises.
- **Multi-term AND:** the query is split on whitespace; EVERY term must appear
  somewhere in the record's searchable text (e.g. `skyrizi efficacy` finds records
  mentioning both). Empty query → no filtering.
- **Live:** filters as you type (the existing filter listener already binds `input`).
- **Combines** with the dropdown/date/source filters via AND (all predicates apply).
- **Clears** via the native search input's ✕ and via the existing **Reset** button.
- **Result count:** a `Showing N of M` indicator in the filter bar, updated on every
  render, so it's obvious the search took effect.

## Components (all in `ema_poc/dashboard/render.py` — self-contained HTML/JS)

1. **Search input** — `<label>Search<input type='search' id='f-search'
   placeholder='Search all text…'></label>` added as the FIRST control in the
   `filter-bar` block (most-reached control first).
2. **Result count** — `<span id='f-count' class='filter-count'></span>` in the
   filter bar (after the Reset button).
3. **`_searchable(r)` JS helper** — returns the lowercased space-joined concatenation
   of the text fields listed above (`Array.join` renders null/undefined as empty;
   `brand_mentions` joined first). One small pure function.
4. **`applyFilters()`** — read `f-search`, `.trim().toLowerCase()`, split on `\s+`
   into `terms`; if `terms.length`, compute `hay = _searchable(r)` and return false
   unless every term is found via `hay.indexOf(term) >= 0`. Added alongside the
   existing predicates.
5. **Filter listener** — add `#f-search` to the existing
   `querySelectorAll('#f-ta,#f-brand,...')` (it already binds `change` + `input` →
   live re-render).
6. **Reset handler** — add `document.getElementById('f-search').value = '';`.
7. **`render()`** — after `var rows = applyFilters();`, set
   `f-count.textContent = 'Showing ' + rows.length + ' of ' + DATA.records.length;`
   (use `textContent`, not innerHTML — the count is derived integers, and the search
   value never reaches the DOM as HTML).
8. **CSS** — minimal: style the `type=search` input to match the existing filter
   inputs, and a muted `.filter-count`. No external resources.

## Error handling / edge cases
- Null/undefined text fields → empty in the join (safe).
- Query with only whitespace → `terms` empty → no filtering.
- Search + zero matches → existing "No … match the current filters" empty states show
  (the section renderers already handle `rows.length === 0`); count shows `0 of M`.
- No XSS surface: the search string is used only for matching; the count uses
  `textContent`.

## Testing (offline; structural string assertions — no JS runtime in CI, matching the
existing render-test pattern)
- `tests/dashboard/test_dashboard_render.py` (append, using the existing `html`
  fixture):
  - `id='f-search'` present in the filter bar.
  - `function _searchable` defined; `applyFilters` references the split search `terms`
    and `_searchable(`/`indexOf`.
  - `id='f-count'` present and `render()` sets the `Showing ... of ...` text.
  - `f-search` cleared in the reset handler (the reset block sets its value to '').
  - Dashboard stays self-contained (the existing `test_self_contained_no_external_urls`
    continues to pass).

## Out of scope (deferrable)
- Match highlighting in the Responses table.
- Fuzzy / typo-tolerant search, ranking, regex mode.
- Per-field or quoted-phrase search syntax (whitespace-AND substring is enough).
- Server-side search (the dataset is already fully client-side).
