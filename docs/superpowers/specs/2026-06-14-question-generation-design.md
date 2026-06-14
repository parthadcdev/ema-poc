# Question-Generation Assist — Design

**Date:** 2026-06-14
**Status:** Approved
**Addresses:** Stakeholder feedback #5 (COULD→SHOULD) — Claude proposes new
monitoring questions to fill coverage gaps, queued for Medical Affairs approval —
turning the static bank into a feedback loop.

## Decisions (from brainstorming)

1. **Gap signal:** coverage matrix (under-covered brand×persona×domain cells) +
   effectiveness (chronically NOT_MENTIONED questions). Degrades to coverage-only
   when there's no scored data.
2. **Sink:** proposals are written into the `questions` table as PENDING +
   inactive (SE-002 keeps them out of runs until approved), tagged
   `source='generated'`. Reuses the existing approve/reject flow.

## Components — `ema_poc/suggest/`

### `gaps.py`
`analyze_gaps(conn, *, abbvie_brands) -> GapReport` where
`GapReport(under_covered: list[Cell], low_value: list[dict])`:
- **Coverage matrix:** over active+approved questions, count per
  `(brand_focus, persona, domain)`. `Cell(brand, persona, domain, count)` for cells
  with `count == 0` (the structural gaps), across personas {Prospect, Provider,
  Patient}, domains {Efficacy, Safety, Comparative, Access, General}, and the
  AbbVie brands.
- **Effectiveness:** reuse `ema_poc.coverage.question_effectiveness`; include the
  `low_value` questions (id, brand_focus, question_text, not_mentioned_rate).
  Empty list when no scored data.

### `generator.py`
`ProposedQuestion` (Pydantic): `question_text, persona (Literal personas),
domain (Literal domains), therapeutic_area, brand_focus, rationale`.
`GenerationResult`: `proposals: list[ProposedQuestion]`.
`suggest_questions(client, *, gap_report, abbvie_brands, competitor_brands,
existing_texts, count, model="claude-opus-4-8") -> GenerationResult` via
`client.messages.parse` (adaptive thinking, no temperature). The prompt provides
the gap report, the brand lists, and the existing question texts (to avoid
duplicates), and asks for `count` new, distinct, PII/PHI-free questions targeting
the gaps — each tagged to a persona/domain/brand with a one-line rationale.

### `pipeline.py`
`generate_and_store(conn, *, client, config, count, model=None, now_factory,
id_factory) -> SuggestSummary(proposed, stored, skipped)`:
1. `gap_report = analyze_gaps(conn, abbvie_brands=config.brands.abbvie_brands)`.
2. `existing = {normalized question_text of every current question}`.
3. `result = suggest_questions(client, gap_report=..., existing_texts=...,
   count=count, ...)`.
4. For each proposal, skip (count `skipped`) if its normalized text matches an
   existing question; else `add_question(..., source='generated')` with a
   `GEN-<short id>` question_id (PENDING + inactive by default). Count `stored`.
5. Return the summary; the proposals are also returned/printed for review.

## Storage

- `questions` gains `source TEXT NOT NULL DEFAULT 'manual'` (additive migration).
  `Question` model gains `source: str = "manual"`. `_insert_version` INSERT +
  `_question_from_row` carry it. `add_question(..., source: str = "manual")`.
- No new tables. Generated questions are ordinary PENDING/inactive rows,
  distinguished only by `source='generated'`.

## CLI & config

- **`ema suggest-questions [--count N]`** (default N=10) — validates
  `ANTHROPIC_API_KEY` (uses Claude); runs `generate_and_store`; prints each stored
  proposal (question_id, persona/domain/brand, text, rationale) plus the summary.
- Model = `config.settings.scoring_model`.

## Testing (offline)

- `analyze_gaps`: under-covered cells computed from a seeded bank; low_value
  included from seeded scored data; degrades (empty low_value) with no scores.
- `generator`: fake Claude returns a `GenerationResult`; `_build_prompt` embeds the
  gap summary + existing texts; max_tokens set, no temperature.
- `pipeline`: stores proposals as PENDING + inactive + `source='generated'`; skips
  a proposal duplicating an existing question; summary counts correct.
- `questions` repo: `source` round-trips; migration adds the column; default
  'manual'.
- CLI: validates credentials; prints proposals + summary.

## Out of scope (deferrable)

- An `ema approve`/dashboard approval write-back (approval stays via the existing
  repo flow — a pre-existing gap for ALL PENDING questions, not specific to this).
- Auto-running generated questions (they're inactive until approved).
- Ranking/scoring proposals or de-duping against rejected history.
