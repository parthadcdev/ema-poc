# Evidence Monitoring Agent — Scoring & Alerting Implementation Plan (Phase 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score each stored response for AbbVie brand sentiment and competitive positioning using Claude structured output, persist versioned scoring records, raise threshold-based alerts, and update the response's derived columns so the Phase 4 sentiment/alert filters work (FR-4: FR-401–408, plus BR-005/006).

**Architecture:** A `score_response` primitive calls `claude-opus-4-8` via `client.messages.parse(...)` with a Pydantic `ScoreResult` schema (FR-404) — the Anthropic client is injected so tests use a fake (no real API calls). A `scores` repository persists versioned, append-only score rows (FR-304/407). `evaluate_alert` is a pure function over a `ScoreResult` (FR-405) using config-driven AbbVie/competitor brand lists (SE-007). The `score_pending` pipeline ties them together: for each unscored SUCCESS response it scores, writes a versioned `Score`, updates the response's derived columns (`sentiment_score`/`competitive_position`/`alert_triggered` — the only mutation, content untouched), raises+persists an alert if warranted, and records an audit event.

**Spec reconciliation (FR-302 vs FR-304):** the `scores` table is the authoritative, append-only, versioned scoring record (FR-304/407). The response row's `sentiment_score`/`competitive_position`/`alert_triggered` are a denormalized cache of the latest score (FR-302: "nullable — populated by scoring pass") so Phase 4 filters (`query_responses(sentiment_max=..., alert_triggered=...)`) function. The scoring pass updates ONLY those three derived columns; captured content (response_text, status, etc.) is never modified.

**Tech Stack:** Python 3.11+, `anthropic` SDK (`messages.parse` — lazily/injected, not imported at module top), Pydantic v2, stdlib `sqlite3` + `json`. Built on Phases 1–4 (merged to `develop`).

**Spec:** `docs/superpowers/specs/2026-06-13-evidence-monitoring-agent-poc-design.md` (§5 scoring & alerting, FR-4, BR-005/006).

**Conventions:**
- Claude calls use `thinking={"type":"adaptive"}` and **no temperature** (Opus 4.8 rejects it).
- `now`/ids injectable; the Anthropic client and the scorer function are injectable so the pipeline test uses a fake (no network).
- Activate the venv with `. .venv/bin/activate` before pytest.

---

### Task 1: ScoreResult schema + Claude scoring primitive

**Files:**
- Create: `ema_poc/scoring/__init__.py`
- Create: `ema_poc/scoring/scorer.py`
- Test: `tests/scoring/__init__.py`
- Test: `tests/scoring/test_scorer.py`

- [ ] **Step 1: Write the failing test**

`tests/scoring/__init__.py`:
```python
```

`tests/scoring/test_scorer.py`:
```python
import pytest
from pydantic import ValidationError

from ema_poc.scoring.scorer import ScoreResult, score_response


class _FakeMessages:
    def __init__(self, result):
        self._result = result
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return type("Parsed", (), {"parsed_output": self._result})()


class _FakeClient:
    def __init__(self, result):
        self.messages = _FakeMessages(result)


def test_score_result_validates_sentiment_bounds():
    ScoreResult(
        sentiment_score=0.5, competitive_position="AMONG_OPTIONS",
        brand_mentions=["Skyrizi"], key_claims=["claim"], scoring_rationale="r",
    )
    with pytest.raises(ValidationError):
        ScoreResult(
            sentiment_score=1.5, competitive_position="AMONG_OPTIONS",
            brand_mentions=[], key_claims=[], scoring_rationale="r",
        )


def test_score_result_rejects_bad_competitive_position():
    with pytest.raises(ValidationError):
        ScoreResult(
            sentiment_score=0.0, competitive_position="MAYBE",
            brand_mentions=[], key_claims=[], scoring_rationale="r",
        )


def test_score_response_returns_parsed_output():
    expected = ScoreResult(
        sentiment_score=-0.4, competitive_position="SECOND_LINE",
        brand_mentions=["Skyrizi", "Humira"], key_claims=["c1"], scoring_rationale="why",
    )
    client = _FakeClient(expected)
    out = score_response(
        client, response_text="some answer", brand_focus="Skyrizi",
        abbvie_brands=["Skyrizi"], competitor_brands=["Humira"],
    )
    assert out is expected


def test_score_response_call_shape_opus48_rules():
    client = _FakeClient(ScoreResult(
        sentiment_score=0.0, competitive_position="NOT_MENTIONED",
        brand_mentions=[], key_claims=[], scoring_rationale="r",
    ))
    score_response(
        client, response_text="text about Skyrizi", brand_focus="Skyrizi",
        abbvie_brands=["Skyrizi"], competitor_brands=["Humira"],
        model="claude-opus-4-8",
    )
    kw = client.messages.kwargs
    assert kw["model"] == "claude-opus-4-8"
    assert kw["output_format"] is ScoreResult
    assert kw["thinking"] == {"type": "adaptive"}
    assert "temperature" not in kw  # Opus 4.8 rejects temperature
    # the response text and brand focus reach the prompt
    user_content = kw["messages"][0]["content"]
    assert "text about Skyrizi" in user_content
    assert "Skyrizi" in user_content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/scoring/test_scorer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.scoring'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/scoring/__init__.py`:
