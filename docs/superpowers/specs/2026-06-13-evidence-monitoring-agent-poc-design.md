# Evidence Monitoring Agent — POC Design Spec

**Date:** 2026-06-13
**Status:** Approved (brainstorming → ready for planning)
**Source requirements:** Evidence Monitoring Agent POC SRS (BR / FR / DM / IN / SC / SE / NF / AC). Requirement IDs referenced inline.

---

## 1. Purpose & Scope

Automated system that submits a curated, persona-tagged bank of questions to multiple monitored LLMs on a daily schedule, stores every response as a structured immutable record, scores each response for AbbVie brand sentiment and competitive positioning using Claude, raises threshold-based alerts, and surfaces findings in a self-contained HTML dashboard for Medical Affairs and Commercial.

**POC success (AC):** an unattended run of ~100 approved questions across 3–4 LLMs completes without manual intervention; responses are correctly stored and queryable; the dashboard shows baseline sentiment and competitive-positioning data confirmed actionable by stakeholders.

**Out of scope for POC:** production MLR/Medical Affairs workflow integration, real-time alerting pipeline (prototype only), full clinical-accuracy scoring, integration with existing AbbVie platforms (Veeva/Salesforce/data lake), Open Evidence API (included only if access confirmed), authN/RBAC/multi-tenant, mobile/native apps.

---

## 2. Key Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Language/runtime | **Python 3.11+** | Mature vendor SDKs; CSV/Excel curation; SRS assumes Python query API. |
| Storage | **SQLite** (stdlib `sqlite3` + repository layer) | Handles POC scale; supports immutable/versioned/queryable needs; zero infra; same schema migratable to Postgres later. |
| Dashboard | **Self-contained static HTML** | Matches FR-603 (no install, emailable); data inlined; client-side filtering. |
| Build approach | **Full pipeline** (sequenced by build order below) | User-selected. |
| Orchestration (FR-202) | **Deterministic Python loop; Claude invoked only for judgment steps** (response validation + scoring) | Reliable/cheap/resumable for 300+ unattended daily calls; satisfies FR-202 intent (Claude coordinates every reasoning-dependent decision). |

### Model pins (all config-driven per IN-103 / NF-010; none hardcoded)

| Role | Model | Notes |
|---|---|---|
| Orchestrator judgment + scoring | `claude-opus-4-8` | **Opus 4.8 API constraints:** `thinking={"type":"adaptive"}` only; `temperature`/`top_p`/`budget_tokens` are rejected with HTTP 400 — must NOT be set on Claude calls. Scoring uses `client.messages.parse()` with a Pydantic schema (FR-404). |
| Monitored Claude target (IN-301) | `claude-opus-4-8` (default, configurable) | Separate client/object from orchestrator; tagged `role=TARGET`. Medical Affairs should confirm the model that real end-users actually hit. Params: `thinking={"type":"adaptive"}`, `max_tokens=1024`, **no temperature** (IN-303). |
| OpenAI target (IN-1) | `gpt-4o` (pin `gpt-4o-2024-11-20`) | `temperature=0.3`, `max_tokens=1024` (IN-104), per-domain overridable. |
| Gemini target (IN-2) | `gemini-1.5-pro` (configurable) | **Dated** — confirm/upgrade current Gemini before launch. `temperature=0.3`, `max_output_tokens=1024` (IN-203). Safety blocks → `BLOCKED` status (IN-204). |
| Open Evidence (IN-4) | conditional | Added via config + adapter only if access confirmed; same interface (IN-402). |

---

## 3. Architecture & Module Boundaries

Deterministic Python pipeline. Each module has one responsibility and is independently testable with no circular dependencies (NF-012).

```
config/                      # YAML: settings.yaml (settings + brand lists), llm_targets.yaml (targets + per-target rate limits + pricing) (NF-010)
.env                         # API keys / secrets (never committed) (IN-501)
ema_poc/
  config.py        Load + Pydantic-validate config; verify all credentials present/reachable at startup, else exit (IN-502)
  db.py            SQLite connection + schema creation/migration
  models.py        Pydantic models: Question, Response, Run, Score, Alert
  repositories/    The ONLY code that touches SQL
    questions.py     CRUD, CSV/Excel import, versioning, filtering (FR-1)
    responses.py     Immutable writes, query-by-any-combination, CSV/JSON export, diff (FR-3)
    runs.py          Run records + resumability state (FR-5)
    scores.py        Versioned scoring records (FR-304/407)
    alerts.py        Alert records (FR-405)
  adapters/        One module per vendor, behind a shared interface
    base.py          LLMAdapter ABC + LLMResponse dataclass
    openai_adapter.py
    gemini_adapter.py
    claude_adapter.py
    open_evidence_adapter.py   # conditional stub, same interface (IN-402)
    registry.py      Build adapters from config — new target = config + adapter module, no core change (NF-010)
  agent/
    executor.py      Retry/backoff (3×: 2/4/8s), per-target rate limiting, truncation retry (FR-206/207/211)
    runner.py        Run loop: per-question fan-out across targets (concurrent), immediate write, resumability, run summary (FR-2)
  scoring/
    scorer.py        Claude structured-output scoring (FR-401–404, 406, 407)
    alerts.py        Alert rule logic (FR-405)
  dashboard/
    build.py         Generate self-contained HTML
    template.html    Inlined chart lib + client-side filtering
  logging_setup.py   Structured JSON logging + credential redaction (NF-007, SE-006)
  audit.py           Append-only audit log (insert-only) (BR-010, SE-003)
  cli.py             Entrypoints: run · dry-run · score · dashboard · import-questions · healthcheck
tests/               Mirror of ema_poc/ (TDD)
pyproject.toml · README.md · .env.example
```

