# Evidence Monitoring Agent — Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation layer (project scaffolding, config loading + credential validation, SQLite schema, domain models, structured logging with secret redaction, and an append-only audit log) that every later phase of the Evidence Monitoring Agent POC depends on.

**Architecture:** A deterministic Python package `ema_poc`. This phase delivers the cross-cutting primitives only — no LLM calls yet. Config is loaded from YAML + `.env` and validated with Pydantic; storage is a single SQLite file whose schema is created idempotently; logging emits JSON lines with credential redaction; the audit log is a separate insert-only table.

**Tech Stack:** Python 3.11+, Pydantic v2, PyYAML, stdlib `sqlite3` + `logging`, pytest + pytest-cov.

**Spec:** `docs/superpowers/specs/2026-06-13-evidence-monitoring-agent-poc-design.md` (sections 3, 4, 7).

**Conventions for this phase:**
- Timestamps are stored as ISO-8601 UTC strings.
- Tests import `ema_poc` directly (no install needed) via pytest `pythonpath`.
- `datetime`/`uuid` are injectable (passed as args with defaults) so tests are deterministic.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `ema_poc/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Create the virtualenv and install dependencies**

Run:
```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -q "pydantic>=2" pyyaml pytest pytest-cov
```
Expected: installs complete with no error.

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "ema-poc"
version = "0.1.0"
description = "Evidence Monitoring Agent POC"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2",
    "pyyaml",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-cov"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-q"

[tool.coverage.run]
source = ["ema_poc"]
```

- [ ] **Step 3: Create the package and test package init files**

`ema_poc/__init__.py`:
```python
"""Evidence Monitoring Agent POC."""

__version__ = "0.1.0"
```

`tests/__init__.py`:
```python
```

- [ ] **Step 4: Write the failing smoke test**

`tests/test_smoke.py`:
```python
def test_package_imports():
    import ema_poc

    assert ema_poc.__name__ == "ema_poc"
    assert ema_poc.__version__ == "0.1.0"
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/test_smoke.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml ema_poc/__init__.py tests/__init__.py tests/test_smoke.py
git commit -m "chore: scaffold ema_poc package and pytest config"
```

---

### Task 2: Domain models and enums