```python
"""Scoring & alerting — Claude sentiment/competitive scoring and alert rules (§5)."""
```

`ema_poc/scoring/scorer.py`:
```python
"""Brand sentiment + competitive positioning scoring via Claude (FR-401–404).

Uses claude-opus-4-8 with adaptive thinking and structured output
(client.messages.parse with a Pydantic schema). NO temperature (Opus 4.8
rejects it). The Anthropic client is injected so tests use a fake."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

_SYSTEM = (
    "You are a pharmaceutical brand-monitoring analyst for AbbVie. You assess "
    "how an LLM's response represents AbbVie therapies relative to competitors. "
    "Be objective and base every score strictly on the response text provided."
)


class ScoreResult(BaseModel):
    """Structured scoring output (FR-404)."""

    sentiment_score: float = Field(ge=-1.0, le=1.0)
    competitive_position: Literal[
        "FIRST_LINE_RECOMMENDED",
        "AMONG_OPTIONS",
        "SECOND_LINE",
        "NOT_RECOMMENDED",
        "NOT_MENTIONED",
    ]
    brand_mentions: list[str]
    key_claims: list[str]
    scoring_rationale: str


def _build_prompt(
    *, response_text: str, brand_focus, abbvie_brands, competitor_brands
) -> str:
    return (
        "Analyze the following LLM response about pharmaceutical therapies.\n\n"
        f"AbbVie therapy in focus: {brand_focus or 'the AbbVie therapy'}\n"
        f"Known AbbVie brands: {', '.join(abbvie_brands) or 'none provided'}\n"
        f"Known competitor brands: {', '.join(competitor_brands) or 'none provided'}\n\n"
        f'Response to analyze:\n"""\n{response_text}\n"""\n\n'
        "Score brand sentiment toward the AbbVie therapy from -1.0 (strongly "
        "negative) to +1.0 (strongly positive). Classify the AbbVie therapy's "
        "competitive positioning. List the brand names mentioned, up to 5 key "
        "claims about the therapy, and a brief scoring rationale."
    )


def score_response(
    client,
    *,
    response_text: str,
    brand_focus,
    abbvie_brands,
    competitor_brands,
    model: str = "claude-opus-4-8",
) -> ScoreResult:
    """Score one response. `client` is an Anthropic client (or a fake exposing
    `messages.parse`)."""
    parsed = client.messages.parse(
        model=model,
        max_tokens=1024,
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": _build_prompt(
                    response_text=response_text,
                    brand_focus=brand_focus,
                    abbvie_brands=abbvie_brands,
                    competitor_brands=competitor_brands,
                ),
            }
        ],
        output_format=ScoreResult,
    )
    return parsed.parsed_output
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/scoring/test_scorer.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/scoring/__init__.py ema_poc/scoring/scorer.py tests/scoring/__init__.py tests/scoring/test_scorer.py
git commit -m "feat: ScoreResult schema + Claude structured-output scoring primitive"
```

---

### Task 2: Scores repository + response derived-field update

**Files:**
- Create: `ema_poc/repositories/scores.py`
- Modify: `ema_poc/repositories/responses.py` (append `update_response_scoring`)
- Test: `tests/repositories/test_scores.py`

- [ ] **Step 1: Write the failing test**

