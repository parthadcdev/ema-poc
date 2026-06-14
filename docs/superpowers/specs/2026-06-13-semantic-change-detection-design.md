# Semantic Change Detection & Drift Alerts — Design

**Date:** 2026-06-13
**Status:** Approved
**Addresses:** Stakeholder feedback #2 (MUST) — define "material change" with a semantic
similarity threshold, a distinct drift alert type, and a frozen v0 baseline.

## Goal

Upgrade longitudinal change detection from text-diff (FR-306) to a **semantic**
signal: detect when a monitored LLM's answer to a question has *materially*
changed relative to a frozen v0 baseline, and raise a distinct **drift alert**
when it does — even if the change does not cross the sentiment threshold.

## Decisions (from brainstorming)

1. **Similarity engine:** embeddings API + cosine. Embed each compared response
   via the OpenAI embeddings API (`text-embedding-3-small`); flag text drift when
   cosine similarity to the baseline `< cosine_threshold` (default 0.85).
2. **Reference point:** a **frozen v0 baseline** per (question, LLM) pair is the
   primary anchor; the prior-run delta is also recorded but the baseline drives
   the alert.
3. **Drift trigger:** raise a drift alert when **cosine < threshold OR the
   competitive_position changed from the baseline** (e.g. FIRST_LINE_RECOMMENDED
   → NOT_MENTIONED). The alert reason records which condition fired.

## Architecture

New package `ema_poc/drift/`, three focused modules, following the existing DI
pattern (injectable client, fakes in tests, lazy vendor SDK import):

- **`embeddings.py`** — `EmbeddingClient` protocol + a default OpenAI-backed
  implementation (lazy `import openai`); pure-Python `cosine_similarity(a, b)`
  (no numpy); `embed_response(conn, response, *, client, model)` that computes
  and stores a vector (idempotent — skips if already embedded).
- **`baseline.py`** — `freeze_baseline(conn, *, now)` snapshots the latest
  *scored* response per (question, LLM) pair as the immutable v0 reference
  (skips pairs already frozen unless `force=True`); `get_baseline(conn, qid, llm)`.
- **`detector.py`** — `detect_drift(conn, *, client, config, now)`: for each pair
  with a baseline, ensure embeddings exist for the baseline response and the
  latest scored response, compute cosine + position-change vs baseline, and raise
  a drift alert when cosine < threshold OR position changed. Returns a summary.

## Data model (two new append-only tables; alerts reused)

```sql
CREATE TABLE IF NOT EXISTS response_embeddings (
    response_id  TEXT PRIMARY KEY,
    model        TEXT NOT NULL,
    vector       TEXT NOT NULL,          -- JSON float array
    created_at   TEXT NOT NULL,
    FOREIGN KEY (response_id) REFERENCES responses(response_id)
);

CREATE TABLE IF NOT EXISTS drift_baselines (
    question_id  TEXT NOT NULL,
    llm_name     TEXT NOT NULL,
    response_id  TEXT NOT NULL,          -- immutable pointer to the v0 response
    frozen_at    TEXT NOT NULL,
    PRIMARY KEY (question_id, llm_name),
    FOREIGN KEY (response_id) REFERENCES responses(response_id)
);
```

The baseline is an immutable pointer to a `response_id`; that response's
embedding (in `response_embeddings`) and `competitive_position` (immutable on the
response row) are read by join, so no denormalized copies are needed. Both tables
are brand-new, so `CREATE TABLE IF NOT EXISTS` adds them to existing DBs with no
migration needed (only new *columns* require the additive migration in
`init_schema`).

**Drift alerts reuse the existing `alerts` table** (FK `score_id`), tied to the
current response's latest score, with `reason` prefixed `DRIFT:` —
e.g. `DRIFT: cosine 0.81 < 0.85` or
`DRIFT: position FIRST_LINE_RECOMMENDED -> NOT_MENTIONED`. They surface in the
dashboard's Alerts section automatically, distinguishable by the prefix.

## Flow & CLI

- **`ema baseline-freeze [--force]`** — one-time at POC launch: freezes the v0
  baseline for every (question, LLM) pair that has a scored response.
- **`ema drift`** — runs `detect_drift`: lazily embeds the baseline + latest
  scored response per pair (≤2 embeddings/pair → bounded cost), compares, raises
  drift alerts, and prints a summary. Intended to run after `ema score`.

Drift runs **after scoring** (needs `competitive_position` and a `score_id` to
attach the alert). Credentials: drift needs the embedding key (OPENAI_API_KEY),
so `drift` is added to the credential-validation set; `baseline-freeze` is
read/local-only and is not.

## Config

```yaml
drift:
  embedding_model: text-embedding-3-small
  embedding_api_key_env: OPENAI_API_KEY
  cosine_threshold: 0.85
```

Parsed into a `DriftConfig` on `AppConfig`. Defaults applied if the section is
absent (backward compatible).

## Testing

A fake `EmbeddingClient` returning deterministic vectors keeps the suite offline:
- `cosine_similarity` math (identical → 1.0, orthogonal → 0.0).
- `embed_response` stores + is idempotent; FK enforced.
- `freeze_baseline` snapshots latest scored response per pair; skips frozen.
- `detect_drift`: raises on low cosine; raises on position change with high
  cosine; does **not** raise when similar + same position; ties the alert to the
  current score with a `DRIFT:` reason.

## Out of scope (deferrable)

- A dedicated dashboard "Drift" view beyond the existing Alerts section.
- Embedding every historical response (we embed only what is compared).
- Re-freezing/versioned baselines beyond the `--force` reset.