**Files:**
- Create: `ema_poc/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
import pytest
from pydantic import ValidationError

from ema_poc.models import (
    Question,
    Response,
    Run,
    Score,
    Alert,
    Persona,
    Domain,
    ApprovalStatus,
    ResponseStatus,
    CompetitivePosition,
)


def test_question_valid():
    q = Question(
        question_id="Q1",
        question_text="Is drug X first-line for condition Y?",
        persona=Persona.PROVIDER,
        domain=Domain.COMPARATIVE,
    )
    assert q.version == 1
    assert q.active is True
    assert q.approval_status is ApprovalStatus.PENDING


def test_question_rejects_bad_persona():
    with pytest.raises(ValidationError):
        Question(
            question_id="Q1",
            question_text="text",
            persona="Doctor",  # not a valid Persona
            domain=Domain.GENERAL,
        )


def test_response_defaults_and_enum():
    r = Response(
        response_id="r-1",
        run_id="run-1",
        timestamp_utc="2026-06-13T02:00:00+00:00",
        llm_name="GPT-4o",
        llm_model_version="gpt-4o-2024-11-20",
        persona=Persona.PATIENT,
        question_id="Q1",
        question_text="text",
        domain=Domain.SAFETY,
        response_text="some answer",
        status=ResponseStatus.SUCCESS,
    )
    assert r.alert_triggered is False
    assert r.sentiment_score is None


def test_score_sentiment_bounds():
    with pytest.raises(ValidationError):
        Score(
            score_id="s-1",
            response_id="r-1",
            sentiment_score=1.5,  # out of [-1, 1]
            competitive_position=CompetitivePosition.AMONG_OPTIONS,
            scoring_model="claude-opus-4-8",
        )


def test_run_and_alert_construct():
    run = Run(run_id="run-1", started_at="2026-06-13T02:00:00+00:00")
    assert run.status == "RUNNING"
    alert = Alert(alert_id="a-1", score_id="s-1", reason="sentiment < -0.3")
    assert alert.reason
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.models'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/models.py`:
```python
"""Pydantic domain models and enums (spec §4)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Persona(str, Enum):
    PROSPECT = "Prospect"
    PROVIDER = "Provider"
    PATIENT = "Patient"


class Domain(str, Enum):
    EFFICACY = "Efficacy"
    SAFETY = "Safety"
    ACCESS = "Access"
    COMPARATIVE = "Comparative"
    GENERAL = "General"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ResponseStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TRUNCATED = "TRUNCATED"
    BLOCKED = "BLOCKED"


class CompetitivePosition(str, Enum):
    FIRST_LINE_RECOMMENDED = "FIRST_LINE_RECOMMENDED"
    AMONG_OPTIONS = "AMONG_OPTIONS"
    SECOND_LINE = "SECOND_LINE"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"
    NOT_MENTIONED = "NOT_MENTIONED"


class Question(BaseModel):
    question_id: str
    version: int = 1
    question_text: str
    persona: Persona
    therapeutic_area: str | None = None
    brand_focus: str | None = None
    domain: Domain
    active: bool = True
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approver_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
    delete_reason: str | None = None


class Run(BaseModel):
    run_id: str
    started_at: datetime
    ended_at: datetime | None = None
    questions_attempted: int = 0
    responses_captured: int = 0
    failure_count: int = 0
    total_tokens: int = 0
    est_cost: float = 0.0
    status: str = "RUNNING"


class Response(BaseModel):
    response_id: str
    run_id: str
    timestamp_utc: datetime
    llm_name: str
    llm_model_version: str
    persona: Persona
    question_id: str
    question_text: str
    therapeutic_area: str | None = None
    brand_focus: str | None = None
    domain: Domain
    response_text: str
    response_tokens: int | None = None
    finish_reason: str | None = None
    status: ResponseStatus
    sentiment_score: float | None = None
    competitive_position: CompetitivePosition | None = None
    alert_triggered: bool = False
    created_at: datetime | None = None


class Score(BaseModel):
    score_id: str
    response_id: str
    version: int = 1
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    competitive_position: CompetitivePosition
    brand_mentions: list[str] = Field(default_factory=list)
    key_claims: list[str] = Field(default_factory=list)
    scoring_rationale: str | None = None
    scoring_model: str
    human_override: bool = False
    override_rationale: str | None = None
    created_at: datetime | None = None


class Alert(BaseModel):
    alert_id: str
    score_id: str
    reason: str
    created_at: datetime | None = None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/test_models.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/models.py tests/test_models.py
git commit -m "feat: add domain models and enums"
```

---

### Task 3: Config schema and YAML loader

**Files:**
- Create: `ema_poc/config.py`
- Create: `config/settings.yaml`
- Create: `config/llm_targets.yaml`
- Create: `.env.example`
- Test: `tests/test_config_load.py`