`tests/repositories/test_scores.py`:
```python
from ema_poc.db import connect, init_schema
from ema_poc.models import CompetitivePosition, Response, Score
from ema_poc.repositories.responses import save_response, update_response_scoring
from ema_poc.repositories.runs import create_run
from ema_poc.repositories.scores import (
    latest_score,
    next_score_version,
    save_score,
    unscored_success_responses,
)

NOW = "2026-06-13T02:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=NOW)
    return conn


def _resp(conn, rid, *, status="SUCCESS"):
    save_response(conn, Response(
        response_id=rid, run_id="r1", timestamp_utc=NOW, llm_name="GPT-4o",
        llm_model_version="m", persona="Provider", question_id="Q1",
        question_text="q", domain="Safety", response_text="ans", response_tokens=1,
        finish_reason="stop", status=status, created_at=NOW,
    ))


def _score(rid, version=1, sentiment=0.2):
    return Score(
        score_id=f"{rid}-s{version}", response_id=rid, version=version,
        sentiment_score=sentiment, competitive_position="AMONG_OPTIONS",
        brand_mentions=["Skyrizi", "Humira"], key_claims=["c1", "c2"],
        scoring_rationale="rationale", scoring_model="claude-opus-4-8",
        created_at=NOW,
    )


def test_save_and_latest_score_roundtrips_json_fields(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "resp-1")
    save_score(conn, _score("resp-1", sentiment=-0.5))
    got = latest_score(conn, "resp-1")
    assert got.sentiment_score == -0.5
    assert got.competitive_position is CompetitivePosition.AMONG_OPTIONS
    assert got.brand_mentions == ["Skyrizi", "Humira"]  # JSON round-trip
    assert got.key_claims == ["c1", "c2"]
    assert latest_score(conn, "missing") is None
    conn.close()


def test_versioning_and_next_version(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "resp-1")
    assert next_score_version(conn, "resp-1") == 1
    save_score(conn, _score("resp-1", version=1))
    assert next_score_version(conn, "resp-1") == 2
    save_score(conn, _score("resp-1", version=2, sentiment=0.9))
    assert latest_score(conn, "resp-1").version == 2
    assert latest_score(conn, "resp-1").sentiment_score == 0.9  # latest wins
    conn.close()


def test_unscored_success_responses_excludes_scored_and_non_success(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "a", status="SUCCESS")
    _resp(conn, "b", status="SUCCESS")
    _resp(conn, "c", status="FAILED")  # non-success excluded
    save_score(conn, _score("a"))       # already scored excluded
    ids = [r.response_id for r in unscored_success_responses(conn)]
    assert ids == ["b"]
    conn.close()


def test_update_response_scoring_sets_derived_columns_only(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "resp-1")
    update_response_scoring(conn, "resp-1", sentiment_score=-0.7,
                            competitive_position="NOT_RECOMMENDED", alert_triggered=True)
    row = conn.execute(
        "SELECT sentiment_score, competitive_position, alert_triggered, response_text "
        "FROM responses WHERE response_id='resp-1'"
    ).fetchone()
    assert row["sentiment_score"] == -0.7
    assert row["competitive_position"] == "NOT_RECOMMENDED"
    assert row["alert_triggered"] == 1
    assert row["response_text"] == "ans"  # content untouched
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/repositories/test_scores.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.repositories.scores'`.

- [ ] **Step 3a: Write `ema_poc/repositories/scores.py`**

```python
"""Scores repository — append-only, versioned scoring records (FR-304/407)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from ema_poc.models import Response, Score


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def _score_from_row(row: sqlite3.Row) -> Score:
    data = dict(row)
    data["brand_mentions"] = json.loads(data["brand_mentions"]) if data["brand_mentions"] else []
    data["key_claims"] = json.loads(data["key_claims"]) if data["key_claims"] else []
    data["human_override"] = bool(data["human_override"])
    return Score(**data)


def save_score(conn: sqlite3.Connection, score: Score) -> None:
    conn.execute(
        """
        INSERT INTO scores (
            score_id, response_id, version, sentiment_score, competitive_position,
            brand_mentions, key_claims, scoring_rationale, scoring_model,
            human_override, override_rationale, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            score.score_id,
            score.response_id,
            score.version,
            score.sentiment_score,
            score.competitive_position.value,
            json.dumps(score.brand_mentions),
            json.dumps(score.key_claims),
            score.scoring_rationale,
            score.scoring_model,
            int(score.human_override),
            score.override_rationale,
            _iso(score.created_at),
        ),
    )
    conn.commit()


def latest_score(conn: sqlite3.Connection, response_id: str) -> Score | None:
    row = conn.execute(
        "SELECT * FROM scores WHERE response_id = ? ORDER BY version DESC LIMIT 1",
        (response_id,),
    ).fetchone()
    return _score_from_row(row) if row else None


def next_score_version(conn: sqlite3.Connection, response_id: str) -> int:
    row = conn.execute(
        "SELECT MAX(version) AS v FROM scores WHERE response_id = ?", (response_id,)
    ).fetchone()
    return (row["v"] or 0) + 1


def unscored_success_responses(conn: sqlite3.Connection) -> list[Response]:
    """SUCCESS responses that have no score row yet (FR-401)."""
    rows = conn.execute(
        """
        SELECT r.* FROM responses r
        LEFT JOIN scores s ON r.response_id = s.response_id
        WHERE r.status = 'SUCCESS' AND s.score_id IS NULL
        ORDER BY r.timestamp_utc ASC, r.response_id ASC
        """
    ).fetchall()
    return [Response(**dict(r)) for r in rows]
```

