# Triple-Run Consensus Scoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Submit N samples per question×LLM per run, then compute a majority-vote consensus position + agreement + sentiment spread, raising a VARIANCE alert on material disagreement.

**Branch:** `feature/triple-run-consensus`. **Spec:** `docs/superpowers/specs/2026-06-14-triple-run-consensus-design.md`.

---

### Task 1: `sample_index` on responses + config + Response model

**Files:** `ema_poc/db.py`, `ema_poc/config.py`, `ema_poc/models.py`, `ema_poc/repositories/responses.py` (build_response/save_response/completed_keys), tests.

- `db.py`: add `sample_index INTEGER NOT NULL DEFAULT 0` to the `responses` table; add `("responses", "sample_index", "INTEGER NOT NULL DEFAULT 0")` to `_ADDITIVE_COLUMNS` (existing DBs gain it — note: SQLite ADD COLUMN with NOT NULL requires a DEFAULT, which this has).
- `config.py`: add `samples_per_question: int = 3` to `Settings`.
- `models.py`: add `sample_index: int = 0` to the `Response` model.
- `responses.py`:
  - `build_response(...)` gains a keyword param `sample_index: int = 0`, set on the returned Response.
  - `save_response` includes `sample_index` in the INSERT column list + value.
  - `completed_keys(conn, run_id)` → return a set of `(question_id, llm_name, sample_index)` tuples (add the column to its SELECT). READ the current impl first; update its callers' expectations (the runner, Task 2).
- Tests: a Response/round-trip carrying sample_index persists + reads back; `completed_keys` returns the 3-tuple including sample_index; config default `samples_per_question == 3`; the additive migration adds the column to an old DB (extend the existing migration test).

### Task 2: Runner fans out N samples

**Files:** `ema_poc/agent/runner.py`, `tests/agent/test_runner.py`.

- In `run(...)`, read `samples = config.settings.samples_per_question`.
- The resume set `done = completed_keys(conn, run_id)` now holds `(qid, llm, sample_index)`.
- Replace the per-adapter submit loop: for each adapter, for `sample_index in range(samples)`, skip if `(question.question_id, adapter.name, sample_index) in done`, else submit. Track the `sample_index` alongside the adapter for each future (e.g. `futures[fut] = (adapter, sample_index)`).
- When building/saving the response, pass `sample_index=sample_index` to `build_response`.
- `questions_attempted` should still count a question if ANY (adapter, sample) was submitted for it (unchanged semantics — increment once per question that has ≥1 future).
- Keep all DB writes in the main thread; keep append-only/audit/citation/model-drift logic intact.
- Tests: with a config whose `samples_per_question=2` and one fake adapter, a single approved question yields 2 response rows for that (question, llm) with sample_index {0,1}. Resume: pre-insert sample_index 0 (mark done), run again → only sample_index 1 is submitted (assert the fake adapter called once / one new row). Existing runner tests must still pass — they likely use a config with default samples=3; UPDATE those fixtures to set `samples_per_question=1` so existing single-sample assertions hold (or adjust expected counts). Prefer setting samples=1 in the existing fixtures to preserve their intent, and add NEW tests for the multi-sample behavior.

### Task 3: Consensus storage + repository

**Files:** `ema_poc/db.py` (consensus table), `ema_poc/repositories/consensus.py`, tests.

- `db.py`: add the `consensus` table + index (see spec). New table → no additive migration.
- Repository: `save_consensus(conn, *, consensus_id, run_id, question_id, llm_name, canonical_position, agreement, sentiment_mean, sentiment_stdev, sample_count, now, commit=True)`; `existing_groups(conn) -> set[tuple[str,str,str]]` returning `(run_id, question_id, llm_name)` already computed; `list_consensus(conn) -> list[ConsensusRow]` (dataclass). 
- Tests: save + list round-trip; existing_groups reflects saved rows; canonical_position null allowed.

### Task 4: Consensus computation + variance alerts

**Files:** `ema_poc/consensus/__init__.py` (empty), `ema_poc/consensus/compute.py`, tests.