### Adapter interface (the pluggability boundary)

```python
@dataclass
class LLMResponse:
    text: str
    finish_reason: str          # normalized: stop | length | error | blocked
    status: str                 # SUCCESS | FAILED | TRUNCATED | BLOCKED
    prompt_tokens: int | None
    completion_tokens: int | None
    raw: dict                   # vendor payload, for audit

class LLMAdapter(ABC):
    name: str                   # from config, e.g. "GPT-4o"
    model_version: str          # pinned, from config (IN-103)
    @abstractmethod
    def query(self, system_prompt: str, question_text: str, params: dict) -> LLMResponse: ...
```

Adapters own only vendor request-shaping + response normalization (incl. Gemini safety-block → `BLOCKED`, truncation detection). **Retry, backoff, rate-limiting live once in `agent/executor.py`** so all targets behave identically. Claude target adapter is distinct from the orchestrator/scoring client; logs tag `role=ORCHESTRATOR|TARGET` (IN-301/302).

### Run loop (`agent/runner.py`)

For each `active AND APPROVED` question (SE-002, BR-009): fan out to all configured targets **concurrently** (`ThreadPoolExecutor`, NF-003); write each response **immediately** to the Response Repository; then advance to the next question (FR-204). Every `(run_id, question_id, llm)` is written as it completes, so on resume the runner skips already-`SUCCESS` pairs for that `run_id` (FR-504, NF-005). Emits run summary (counts by status, tokens, est. cost, alert count) per NF-008 / NF-014.

### Scheduling & deployment

Single CLI entrypoint `ema run`; **OS `cron` invokes it daily at 02:00 UTC** (documented in README, FR-502); resumability lives in the DB, not the scheduler. `dry-run` validates connectivity/config without writing (FR-209). `run --persona/--ta/--brand/--domain` does subset runs (FR-210). Ad-hoc runs = invoking the CLI (FR-506). Runs on a single machine/container, no scheduler service.

---

## 4. Data Model (DM)

SQLite tables (one row = one record; derived fields versioned separately):

- **questions** — `question_id, question_text, persona(Prospect|Provider|Patient), therapeutic_area, brand_focus, domain(Efficacy|Safety|Access|Comparative|General), active(bool), approval_status(PENDING|APPROVED|REJECTED), approver_name, version, created_at, updated_at, deleted_at(soft-delete), delete_reason` (FR-102, SE-002, DM-003). Editing/deactivating creates a new version row; history never deleted (FR-103).
- **llm_targets** — sourced from config, not a table (NF-010). (Config holds name, adapter, model_version, params, rate limits.)
- **runs** — `run_id, started_at, ended_at, questions_attempted, responses_captured, failure_count, total_tokens, est_cost, status` (FR-503).
- **responses** — `response_id(UUID), run_id, timestamp_utc, llm_name, llm_model_version, persona, question_id, question_text(denormalised), therapeutic_area, brand_focus, domain, response_text(full/unedited), response_tokens, finish_reason, status(SUCCESS|FAILED|TRUNCATED|BLOCKED), sentiment_score(nullable), competitive_position(nullable), alert_triggered(bool), created_at` (FR-302). **Immutable once written** (FR-304, DM-002).
- **scores** — `score_id, response_id(FK), version, sentiment_score(float), competitive_position(enum), brand_mentions(json), key_claims(json), scoring_rationale, scoring_model, human_override(bool), override_rationale, created_at` (FR-304/404/407/408). New version per (re)score; original response untouched.
- **alerts** — `alert_id, score_id(FK), reason, created_at` (FR-405).
- **audit_log** — append-only, insert-only: `id, timestamp, event_type, role(ORCHESTRATOR|TARGET), question_id, llm_target, http_status, detail` (BR-010, SE-003).

Retention: responses kept ≥24 months, full/unmodified; soft-delete only (DM-001/002/003).

---

## 5. Scoring & Alerting (FR-4)