- [ ] **Step 3b: Append `update_response_scoring` to `ema_poc/repositories/responses.py`**

```python
def update_response_scoring(
    conn: sqlite3.Connection,
    response_id: str,
    *,
    sentiment_score: float | None,
    competitive_position,
    alert_triggered: bool,
) -> None:
    """Update ONLY the derived/denormalized scoring columns on a response
    (FR-302). The authoritative versioned scoring record lives in the scores
    table (FR-304); these columns are a cache of the latest score so the Phase 4
    sentiment/alert filters work. Captured content is never modified."""
    cp = (
        competitive_position.value
        if hasattr(competitive_position, "value")
        else competitive_position
    )
    conn.execute(
        "UPDATE responses SET sentiment_score = ?, competitive_position = ?, "
        "alert_triggered = ? WHERE response_id = ?",
        (sentiment_score, cp, int(alert_triggered), response_id),
    )
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/repositories/test_scores.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/repositories/scores.py ema_poc/repositories/responses.py tests/repositories/test_scores.py
git commit -m "feat: scores repository + response derived-field update"
```

---

### Task 3: Alert rule + alerts repository

**Files:**
- Create: `ema_poc/scoring/alerts.py` (`evaluate_alert`)
- Create: `ema_poc/repositories/alerts.py` (`save_alert`, `list_alerts`)
- Test: `tests/scoring/test_alert_rule.py`
- Test: `tests/repositories/test_alerts.py`

- [ ] **Step 1: Write the failing tests**

`tests/scoring/test_alert_rule.py`:
```python
from ema_poc.scoring.alerts import evaluate_alert
from ema_poc.scoring.scorer import ScoreResult

ABBVIE = ["Skyrizi", "Rinvoq"]
COMPETITORS = ["Humira", "Stelara"]


def _score(sentiment=0.5, position="AMONG_OPTIONS", mentions=None):
    return ScoreResult(
        sentiment_score=sentiment, competitive_position=position,
        brand_mentions=mentions or [], key_claims=[], scoring_rationale="r",
    )


def test_no_alert_for_positive_neutral():
    assert evaluate_alert(_score(sentiment=0.4), abbvie_brands=ABBVIE,
                          competitor_brands=COMPETITORS) is None


def test_alert_on_low_sentiment():
    assert evaluate_alert(_score(sentiment=-0.5), abbvie_brands=ABBVIE,
                          competitor_brands=COMPETITORS) == "SENTIMENT_BELOW_THRESHOLD"


def test_alert_on_not_recommended_position():
    reason = evaluate_alert(_score(sentiment=0.2, position="NOT_RECOMMENDED"),
                            abbvie_brands=ABBVIE, competitor_brands=COMPETITORS)
    assert reason == "COMPETITIVE_POSITION_NOT_RECOMMENDED"


def test_alert_on_competitor_favored():
    # competitor mentioned + AbbVie sentiment non-positive (POC proxy)
    reason = evaluate_alert(
        _score(sentiment=-0.1, position="AMONG_OPTIONS", mentions=["Skyrizi", "Humira"]),
        abbvie_brands=ABBVIE, competitor_brands=COMPETITORS,
    )
    assert reason == "COMPETITOR_FAVORED"


def test_no_competitor_favored_when_sentiment_positive():
    assert evaluate_alert(
        _score(sentiment=0.3, mentions=["Skyrizi", "Humira"]),
        abbvie_brands=ABBVIE, competitor_brands=COMPETITORS,
    ) is None
```

`tests/repositories/test_alerts.py`:
```python
from ema_poc.db import connect, init_schema
from ema_poc.models import Alert
from ema_poc.repositories.alerts import list_alerts, save_alert

NOW = "2026-06-13T02:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def test_save_and_list_alerts(tmp_path):
    conn = _conn(tmp_path)
    save_alert(conn, Alert(alert_id="al-1", score_id="s-1",
                           reason="SENTIMENT_BELOW_THRESHOLD", created_at=NOW))
    save_alert(conn, Alert(alert_id="al-2", score_id="s-2",
                           reason="COMPETITIVE_POSITION_NOT_RECOMMENDED", created_at=NOW))
    alerts = list_alerts(conn)
    assert [a.alert_id for a in alerts] == ["al-1", "al-2"]
    assert alerts[0].reason == "SENTIMENT_BELOW_THRESHOLD"
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/scoring/test_alert_rule.py tests/repositories/test_alerts.py -v`
Expected: FAIL with `ModuleNotFoundError` for `ema_poc.scoring.alerts` / `ema_poc.repositories.alerts`.