Note: rate limits live inside each target entry in `llm_targets.yaml`; brands and global settings live in `settings.yaml`. (Consolidated from the spec's three-file mention — cleaner, each target owns its own limits.)

- [ ] **Step 1: Write the failing test**

`tests/test_config_load.py`:
```python
from pathlib import Path

import pytest

from ema_poc.config import load_config


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    (tmp_path / "settings.yaml").write_text(
        """
settings:
  db_path: test.sqlite
  schedule_cron: "0 2 * * *"
  max_retries: 3
  backoff_seconds: [2, 4, 8]
  orchestrator_model: claude-opus-4-8
  scoring_model: claude-opus-4-8
  anthropic_api_key_env: ANTHROPIC_API_KEY
brands:
  abbvie_brands: ["Skyrizi", "Rinvoq"]
  competitor_brands: ["Humira-biosimilar", "Stelara"]
"""
    )
    (tmp_path / "llm_targets.yaml").write_text(
        """
targets:
  - name: GPT-4o
    adapter: openai
    model_version: gpt-4o-2024-11-20
    api_key_env: OPENAI_API_KEY
    params: {temperature: 0.3, max_tokens: 1024}
    pricing: {input_per_1k: 0.0025, output_per_1k: 0.01}
    rate_limit: {requests_per_minute: 60, tokens_per_minute: 90000}
  - name: Gemini-1.5-Pro
    adapter: gemini
    model_version: gemini-1.5-pro
    api_key_env: GOOGLE_API_KEY
    enabled: false
    params: {temperature: 0.3, max_output_tokens: 1024}
    pricing: {input_per_1k: 0.00125, output_per_1k: 0.005}
    rate_limit: {requests_per_minute: 60, tokens_per_minute: 90000}
"""
    )
    return tmp_path


def test_load_config_parses_settings_targets_and_brands(config_dir: Path):
    cfg = load_config(config_dir)

    assert cfg.settings.db_path == "test.sqlite"
    assert cfg.settings.backoff_seconds == [2, 4, 8]
    assert cfg.brands.abbvie_brands == ["Skyrizi", "Rinvoq"]

    assert len(cfg.targets) == 2
    gpt = cfg.targets[0]
    assert gpt.name == "GPT-4o"
    assert gpt.adapter == "openai"
    assert gpt.enabled is True
    assert gpt.rate_limit.requests_per_minute == 60
    assert gpt.params["temperature"] == 0.3

    gemini = cfg.targets[1]
    assert gemini.enabled is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/test_config_load.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.config'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/config.py`:
```python
"""Configuration schema, loading, and credential validation (spec §3, §7)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ConfigError(Exception):
    """Raised when configuration or required credentials are invalid/missing."""


class RateLimitConfig(BaseModel):
    requests_per_minute: int
    tokens_per_minute: int


class PricingConfig(BaseModel):
    input_per_1k: float
    output_per_1k: float


class LLMTargetConfig(BaseModel):
    name: str
    adapter: str  # openai | gemini | claude | open_evidence
    model_version: str
    api_key_env: str
    enabled: bool = True
    params: dict = Field(default_factory=dict)
    pricing: PricingConfig
    rate_limit: RateLimitConfig


class Settings(BaseModel):
    db_path: str = "ema.sqlite"
    schedule_cron: str = "0 2 * * *"
    max_retries: int = 3
    backoff_seconds: list[int] = Field(default_factory=lambda: [2, 4, 8])
    max_tokens_per_run: int | None = None
    orchestrator_model: str = "claude-opus-4-8"
    scoring_model: str = "claude-opus-4-8"
    anthropic_api_key_env: str = "ANTHROPIC_API_KEY"


class BrandConfig(BaseModel):
    abbvie_brands: list[str] = Field(default_factory=list)
    competitor_brands: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    settings: Settings
    brands: BrandConfig
    targets: list[LLMTargetConfig]


def load_config(config_dir: Path | str) -> AppConfig:
    config_dir = Path(config_dir)
    settings_raw = yaml.safe_load((config_dir / "settings.yaml").read_text()) or {}
    targets_raw = yaml.safe_load((config_dir / "llm_targets.yaml").read_text()) or {}

    return AppConfig(
        settings=Settings(**settings_raw.get("settings", {})),
        brands=BrandConfig(**settings_raw.get("brands", {})),
        targets=[LLMTargetConfig(**t) for t in targets_raw.get("targets", [])],
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/test_config_load.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Create the real config files and `.env.example`**

`config/settings.yaml`:
```yaml
settings:
  db_path: ema.sqlite
  schedule_cron: "0 2 * * *"      # daily 02:00 UTC (FR-502)
  max_retries: 3                  # FR-206
  backoff_seconds: [2, 4, 8]      # FR-206
  max_tokens_per_run: null        # NF-015; null = no budget cap
  orchestrator_model: claude-opus-4-8
  scoring_model: claude-opus-4-8
  anthropic_api_key_env: ANTHROPIC_API_KEY

brands:                            # SE-007: content lives in config, not code
  abbvie_brands: []
  competitor_brands: []
```

`config/llm_targets.yaml`:
```yaml
targets:
  - name: GPT-4o
    adapter: openai
    model_version: gpt-4o-2024-11-20   # IN-103: pinned
    api_key_env: OPENAI_API_KEY
    params: {temperature: 0.3, max_tokens: 1024}   # IN-104
    pricing: {input_per_1k: 0.0025, output_per_1k: 0.01}
    rate_limit: {requests_per_minute: 60, tokens_per_minute: 90000}

  - name: Gemini-1.5-Pro
    adapter: gemini
    model_version: gemini-1.5-pro       # NOTE: confirm/upgrade to current Gemini before launch
    api_key_env: GOOGLE_API_KEY
    params: {temperature: 0.3, max_output_tokens: 1024}   # IN-203
    pricing: {input_per_1k: 0.00125, output_per_1k: 0.005}
    rate_limit: {requests_per_minute: 60, tokens_per_minute: 90000}

  - name: Claude-Opus-4.8
    adapter: claude
    model_version: claude-opus-4-8      # IN-301 monitored Claude target (NOT the orchestrator)
    api_key_env: ANTHROPIC_API_KEY
    params: {max_tokens: 1024}          # IN-303: adaptive thinking, NO temperature
    pricing: {input_per_1k: 0.005, output_per_1k: 0.025}
    rate_limit: {requests_per_minute: 50, tokens_per_minute: 80000}
```

`.env.example`:
```bash
# Copy to .env and fill in. Never commit .env (IN-501).
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=
```

- [ ] **Step 6: Commit**

```bash
git add ema_poc/config.py config/settings.yaml config/llm_targets.yaml .env.example tests/test_config_load.py
git commit -m "feat: add config schema, YAML loader, and example config"
```

---

### Task 4: Credential validation at startup

**Files:**
- Modify: `ema_poc/config.py` (add `validate_credentials`)
- Test: `tests/test_config_credentials.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config_credentials.py`:
```python
import pytest

from ema_poc.config import (
    AppConfig,
    BrandConfig,
    ConfigError,
    LLMTargetConfig,
    PricingConfig,
    RateLimitConfig,
    Settings,
    validate_credentials,
)


def _target(name: str, api_key_env: str, enabled: bool = True) -> LLMTargetConfig:
    return LLMTargetConfig(
        name=name,
        adapter="openai",
        model_version="x",
        api_key_env=api_key_env,
        enabled=enabled,
        pricing=PricingConfig(input_per_1k=0.0, output_per_1k=0.0),
        rate_limit=RateLimitConfig(requests_per_minute=60, tokens_per_minute=1000),
    )


def _config(targets) -> AppConfig:
    return AppConfig(settings=Settings(), brands=BrandConfig(), targets=targets)


def test_passes_when_all_credentials_present():
    cfg = _config([_target("GPT-4o", "OPENAI_API_KEY")])
    env = {"ANTHROPIC_API_KEY": "sk-a", "OPENAI_API_KEY": "sk-o"}
    validate_credentials(cfg, env)  # should not raise


def test_raises_listing_missing_credentials():
    cfg = _config([_target("GPT-4o", "OPENAI_API_KEY")])
    env = {"OPENAI_API_KEY": "sk-o"}  # ANTHROPIC missing
    with pytest.raises(ConfigError) as exc:
        validate_credentials(cfg, env)
    assert "ANTHROPIC_API_KEY" in str(exc.value)


def test_ignores_disabled_targets():
    cfg = _config([_target("Gemini", "GOOGLE_API_KEY", enabled=False)])
    env = {"ANTHROPIC_API_KEY": "sk-a"}
    validate_credentials(cfg, env)  # disabled target's key not required
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/test_config_credentials.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate_credentials'`.

- [ ] **Step 3: Add the implementation to `ema_poc/config.py`**

Add these imports at the top of `ema_poc/config.py` (below the existing imports):
```python
import os
from collections.abc import Mapping
```

Append to the end of `ema_poc/config.py`:
```python
def validate_credentials(
    config: AppConfig, env: Mapping[str, str] | None = None
) -> None:
    """Verify every required credential is present, else raise ConfigError (IN-502)."""
    if env is None:
        env = os.environ

    missing: list[str] = []
    if not env.get(config.settings.anthropic_api_key_env):
        missing.append(config.settings.anthropic_api_key_env)
    for target in config.targets:
        if target.enabled and not env.get(target.api_key_env):
            missing.append(target.api_key_env)

    if missing:
        raise ConfigError(
            "Missing required credentials: " + ", ".join(sorted(set(missing)))
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/test_config_credentials.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/config.py tests/test_config_credentials.py
git commit -m "feat: validate required credentials at startup"
```

---

### Task 5: SQLite connection and schema

**Files:**
- Create: `ema_poc/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

`tests/test_db.py`:
```python
from ema_poc.db import connect, init_schema

EXPECTED_TABLES = {
    "questions",
    "runs",
    "responses",
    "scores",
    "alerts",
    "audit_log",
}


def test_init_schema_creates_all_tables(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)

    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert EXPECTED_TABLES <= names


def test_init_schema_is_idempotent(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    init_schema(conn)  # second call must not raise


def test_row_factory_returns_mappings(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    conn.execute(
        "INSERT INTO runs (run_id, started_at) VALUES (?, ?)",
        ("run-1", "2026-06-13T02:00:00+00:00"),
    )
    conn.commit()
    row = conn.execute("SELECT run_id, status FROM runs").fetchone()
    assert row["run_id"] == "run-1"
    assert row["status"] == "RUNNING"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.db'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/db.py`:
```python
"""SQLite connection and schema (spec §4)."""

from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    question_id      TEXT NOT NULL,
    version          INTEGER NOT NULL DEFAULT 1,
    question_text    TEXT NOT NULL,
    persona          TEXT NOT NULL,
    therapeutic_area TEXT,
    brand_focus      TEXT,
    domain           TEXT NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1,
    approval_status  TEXT NOT NULL DEFAULT 'PENDING',
    approver_name    TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT,
    delete_reason    TEXT,
    PRIMARY KEY (question_id, version)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    started_at          TEXT NOT NULL,
    ended_at            TEXT,
    questions_attempted INTEGER NOT NULL DEFAULT 0,
    responses_captured  INTEGER NOT NULL DEFAULT 0,
    failure_count       INTEGER NOT NULL DEFAULT 0,
    total_tokens        INTEGER NOT NULL DEFAULT 0,
    est_cost            REAL NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'RUNNING'
);

CREATE TABLE IF NOT EXISTS responses (
    response_id          TEXT PRIMARY KEY,
    run_id               TEXT NOT NULL,
    timestamp_utc        TEXT NOT NULL,
    llm_name             TEXT NOT NULL,
    llm_model_version    TEXT NOT NULL,
    persona              TEXT NOT NULL,
    question_id          TEXT NOT NULL,
    question_text        TEXT NOT NULL,
    therapeutic_area     TEXT,
    brand_focus          TEXT,
    domain               TEXT NOT NULL,
    response_text        TEXT NOT NULL,
    response_tokens      INTEGER,
    finish_reason        TEXT,
    status               TEXT NOT NULL,
    sentiment_score      REAL,
    competitive_position TEXT,
    alert_triggered      INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_responses_run ON responses(run_id);
CREATE INDEX IF NOT EXISTS idx_responses_q_llm ON responses(question_id, llm_name);

CREATE TABLE IF NOT EXISTS scores (
    score_id             TEXT PRIMARY KEY,
    response_id          TEXT NOT NULL,
    version              INTEGER NOT NULL DEFAULT 1,
    sentiment_score      REAL NOT NULL,
    competitive_position TEXT NOT NULL,
    brand_mentions       TEXT NOT NULL,
    key_claims           TEXT NOT NULL,
    scoring_rationale    TEXT,
    scoring_model        TEXT NOT NULL,
    human_override       INTEGER NOT NULL DEFAULT 0,
    override_rationale   TEXT,
    created_at           TEXT NOT NULL,
    FOREIGN KEY (response_id) REFERENCES responses(response_id)
);
CREATE INDEX IF NOT EXISTS idx_scores_response ON scores(response_id);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id    TEXT PRIMARY KEY,
    score_id    TEXT NOT NULL,
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (score_id) REFERENCES scores(score_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    role        TEXT,
    question_id TEXT,
    llm_target  TEXT,
    http_status INTEGER,
    detail      TEXT
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/test_db.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/db.py tests/test_db.py
git commit -m "feat: add sqlite connection and schema"
```

---

### Task 6: Structured JSON logging with credential redaction

**Files:**
- Create: `ema_poc/logging_setup.py`
- Test: `tests/test_logging_setup.py`

- [ ] **Step 1: Write the failing test**

`tests/test_logging_setup.py`:
```python
import json
import logging

from ema_poc.logging_setup import JsonFormatter, RedactionFilter, redact


def test_redact_masks_known_secret_patterns():
    assert "sk-ABCDEF1234567890" not in redact("key=sk-ABCDEF1234567890")
    assert "AIzaABCDEF1234567890" not in redact("g=AIzaABCDEF1234567890")
    assert "REDACTED" in redact("Authorization: Bearer abcdef1234567890")


def test_json_formatter_emits_parseable_json_with_context():
    record = logging.LogRecord(
        name="ema",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="dispatched",
        args=(),
        exc_info=None,
    )
    record.context = {"llm_name": "GPT-4o", "question_id": "Q1"}
    out = JsonFormatter().format(record)
    parsed = json.loads(out)
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "dispatched"
    assert parsed["llm_name"] == "GPT-4o"
    assert parsed["question_id"] == "Q1"


def test_redaction_filter_scrubs_message():
    record = logging.LogRecord(
        name="ema",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="using key sk-SECRET1234567890",
        args=(),
        exc_info=None,
    )
    RedactionFilter().filter(record)
    assert "sk-SECRET1234567890" not in record.msg
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/test_logging_setup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.logging_setup'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/logging_setup.py`:
```python
"""Structured JSON logging with credential redaction (spec §7; NF-007, SE-006)."""

from __future__ import annotations

import json
import logging
import re

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),          # OpenAI / Anthropic style
    re.compile(r"AIza[0-9A-Za-z_\-]{8,}"),         # Google API key style
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),  # Bearer tokens
]

_REDACTION = "***REDACTED***"


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTION, text)
    return text


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload.update(context)
        return json.dumps(payload)


def get_logger(name: str = "ema", log_path: str | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    handler: logging.Handler = (
        logging.FileHandler(log_path) if log_path else logging.StreamHandler()
    )
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/test_logging_setup.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/logging_setup.py tests/test_logging_setup.py
git commit -m "feat: add structured JSON logging with credential redaction"
```

---

### Task 7: Append-only audit log

**Files:**
- Create: `ema_poc/audit.py`
- Test: `tests/test_audit.py`

- [ ] **Step 1: Write the failing test**

`tests/test_audit.py`:
```python
from ema_poc.audit import list_events, record_event
from ema_poc.db import connect, init_schema


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def test_record_event_persists_row(tmp_path):
    conn = _conn(tmp_path)
    record_event(
        conn,
        event_type="LLM_CALL",
        role="TARGET",
        question_id="Q1",
        llm_target="GPT-4o",
        http_status=200,
        detail="ok",
        timestamp="2026-06-13T02:00:00+00:00",
    )
    events = list_events(conn)
    assert len(events) == 1
    assert events[0]["event_type"] == "LLM_CALL"
    assert events[0]["role"] == "TARGET"
    assert events[0]["http_status"] == 200


def test_events_accumulate_append_only(tmp_path):
    conn = _conn(tmp_path)
    record_event(conn, event_type="A", timestamp="2026-06-13T02:00:00+00:00")
    record_event(conn, event_type="B", timestamp="2026-06-13T02:00:01+00:00")
    events = list_events(conn)
    assert [e["event_type"] for e in events] == ["A", "B"]


def test_module_exposes_no_mutation_helpers():
    import ema_poc.audit as audit

    # Audit log is insert-only by design (SE-003): no update/delete helpers.
    assert not hasattr(audit, "update_event")
    assert not hasattr(audit, "delete_event")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/test_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.audit'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/audit.py`:
```python
"""Append-only audit log (spec §7; BR-010, SE-003).

Insert-only by design: this module deliberately exposes no update or delete
helpers. The audit trail must be immutable for compliance review.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    role: str | None = None,
    question_id: str | None = None,
    llm_target: str | None = None,
    http_status: int | None = None,
    detail: str | None = None,
    timestamp: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log
            (timestamp, event_type, role, question_id, llm_target, http_status, detail)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            timestamp or _now_iso(),
            event_type,
            role,
            question_id,
            llm_target,
            http_status,
            detail,
        ),
    )
    conn.commit()


def list_events(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY id ASC"
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/test_audit.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/audit.py tests/test_audit.py
git commit -m "feat: add append-only audit log"
```

---

### Task 8: Foundations integration check + README stub

**Files:**
- Create: `README.md`
- Test: `tests/test_foundations_integration.py`

- [ ] **Step 1: Write the failing test**

`tests/test_foundations_integration.py`:
```python
"""End-to-end wiring of the foundation layer with no LLM calls."""

from pathlib import Path

from ema_poc.audit import list_events, record_event
from ema_poc.config import load_config, validate_credentials
from ema_poc.db import connect, init_schema


def _write_config(d: Path) -> None:
    (d / "settings.yaml").write_text(
        """
settings:
  db_path: ema.sqlite
brands:
  abbvie_brands: ["Skyrizi"]
  competitor_brands: ["Stelara"]
"""
    )
    (d / "llm_targets.yaml").write_text(
        """
targets:
  - name: GPT-4o
    adapter: openai
    model_version: gpt-4o-2024-11-20
    api_key_env: OPENAI_API_KEY
    pricing: {input_per_1k: 0.0025, output_per_1k: 0.01}
    rate_limit: {requests_per_minute: 60, tokens_per_minute: 90000}
"""
    )


def test_config_db_and_audit_wire_together(tmp_path):
    _write_config(tmp_path)

    cfg = load_config(tmp_path)
    validate_credentials(
        cfg, {"ANTHROPIC_API_KEY": "sk-a", "OPENAI_API_KEY": "sk-o"}
    )

    conn = connect(str(tmp_path / cfg.settings.db_path))
    init_schema(conn)

    record_event(
        conn,
        event_type="STARTUP",
        detail=f"loaded {len(cfg.targets)} target(s)",
        timestamp="2026-06-13T02:00:00+00:00",
    )
    events = list_events(conn)
    assert events[0]["event_type"] == "STARTUP"
    assert "1 target" in events[0]["detail"]
```

- [ ] **Step 2: Run the test to verify it fails (then passes — all deps exist)**

Run: `. .venv/bin/activate && pytest tests/test_foundations_integration.py -v`
Expected: PASS (the foundation modules already exist; this test asserts they wire together). If any import fails, fix the referenced module before continuing.

- [ ] **Step 3: Write the README stub**

`README.md`:
```markdown
# Evidence Monitoring Agent — POC

Automated monitoring of how multiple LLMs respond to persona-tagged questions
about AbbVie therapies: collect responses, score brand sentiment and
competitive positioning with Claude, alert on thresholds, and report via a
self-contained HTML dashboard.

See `docs/superpowers/specs/2026-06-13-evidence-monitoring-agent-poc-design.md`
for the full design.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in API keys
```

Required environment variables (see `.env.example`): `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `GOOGLE_API_KEY`.

## Configuration

- `config/settings.yaml` — global settings + AbbVie/competitor brand lists.
- `config/llm_targets.yaml` — monitored LLM targets, model pins, params,
  pricing, and per-target rate limits. Add a target by adding an entry here and
  a matching adapter module (no core code change).

## Running tests

```bash
. .venv/bin/activate && pytest
```

## Status

Foundations phase complete (config, storage, models, logging, audit).
Subsequent phases: question repository, LLM adapters + runner, response
repository, scoring + alerts, scheduling, dashboard.
```

- [ ] **Step 4: Run the whole suite to verify everything passes together**

Run: `. .venv/bin/activate && pytest --cov`
Expected: PASS (all tests across tasks 1–8 pass); coverage report prints for `ema_poc`.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_foundations_integration.py
git commit -m "test: foundations integration wiring + README"
```

---

## Self-Review

**Spec coverage (foundations scope — spec §3, §4, §7):**
- Project package + test harness → Task 1.
- Domain models/enums for all six entities (DM, §4) → Task 2.
- Config schema + YAML loading, model pins config-driven (IN-103, NF-010) → Task 3.
- Startup credential validation (IN-501/502) → Task 4.
- SQLite schema for questions/runs/responses/scores/alerts/audit_log, immutability via separate score versioning columns (FR-304), append-only audit table (SE-003) → Tasks 5, 7.
- Structured JSON logging (NF-007) + credential redaction (SE-006) → Task 6.
- Append-only audit log (BR-010, SE-003) → Task 7.
- End-to-end wiring + README → Task 8.

Deferred to later phases (correctly out of this plan's scope): question-repo CRUD/import/versioning logic (Phase 2), adapters/executor/runner (Phase 3), response query/export/diff (Phase 4), scoring/alerts logic (Phase 5), scheduling/run-summary/cost (Phase 6), dashboard (Phase 7). The schema and models for these entities exist now so later phases build on a stable base.

**Placeholder scan:** No "TBD"/"add error handling"/"similar to" placeholders — every code and test step contains complete content.

**Type consistency:** `connect`/`init_schema` (db.py) used identically in Tasks 5, 7, 8. `record_event`/`list_events` signatures match across Tasks 7 and 8. `load_config`/`validate_credentials` and the config model names (`AppConfig`, `LLMTargetConfig`, `PricingConfig`, `RateLimitConfig`, `Settings`, `BrandConfig`) are consistent across Tasks 3, 4, 8. Enum and model field names in Task 2 match the columns defined in Task 5.
```