`scoring/scorer.py` reads `SUCCESS` responses lacking a current score and calls `claude-opus-4-8` via `client.messages.parse()` with:

```python
class ScoreResult(BaseModel):
    sentiment_score: float                 # -1.0..+1.0 (FR-402)
    competitive_position: Literal[
        "FIRST_LINE_RECOMMENDED","AMONG_OPTIONS","SECOND_LINE",
        "NOT_RECOMMENDED","NOT_MENTIONED"]  # FR-403
    brand_mentions: list[str]
    key_claims: list[str]                  # up to 5
    scoring_rationale: str
```

Adaptive thinking; no temperature (Opus 4.8). Scores written as new versioned rows linked to `response_id` (FR-304); re-scoring after prompt change adds a version (FR-407). Runs automatically at end of `ema run`, also callable standalone (`ema score`) for re-scoring history (FR-406/407). Human override supported as an additional row without deleting the AI score (FR-408).

`scoring/alerts.py` — pure function over (score, response). Flag if `sentiment_score < -0.3` **OR** `competitive_position == NOT_RECOMMENDED` **OR** a known competitor in `brand_mentions` scores materially higher than the AbbVie therapy in the same response (FR-405). Competitor list + AbbVie-brand mapping come from **config**, keeping code content-agnostic (SE-007). Alerts persisted and surfaced in run summary + dashboard. Optional config'd webhook/email of run summary, off by default (FR-505).

---

## 6. Dashboard (FR-6)

`ema dashboard` queries the repository and renders a **single self-contained HTML file** — data inlined as JSON, charts via an embedded JS lib (Chart.js or Plotly, inlined), client-side JS filtering by persona / TA / LLM / date range (FR-604). No server; emailable (FR-603). Displays: sentiment distribution by LLM & therapy; competitive-position breakdown by LLM; alert count + flagged list; response volume over time (FR-602). Row click → full response text + scoring rationale (FR-605). Side-by-side same-question comparison (FR-606) included if cheap, else deferred.

---

## 7. Cross-Cutting

- **Config (`config.py`):** `settings.yaml` (settings + brand lists), `llm_targets.yaml` (targets + per-target rate limits + pricing) + `.env`. Rate limits are consolidated into each target entry rather than a standalone `rate_limits.yaml`, so each target owns its own limits — still fully externalised per FR-207/NF-010. Startup validates config (Pydantic) and verifies every required credential present/reachable, exiting with a clear error before any query (IN-501/502).
- **Logging (`logging_setup.py`):** structured JSON to file — run start/stop, dispatch, response, retry, error, alert — timestamp/severity/context (NF-007); redaction filter masks credential-pattern strings (SE-006).
- **Audit (`audit.py`):** separate append-only/insert-only table; every external LLM call (timestamp, question_id, target, role, HTTP status) and scoring decision recorded for compliance review (BR-010, SE-003).
- **Governance:** runner dispatches only `active AND APPROVED` questions (SE-002, BR-009). No PII stored/required; questions generic (SE-001, BR-012).
- **Cost (NF-014/015):** tokens tracked per run/target; run summary includes est. API cost from config'd per-model pricing; optional `max_tokens_per_run` budget pauses+notifies rather than proceeding silently.

---

## 8. Non-Functional Targets

- Full daily run (100 Q × 3 LLMs = 300 calls) completes < 4h at rate-limited cadence (NF-001); concurrent fan-out across targets (NF-003).
- Scoring completes < 30 min after collection (NF-002).
- ≥95% capture rate over 7-day continuous run (NF-004); resumable with no data loss (NF-005); auto-recovery from transient errors (NF-006).
- Health-check CLI verifies connectivity to all targets (NF-009).
- ≥70% unit-test coverage on: question repo CRUD, adapter retry logic, response schema validation, scoring output parsing (NF-013).

---

## 9. Testing Strategy

TDD throughout. Unit tests with mocked vendor clients cover: question repo CRUD + CSV import, executor retry/backoff, response schema validation, scoring-output parsing, alert-rule logic. `dry-run` integration smoke test validates adapters against live APIs without writing. Target ≥70% coverage on the named modules (NF-013).

---

## 10. Build Order (one-pass implementation)

1. Foundations — config, db, models, logging, audit
2. Question Repository — CRUD, CSV/Excel import, versioning, filtering, approval
3. Adapters + executor + runner — OpenAI/Gemini/Claude, retry/rate-limit, concurrent fan-out, resumable runs, dry-run
4. Response Repository — query-by-any-combination, CSV/JSON export, diff
5. Scoring + alerting — structured-output scoring, versioned scores, alert rules
6. Scheduling — run summary, cost tracking, cron docs, ad-hoc/subset/health-check
7. Dashboard — static HTML with charts + filtering

Each phase lands with its tests.
```