- [ ] **Step 3a: Write `ema_poc/scoring/alerts.py`**

```python
"""Threshold-based alert rule over a ScoreResult (FR-405).

Brand lists come from config (SE-007). Returns an alert reason string or None.
The competitor-favored rule is a POC proxy for FR-405's "competitor with
materially higher sentiment than the AbbVie therapy": since the score carries a
single AbbVie-directed sentiment, we flag when a known competitor is mentioned
AND the AbbVie sentiment is non-positive."""

from __future__ import annotations

from ema_poc.scoring.scorer import ScoreResult

SENTIMENT_THRESHOLD = -0.3


def evaluate_alert(
    result: ScoreResult, *, abbvie_brands, competitor_brands
) -> str | None:
    if result.sentiment_score < SENTIMENT_THRESHOLD:
        return "SENTIMENT_BELOW_THRESHOLD"
    if result.competitive_position == "NOT_RECOMMENDED":
        return "COMPETITIVE_POSITION_NOT_RECOMMENDED"
    mentions = [m.lower() for m in result.brand_mentions]
    competitor_mentioned = any(
        comp.lower() in mention
        for comp in competitor_brands
        for mention in mentions
    )
    if competitor_mentioned and result.sentiment_score < 0:
        return "COMPETITOR_FAVORED"
    return None
```

- [ ] **Step 3b: Write `ema_poc/repositories/alerts.py`**

```python
"""Alerts repository — triggered-alert records linked to a scoring record (FR-405)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ema_poc.models import Alert


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def save_alert(conn: sqlite3.Connection, alert: Alert) -> None:
    conn.execute(
        "INSERT INTO alerts (alert_id, score_id, reason, created_at) "
        "VALUES (?, ?, ?, ?)",
        (alert.alert_id, alert.score_id, alert.reason, _iso(alert.created_at)),
    )
    conn.commit()


def list_alerts(conn: sqlite3.Connection) -> list[Alert]:
    rows = conn.execute(
        "SELECT * FROM alerts ORDER BY created_at ASC, alert_id ASC"
    ).fetchall()
    return [Alert(**dict(r)) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/scoring/test_alert_rule.py tests/repositories/test_alerts.py -v`
