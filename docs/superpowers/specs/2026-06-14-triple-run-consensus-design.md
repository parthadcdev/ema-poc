# Triple-Run Consensus Scoring — Design

**Date:** 2026-06-14
**Status:** Approved
**Addresses:** Stakeholder feedback #6 (promote FR-212 COULD → SHOULD) — response
variance is scientifically meaningful; capture N samples per question/LLM and a
majority-vote consensus, with a variance alert on material disagreement.

## Decisions (from brainstorming)

1. **Sampling scope:** within a single run. Each run submits every
   (question × LLM) `samples_per_question` times (config, default 3; 1 disables).
   Isolates model non-determinism (day-to-day change stays the drift feature).
2. **Disagreement:** the majority `competitive_position` is canonical (with an
   agreement ratio + sentiment mean/spread). A **VARIANCE alert** fires when the
   samples materially disagree.

## Sampling (runner + schema)

- New `Settings.samples_per_question: int = 3`.
- `responses` gains `sample_index INTEGER NOT NULL DEFAULT 0` (additive migration
  so the live DB upgrades). Each sample is a normal append-only response row.
- The runner fans out `samples_per_question` tasks per (question, adapter); the
  resume key becomes `(question_id, llm_name, sample_index)` via an extended
  `completed_keys`. Thread-safety/append-only semantics unchanged — only more
  fan-out tasks. `build_response`/`save_response`/`Response` carry `sample_index`.

## Scoring — unchanged

Each sample is scored independently by the existing pass (N samples → N scores).

## Consensus pass (new) — `ema_poc/consensus/`

`compute_consensus(conn, *, now, id_factory) -> ConsensusSummary(groups, alerts_raised)`:
for each `(run_id, question_id, llm_name)` group with ≥1 scored sample not yet in
the `consensus` table:
- **canonical_position** = the `competitive_position` with the most votes among the
  group's latest scores; a top tie → `canonical_position = None` (no majority).
- **agreement** = top_count / sample_count.
- **sentiment_mean**, **sentiment_stdev** over the samples' sentiment scores.
- Persist a `consensus` row.
- **Variance alert** when disagreement is material:
  - no majority (tie for top / agreement ≤ 0.5), OR
  - the set of observed positions spans **favorable** {FIRST_LINE_RECOMMENDED,
    AMONG_OPTIONS} and **unfavorable/absent** {NOT_RECOMMENDED, NOT_MENTIONED}.
  Reason: `VARIANCE: <k1×POS1, k2×POS2, ...> across N samples`. Attached to a
  representative sample's latest `score_id` (alerts FK), so it surfaces in the
  dashboard Medical Affairs review queue automatically.

Idempotent: a group already in `consensus` is skipped.

## Storage

```sql
CREATE TABLE IF NOT EXISTS consensus (
    consensus_id       TEXT PRIMARY KEY,
    run_id             TEXT NOT NULL,
    question_id        TEXT NOT NULL,
    llm_name           TEXT NOT NULL,
    canonical_position TEXT,                 -- null = no majority
    agreement          REAL NOT NULL,
    sentiment_mean     REAL,
    sentiment_stdev    REAL,
    sample_count       INTEGER NOT NULL,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_consensus_group
    ON consensus(run_id, question_id, llm_name);
```

Plus `responses.sample_index` (additive). The `consensus` table is the canonical
consensus record; per-response `competitive_position` used elsewhere is unchanged
(out of scope to override it).

## CLI & config

- Flow: `ema run` (N samples) → `ema score` → `ema consensus`.
- **`ema consensus`** — pure computation (no new credentials); writes consensus +
  variance alerts.
- `samples_per_question: 3` in `settings.yaml`.

## Testing (offline)

- Runner: with `samples_per_question=2`, one (question, LLM) yields 2 response rows
  with `sample_index` 0 and 1; resume skips completed (qid, llm, idx) and fills a
  missing sample.
- Consensus: majority/agreement math; sentiment mean/stdev; variance alert fires
  on favorable↔absent disagreement and on no-majority; does NOT fire on unanimity;
  idempotent (second run computes 0 groups).

## Out of scope (deferrable)

- A dedicated dashboard consensus panel (variance alerts already surface).
- Overriding per-response `competitive_position` with the consensus value.
- Adaptive sample counts / early-stopping when samples agree.
