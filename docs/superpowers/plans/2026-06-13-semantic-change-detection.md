# Semantic Change Detection & Drift Alerts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Detect material semantic change in a monitored LLM's answer vs a frozen v0 baseline, and raise a distinct drift alert when cosine-to-baseline < threshold OR competitive_position changed.

**Architecture:** New `ema_poc/drift/` package (embeddings + baseline + detector), two new append-only tables (`response_embeddings`, `drift_baselines`), drift alerts reuse the `alerts` table with a `DRIFT:` reason. OpenAI embeddings API (`text-embedding-3-small`), pure-Python cosine, injected client + fakes (offline tests).

**Branch:** `feature/semantic-drift` (off develop).

**Spec:** `docs/superpowers/specs/2026-06-13-semantic-change-detection-design.md`.

---

### Task 1: DriftConfig + schema (two tables)

**Files:** `ema_poc/config.py`, `ema_poc/db.py`, `config/settings.yaml`, tests `tests/test_config_load.py`, `tests/test_db.py`.

- Add `DriftConfig(BaseModel)` with `embedding_model: str = "text-embedding-3-small"`, `embedding_api_key_env: str = "OPENAI_API_KEY"`, `cosine_threshold: float = 0.85`. Add `drift: DriftConfig = Field(default_factory=DriftConfig)` to `AppConfig`. In `load_config`, parse `settings_raw.get("drift", {})` into `DriftConfig` (defaults if absent).
- Add the two tables (see spec) to the `SCHEMA` string in `db.py` (after `response_citations` or `audit_log`). They are new tables → no additive migration needed.
- Add a `drift:` block to `config/settings.yaml`.
- Tests: config loads a DriftConfig with defaults when `drift:` absent and with overrides when present; `init_schema` creates both tables (PRAGMA table_info shows the columns).

### Task 2: embeddings module + repository

**Files:** `ema_poc/drift/__init__.py` (empty), `ema_poc/drift/embeddings.py`, `ema_poc/repositories/embeddings.py`, tests.

- `cosine_similarity(a: list[float], b: list[float]) -> float` — pure Python; returns 0.0 if either norm is 0.
- `EmbeddingClient` protocol with `embed(text: str) -> list[float]`. Default `OpenAIEmbeddingClient(api_key, model)` lazily `import openai`, calls `client.embeddings.create(model=, input=text)`, returns `resp.data[0].embedding`.
- Repository `ema_poc/repositories/embeddings.py`: `save_embedding(conn, *, response_id, model, vector, now, commit=True)` (JSON-encodes vector), `get_embedding(conn, response_id) -> list[float] | None`, `has_embedding(conn, response_id) -> bool`.
- `embed_response(conn, response, *, client, model, now)` — idempotent: if `has_embedding`, return; else embed `response.response_text` and save.
- Tests (fake client returning fixed vectors): cosine identical→1.0 / orthogonal→0.0; save+get round-trip; embed_response idempotent; FK rejects unknown response_id.

### Task 3: baseline module + repository

**Files:** `ema_poc/drift/baseline.py`, `ema_poc/repositories/baselines.py`, tests.

- Repository: `set_baseline(conn, *, question_id, llm_name, response_id, now, commit=True)` (INSERT OR REPLACE on PK), `get_baseline(conn, question_id, llm_name) -> BaselineRow | None`, `list_baselines(conn) -> list[BaselineRow]`.
- `freeze_baseline(conn, *, now, force=False) -> int` — for each (question_id, llm_name) pair that has at least one SCORED response (competitive_position not null), if no baseline exists (or force), set the baseline to that pair's latest scored response_id. Returns count frozen. Use `latest_responses`-style query but restricted to scored responses.
- Tests: freeze snapshots the latest scored response per pair; skips already-frozen unless force; ignores pairs with no scored response.

### Task 4: detector (detect_drift)

**Files:** `ema_poc/drift/detector.py`, tests.

- `detect_drift(conn, *, client, config, now, id_factory=uuid4().hex) -> DriftSummary` where DriftSummary has `compared: int, drifted: int`.
- For each baseline (question_id, llm_name, baseline response_id):
  - Find the latest scored response for that pair (`latest scored response`). If it IS the baseline response, skip (nothing new). 
  - Ensure embeddings exist for the baseline response and the latest response (call `embed_response` for each).
  - cosine = cosine_similarity(baseline_vec, latest_vec).
  - position_changed = (baseline.competitive_position != latest.competitive_position) and both not None.
  - If cosine < config.drift.cosine_threshold OR position_changed: build a `reason` string (`DRIFT: cosine {c:.2f} < {threshold}` and/or `DRIFT: position {base} -> {latest}`; join with `; ` if both), look up the latest response's latest score_id (via scores repo), and `save_alert(Alert(alert_id=id_factory(), score_id=<latest score_id>, reason=reason, created_at=now))`. Increment drifted.
  - Increment compared.
- If the latest response has no score row, skip (can't attach alert) — but this shouldn't happen since we filter to scored responses.
- Tests (fake client mapping text→vector): drift raised on low cosine (different vectors); raised on position change with identical vectors; NOT raised when identical vectors + same position; alert reason has DRIFT: prefix and is tied to the latest score_id. Use the scores repo to create score rows in the fixture.

### Task 5: CLI (`ema baseline-freeze`, `ema drift`)

**Files:** `ema_poc/cli.py`, `ema_poc/drift/embeddings.py` (a default client factory), tests `tests/test_cli.py`.

- `Deps`: add `freeze_baseline`, `detect_drift`, and `make_embedding_client` (callable env->EmbeddingClient). Wire defaults in `default_deps()` (lazy imports).
- `_parse_args`: add `baseline-freeze` (with `--force`) and `drift` subparsers.
- `main`: 
  - `baseline-freeze` → open DB, `n = deps.freeze_baseline(conn, now=..., force=args.force)`, print count. No credential validation.
  - `drift` → add `"drift"` to the credential-validation set (it needs OPENAI_API_KEY for embeddings); open DB, build embedding client via `deps.make_embedding_client(deps.env, config)`, `summary = deps.detect_drift(conn, client=client, config=config, now=...)`, print summary. Return 0.
- Tests (fake Deps): `baseline-freeze` calls freeze_baseline and prints count; `drift` builds a client and calls detect_drift and prints summary; both via injected fakes (no network).

---

## Self-Review Notes (author)
- Spec coverage: similarity engine (T2 cosine + OpenAI client), frozen baseline (T3), drift trigger cosine OR position (T4), config threshold (T1), CLI (T5), offline tests (every task). 
- New tables are additive (CREATE TABLE IF NOT EXISTS) — safe on the existing migrated DB.
- Alert reuse: drift alerts attach to the latest score_id of the current response; reason `DRIFT:`-prefixed; appear in existing Alerts dashboard section.
- Type consistency: `EmbeddingClient.embed(text)->list[float]`; `cosine_similarity(list,list)->float`; `embed_response(conn, response, *, client, model, now)`; `freeze_baseline(conn,*,now,force)`; `detect_drift(conn,*,client,config,now,id_factory)`.