Expected: PASS (5 + 1 = 6 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/scoring/alerts.py ema_poc/repositories/alerts.py tests/scoring/test_alert_rule.py tests/repositories/test_alerts.py
git commit -m "feat: alert rule + alerts repository"
```

---

### Task 4: Scoring pipeline (score → version → alert → denormalize)

**Files:**
- Create: `ema_poc/scoring/pipeline.py`
- Test: `tests/scoring/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

`tests/scoring/test_pipeline.py`:
```python
from ema_poc.config import AppConfig, BrandConfig, Settings
from ema_poc.db import connect, init_schema
from ema_poc.models import Response
from ema_poc.repositories.alerts import list_alerts
from ema_poc.repositories.responses import query_responses, save_response
from ema_poc.repositories.runs import create_run
from ema_poc.repositories.scores import latest_score
from ema_poc.scoring.pipeline import score_pending
from ema_poc.scoring.scorer import ScoreResult

NOW = "2026-06-13T02:00:00+00:00"


def _config():
    return AppConfig(
        settings=Settings(scoring_model="claude-opus-4-8"),
        brands=BrandConfig(abbvie_brands=["Skyrizi"], competitor_brands=["Humira"]),
        targets=[],
    )


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=NOW)
    return conn


def _resp(conn, rid, text, *, status="SUCCESS", brand="Skyrizi"):
    save_response(conn, Response(
        response_id=rid, run_id="r1", timestamp_utc=NOW, llm_name="GPT-4o",
        llm_model_version="m", persona="Provider", question_id="Q1",
        question_text="q", brand_focus=brand, domain="Safety", response_text=text,
        response_tokens=1, finish_reason="stop", status=status, created_at=NOW,
    ))


def _ids():
    n = {"i": 0}

    def f():
        n["i"] += 1
        return f"id-{n['i']}"

    return f


# A fake scorer keyed by response_text so we control each score deterministically.
def _fake_scorer(scores_by_text):
    def scorer(client, *, response_text, brand_focus, abbvie_brands,
               competitor_brands, model="claude-opus-4-8"):
        return scores_by_text[response_text]

    return scorer


def test_score_pending_scores_persists_alerts_and_denormalizes(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "ok", "X is first-line and excellent.")
    _resp(conn, "bad", "X is not recommended; use Humira.")
    _resp(conn, "skipme", "failed text", status="FAILED")  # non-success: not scored

    scorer = _fake_scorer({
        "X is first-line and excellent.": ScoreResult(
            sentiment_score=0.8, competitive_position="FIRST_LINE_RECOMMENDED",
            brand_mentions=["Skyrizi"], key_claims=["effective"], scoring_rationale="positive",
        ),
        "X is not recommended; use Humira.": ScoreResult(
            sentiment_score=-0.6, competitive_position="NOT_RECOMMENDED",
            brand_mentions=["Skyrizi", "Humira"], key_claims=["avoid"], scoring_rationale="negative",
        ),
    })

    summary = score_pending(
        conn, client=object(), config=_config(), scorer=scorer,
        id_factory=_ids(), now_factory=lambda: NOW,
    )
    assert summary.scored == 2
    assert summary.alerts_raised == 1  # only the negative one

    # versioned scores persisted
    assert latest_score(conn, "ok").sentiment_score == 0.8
    assert latest_score(conn, "bad").competitive_position.value == "NOT_RECOMMENDED"
    assert latest_score(conn, "skipme") is None  # FAILED not scored

    # response derived columns updated (so Phase 4 filters work)
    alerted = [r.response_id for r in query_responses(conn, alert_triggered=True)]
    assert alerted == ["bad"]
    neg = [r.response_id for r in query_responses(conn, sentiment_max=-0.3)]
    assert neg == ["bad"]

    # one alert row
    alerts = list_alerts(conn)
    assert len(alerts) == 1
    assert alerts[0].reason == "SENTIMENT_BELOW_THRESHOLD"

    conn.close()


def test_score_pending_is_idempotent_on_second_run(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "ok", "neutral text")
    scorer = _fake_scorer({"neutral text": ScoreResult(
        sentiment_score=0.1, competitive_position="AMONG_OPTIONS",
        brand_mentions=[], key_claims=[], scoring_rationale="r",
    )})
    cfg = _config()
    s1 = score_pending(conn, client=object(), config=cfg, scorer=scorer,
                       id_factory=_ids(), now_factory=lambda: NOW)
    s2 = score_pending(conn, client=object(), config=cfg, scorer=scorer,
                       id_factory=_ids(), now_factory=lambda: NOW)
    assert s1.scored == 1
    assert s2.scored == 0  # already scored -> nothing pending
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/scoring/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.scoring.pipeline'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/scoring/pipeline.py`:
```python
"""Scoring pass orchestration (FR-401, FR-405, FR-406).

For each unscored SUCCESS response: score via Claude, persist a versioned Score,
update the response's derived columns, and raise+persist an alert if warranted.
The scorer and Anthropic client are injected so this runs against a fake in
tests (no network)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from ema_poc.audit import record_event
from ema_poc.config import AppConfig
from ema_poc.models import Alert, Score
from ema_poc.repositories.alerts import save_alert
from ema_poc.repositories.responses import update_response_scoring
from ema_poc.repositories.scores import (
    next_score_version,
    save_score,
    unscored_success_responses,
)
from ema_poc.scoring.alerts import evaluate_alert
from ema_poc.scoring.scorer import score_response


@dataclass
class ScoringSummary:
    scored: int
    alerts_raised: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def score_pending(
    conn,
    *,
    client,
    config: AppConfig,
    scorer=score_response,
    model: str | None = None,
    id_factory=lambda: uuid4().hex,
    now_factory=_now_iso,
) -> ScoringSummary:
    model = model or config.settings.scoring_model
    abbvie = config.brands.abbvie_brands
    competitors = config.brands.competitor_brands

    scored = 0
    alerts_raised = 0
    for response in unscored_success_responses(conn):
        result = scorer(
            client,
            response_text=response.response_text,
            brand_focus=response.brand_focus,
            abbvie_brands=abbvie,
            competitor_brands=competitors,
            model=model,
        )
        version = next_score_version(conn, response.response_id)
        score = Score(
            score_id=id_factory(),
            response_id=response.response_id,
            version=version,
            sentiment_score=result.sentiment_score,
            competitive_position=result.competitive_position,
            brand_mentions=result.brand_mentions,
            key_claims=result.key_claims,
            scoring_rationale=result.scoring_rationale,
            scoring_model=model,
            created_at=now_factory(),
        )
        save_score(conn, score)

        reason = evaluate_alert(
            result, abbvie_brands=abbvie, competitor_brands=competitors
        )
        update_response_scoring(
            conn,
            response.response_id,
            sentiment_score=result.sentiment_score,
            competitive_position=result.competitive_position,
            alert_triggered=reason is not None,
        )
        if reason is not None:
            save_alert(conn, Alert(
                alert_id=id_factory(), score_id=score.score_id,
                reason=reason, created_at=now_factory(),
            ))
            alerts_raised += 1

        record_event(
            conn,
            event_type="SCORING",
            role="ORCHESTRATOR",
            question_id=response.question_id,
            llm_target=response.llm_name,
            detail=result.competitive_position,
        )
        scored += 1

    return ScoringSummary(scored=scored, alerts_raised=alerts_raised)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/scoring/test_pipeline.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/scoring/pipeline.py tests/scoring/test_pipeline.py
git commit -m "feat: scoring pipeline (score, version, alert, denormalize)"
```

---

### Task 5: Scoring & alerting integration test

**Files:**
- Test: `tests/scoring/test_scoring_integration.py`

- [ ] **Step 1: Write the integration test**

`tests/scoring/test_scoring_integration.py`:
```python
"""End-to-end: a run's responses (positive / negative / blocked) flow through
the scoring pass against a fake Claude scorer, producing versioned scores,
denormalized response columns, and alerts; re-scoring adds a new version."""

from ema_poc.config import AppConfig, BrandConfig, Settings
from ema_poc.db import connect, init_schema
from ema_poc.models import Response
from ema_poc.repositories.alerts import list_alerts
from ema_poc.repositories.responses import query_responses, save_response
from ema_poc.repositories.runs import create_run
from ema_poc.repositories.scores import latest_score, next_score_version
from ema_poc.scoring.pipeline import score_pending
from ema_poc.scoring.scorer import ScoreResult

NOW = "2026-06-13T02:00:00+00:00"


def _config():
    return AppConfig(
        settings=Settings(scoring_model="claude-opus-4-8"),
        brands=BrandConfig(abbvie_brands=["Skyrizi"], competitor_brands=["Humira"]),
        targets=[],
    )


def _ids():
    n = {"i": 0}

    def f():
        n["i"] += 1
        return f"id-{n['i']}"

    return f


def _resp(conn, rid, text, status="SUCCESS"):
    save_response(conn, Response(
        response_id=rid, run_id="r1", timestamp_utc=NOW, llm_name="GPT-4o",
        llm_model_version="m", persona="Provider", question_id="Q1",
        question_text="q", brand_focus="Skyrizi", domain="Safety",
        response_text=text, response_tokens=1, finish_reason="stop",
        status=status, created_at=NOW,
    ))


def test_scoring_pass_end_to_end_with_rescore(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=NOW)
    _resp(conn, "pos", "Skyrizi is first-line and well tolerated.")
    _resp(conn, "neg", "Skyrizi is not recommended.")
    _resp(conn, "blk", "", status="BLOCKED")  # not SUCCESS -> never scored

    scores = {
        "Skyrizi is first-line and well tolerated.": ScoreResult(
            sentiment_score=0.7, competitive_position="FIRST_LINE_RECOMMENDED",
            brand_mentions=["Skyrizi"], key_claims=["tolerated"], scoring_rationale="pos",
        ),
        "Skyrizi is not recommended.": ScoreResult(
            sentiment_score=-0.6, competitive_position="NOT_RECOMMENDED",
            brand_mentions=["Skyrizi"], key_claims=["avoid"], scoring_rationale="neg",
        ),
    }

    def scorer(client, *, response_text, **kw):
        return scores[response_text]

    summary = score_pending(conn, client=object(), config=_config(), scorer=scorer,
                            id_factory=_ids(), now_factory=lambda: NOW)
    assert summary.scored == 2
    assert summary.alerts_raised == 1

    # denormalized response columns drive the Phase 4 filters
    assert {r.response_id for r in query_responses(conn, alert_triggered=True)} == {"neg"}
    positives = [r.response_id for r in query_responses(conn, sentiment_min=0.5)]
    assert positives == ["pos"]
    assert latest_score(conn, "blk") is None

    # one alert, on the negative response
    alerts = list_alerts(conn)
    assert len(alerts) == 1
    assert alerts[0].reason in {"SENTIMENT_BELOW_THRESHOLD", "COMPETITIVE_POSITION_NOT_RECOMMENDED"}

    # re-score: a corrected score for "neg" -> new version (FR-407), original kept
    rescore = {"Skyrizi is not recommended.": ScoreResult(
        sentiment_score=0.0, competitive_position="AMONG_OPTIONS",
        brand_mentions=["Skyrizi"], key_claims=["reassessed"], scoring_rationale="fix",
    )}

    # force a single response back to "unscored" is not how it works; instead
    # call the scorer-backed save path directly via next_score_version semantics:
    from ema_poc.repositories.scores import save_score
    from ema_poc.models import Score
    v = next_score_version(conn, "neg")
    save_score(conn, Score(
        score_id="rescore-1", response_id="neg", version=v,
        sentiment_score=0.0, competitive_position="AMONG_OPTIONS",
        brand_mentions=["Skyrizi"], key_claims=["reassessed"],
        scoring_rationale="fix", scoring_model="claude-opus-4-8", created_at=NOW,
    ))
    assert latest_score(conn, "neg").version == v
    assert latest_score(conn, "neg").sentiment_score == 0.0  # newest version wins
    assert v >= 2  # original version 1 preserved

    conn.close()
```

- [ ] **Step 2: Run the integration test**

Run: `. .venv/bin/activate && pytest tests/scoring/test_scoring_integration.py -v`
Expected: PASS (1 passed). If it fails, the failure points at a real wiring gap — fix the referenced module, do not weaken the test.

- [ ] **Step 3: Run the whole suite with coverage**

Run: `. .venv/bin/activate && pytest -q --cov` and `. .venv/bin/activate && pytest -q -W error::ResourceWarning`.
Expected: all green; no ResourceWarning. Note coverage for `ema_poc/scoring/*` and `ema_poc/repositories/scores.py`.

- [ ] **Step 4: Commit**

```bash
git add tests/scoring/test_scoring_integration.py
git commit -m "test: scoring & alerting end-to-end with re-score"
```

---

## Self-Review

**Spec coverage (Phase 5 scope):**
- FR-401 scoring pass populates sentiment_score + competitive_position → `score_pending` + `update_response_scoring` → Tasks 2, 4.
- FR-402 sentiment −1.0..+1.0 via Claude structured output → `ScoreResult.sentiment_score` (bounded) + `score_response` → Task 1.
- FR-403 competitive_position enum → `ScoreResult.competitive_position` Literal (matches `CompetitivePosition`) → Task 1.
- FR-404 structured JSON (sentiment, position, brand_mentions, key_claims≤5, rationale) via `messages.parse` → Task 1.
- FR-405 alert logic (sentiment<-0.3 OR NOT_RECOMMENDED OR competitor-favored) with config brand lists → `evaluate_alert` → Task 3.
- FR-304/407 versioned, append-only scoring records; re-scoring adds a version → `scores` repo + `next_score_version` → Tasks 2, 5.
- FR-406 scoring runs automatically as a pass → `score_pending` over unscored responses → Task 4 (the scheduler invokes it in Phase 6).
- BR-005/006 baseline sentiment + competitive positioning scored per response → the whole pipeline.

**Design note (flag for stakeholders):**
- FR-405's competitor-favored condition is implemented as a POC **proxy** (competitor mentioned + AbbVie sentiment non-positive), because `ScoreResult` carries a single AbbVie-directed sentiment per FR-404 (no per-competitor sentiment). Documented in `scoring/alerts.py`.
- FR-302/FR-304 reconciliation: `scores` table is authoritative/versioned; the response's three derived columns are a cache updated by the pass (content untouched). Documented in `update_response_scoring`.

Deferred (correctly out of scope): FR-408 human-override row (the `scores` table already has `human_override`/`override_rationale` columns and the versioned model supports it — a UI/CLI override action belongs to a later phase; the *data model* for it exists); FR-406 "within 5 minutes" timing is a scheduling concern (Phase 6); the dashboard surfacing of scores/alerts (Phase 7).

**Placeholder scan:** No "TBD"/"add error handling"/"similar to" placeholders — every code and test step is complete.

**Type/name consistency:** `ScoreResult` (Task 1) is used by `evaluate_alert` (Task 3) and the pipeline (Task 4). `score_response(client, *, response_text, brand_focus, abbvie_brands, competitor_brands, model)` signature matches the fake scorer in Tasks 4–5. `save_score`/`latest_score`/`next_score_version`/`unscored_success_responses` (Task 2) used in Tasks 4–5. `update_response_scoring` (Task 2) used in Task 4. `save_alert`/`list_alerts` (Task 3) used in Tasks 4–5. `Score`/`Alert`/`CompetitivePosition` models and the `scores`/`alerts` schema columns are from Phase 1. The pipeline's `score_pending(conn, *, client, config, scorer, model, id_factory, now_factory)` signature matches its tests.