- READ `ema_poc/repositories/scores.py` (latest_score), `ema_poc/repositories/responses.py` (a way to list scored responses grouped — reuse `success_responses` or add a query), `ema_poc/repositories/alerts.py`, `ema_poc/models.py` (Alert).
- `FAVORABLE = {"FIRST_LINE_RECOMMENDED","AMONG_OPTIONS"}`, `UNFAVORABLE = {"NOT_RECOMMENDED","NOT_MENTIONED"}`.
- `ConsensusSummary(groups: int, alerts_raised: int)`.
- `compute_consensus(conn, *, now_factory=_now_iso, id_factory=uuid4().hex) -> ConsensusSummary`:
  - Gather scored responses (status SUCCESS with a latest score that has competitive_position). Group by `(run_id, question_id, llm_name)`.
  - Skip groups already in `existing_groups(conn)`.
  - For each group: collect the list of `competitive_position` (from each sample's latest score) and `sentiment_score`s.
    - vote counts; top_count = max count; canonical = the position with top_count IF unique else None (tie → None).
    - agreement = top_count / len(samples).
    - sentiment_mean = mean; sentiment_stdev = population stdev (0.0 if <2 or all equal).
    - save_consensus(...).
    - material_disagreement = (canonical is None) OR (positions ∩ FAVORABLE and positions ∩ UNFAVORABLE both non-empty).
    - if material_disagreement: build reason `VARIANCE: <comma-joined "k×POS" sorted by count desc> across N samples`; attach to a representative sample's latest score_id (the first sample in the group that has a score); save_alert; alerts_raised += 1.
  - record an audit event ("CONSENSUS") per group (optional, mirror other passes).
- Tests (seed run + N responses per group + scores via scores.save_score):
  1. 3 samples all FIRST_LINE_RECOMMENDED → canonical FIRST_LINE_RECOMMENDED, agreement 1.0, NO alert.
  2. 2 FIRST_LINE_RECOMMENDED + 1 NOT_MENTIONED → canonical FIRST_LINE_RECOMMENDED, agreement 0.67, alert raised (favorable↔absent span), reason contains "VARIANCE" and the counts.
  3. 1/1/1 three distinct positions → canonical None, alert raised (no majority).
  4. 2 AMONG_OPTIONS + 1 SECOND_LINE (no favorable↔unfavorable span, has majority) → canonical AMONG_OPTIONS, NO alert.
  5. idempotent: second compute → groups 0.
  6. sentiment_mean/stdev correct for a known set.

### Task 5: CLI `ema consensus` + config wiring

**Files:** `ema_poc/cli.py`, `config/settings.yaml`, `tests/test_cli.py`.

- `config/settings.yaml`: add `samples_per_question: 3` under `settings:`.
- `Deps`: add `compute_consensus: Callable | None = None`; wire default in `default_deps()` (lazy import).
- `_parse_args`: `sub.add_parser("consensus", help="Compute majority-vote consensus + variance alerts")`. Do NOT add to credential-validation (pure computation, no network).
- `main` branch: open DB, `summary = deps.compute_consensus(conn)`, `deps.out(f"Consensus: {summary.groups} group(s), variance alerts {summary.alerts_raised}.")`, return 0.
- Tests (fake Deps): `main(["consensus"], deps=...)` returns 0, calls compute_consensus, prints summary; no credential requirement.

---

## Self-Review Notes (author)
- Spec coverage: sampling (T1 schema/config + T2 runner), scoring unchanged, consensus compute + variance alert (T4) + storage (T3), CLI/config (T5), offline tests each task.
- sample_index additive migration (NOT NULL + DEFAULT 0 is ADD COLUMN-safe). consensus is a new table.
- Variance rule: no-majority OR favorable↔unfavorable span. Canonical = unique top vote else None.
- Existing runner tests: set samples_per_question=1 in their fixtures to preserve single-sample assertions; add new multi-sample tests.
- Type consistency: `completed_keys -> set[(qid,llm,sample_index)]`; `build_response(..., sample_index=0)`; `compute_consensus(conn,*,now_factory,id_factory)->ConsensusSummary(groups,alerts_raised)`; `save_consensus(...)`/`existing_groups`/`list_consensus`.
