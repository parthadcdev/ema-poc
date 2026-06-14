# Scoring Confidence + Citation Dimensions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `confidence_level` and `citation_quality` as two new scored dimensions flowing from `ScoreResult` → `Score` model → `scores` DB table → read-back.

**Architecture:** The new fields are added to `ScoreResult` (required, Literal-typed), propagated to `Score` (optional str, backward-compatible), stored in two new nullable TEXT columns in the `scores` table, and passed through in `pipeline.py`. All existing fake `ScoreResult` instances in tests must gain the two new fields; the `FakeScoreResult` duck-type in `test_service.py` must gain them too.

**Tech Stack:** Python 3.12, Pydantic v2, SQLite (via `sqlite3`), pytest

---

## File Map

| File | Action |
|------|--------|
| `ema_poc/scoring/scorer.py` | Add two fields to `ScoreResult`; extend `_build_prompt` closing sentence |
| `ema_poc/models.py` | Add two optional fields to `Score` |
| `ema_poc/db.py` | Add two nullable TEXT columns to `scores` table DDL |
| `ema_poc/repositories/scores.py` | Add columns to INSERT and read them back in `_score_from_row` |
| `ema_poc/scoring/pipeline.py` | Pass new fields when constructing `Score(...)` |
| `tests/scoring/test_scorer.py` | New tests for fields + prompt content; update existing fakes |
| `tests/repositories/test_scores.py` | Extend round-trip test to cover new columns |
| `tests/scoring/test_pipeline.py` | Update fake `ScoreResult` instances; assert new fields propagate |
| `tests/scoring/test_scoring_integration.py` | Update all fake `ScoreResult` instances |
| `tests/scoring/test_alert_rule.py` | Update `_score()` helper to include new fields |
| `tests/test_cli_integration.py` | Update `_fake_scorer` return value |
| `tests/dashboard/test_dashboard_integration.py` | Update `_scorer` return value |
| `tests/playground/test_service.py` | Add new attributes to `FakeScoreResult` |

---

### Task 1: Add fields to `ScoreResult` and extend `_build_prompt`

**Files:**
- Modify: `ema_poc/scoring/scorer.py`

- [ ] **Step 1: Write the failing test first**

In `tests/scoring/test_scorer.py`, add these two test functions **before** implementing anything:

```python
def test_score_result_accepts_new_dimensions():
    """ScoreResult must accept (and require) confidence_level and citation_quality."""
    sr = ScoreResult(
        sentiment_score=0.3,
        competitive_position="AMONG_OPTIONS",
        brand_mentions=["Skyrizi"],
        key_claims=["effective"],
        scoring_rationale="ok",
        confidence_level="ASSERTIVE",
        citation_quality="HIGH",
    )
    assert sr.confidence_level == "ASSERTIVE"
    assert sr.citation_quality == "HIGH"


def test_build_prompt_mentions_confidence_and_citation():
    """_build_prompt must instruct the scorer on both new dimensions."""
    prompt = _build_prompt(
        response_text="Some pharma text.",
        brand_focus="Skyrizi",
        abbvie_brands=["Skyrizi"],
        competitor_brands=["Humira"],
    )
    assert "confidence" in prompt.lower()
    assert "citation" in prompt.lower()
```

- [ ] **Step 2: Run the failing tests**

```bash
cd /Users/partha/Work/ema-poc && source .venv/bin/activate && python -m pytest tests/scoring/test_scorer.py::test_score_result_accepts_new_dimensions tests/scoring/test_scorer.py::test_build_prompt_mentions_confidence_and_citation -v
```

Expected: both FAIL — `ScoreResult` rejects unknown fields / fields missing.

- [ ] **Step 3: Implement — update `ScoreResult` and `_build_prompt`**

In `ema_poc/scoring/scorer.py`, update `ScoreResult` to:

```python
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
    confidence_level: Literal["HEDGED", "MIXED", "ASSERTIVE"]
    citation_quality: Literal["NONE", "LOW", "MODERATE", "HIGH"]
```

Update `_build_prompt` — replace the closing sentence (starting "Score brand sentiment...") with:

```python
        "Score brand sentiment toward the AbbVie therapy from -1.0 (strongly "
        "negative) to +1.0 (strongly positive). Classify the AbbVie therapy's "
        "competitive positioning. List the brand names mentioned, up to 5 key "
        "claims about the therapy, and a brief scoring rationale. "
        "Also assess confidence_level (how confidently the response asserts claims "
        "about the AbbVie therapy: HEDGED = claims heavily qualified with 'may', "
        "'might', 'could'; MIXED = mix of qualified and definitive claims; "
        "ASSERTIVE = definitive statements such as 'is first-line') and "
        "citation_quality (quality of any sources cited: NONE = no sources cited; "
        "LOW = forums, blogs, or marketing materials; MODERATE = general medical "
        "or reference sites; HIGH = peer-reviewed literature, clinical guidelines, "
        "or regulatory labels)."
```

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
cd /Users/partha/Work/ema-poc && source .venv/bin/activate && python -m pytest tests/scoring/test_scorer.py::test_score_result_accepts_new_dimensions tests/scoring/test_scorer.py::test_build_prompt_mentions_confidence_and_citation -v
```

Expected: both PASS.

- [ ] **Step 5: Update ALL existing `ScoreResult` fakes in the test suite**

The two new fields are **required** on `ScoreResult`. Every fake that omits them will fail. Update each location listed below — add `confidence_level="MIXED", citation_quality="MODERATE"` (or any valid values) to every `ScoreResult(...)` call:

**`tests/scoring/test_scorer.py`** — 5 locations:

```python
# test_score_result_validates_sentiment_bounds — line ~23
ScoreResult(
    sentiment_score=0.5, competitive_position="AMONG_OPTIONS",
    brand_mentions=["Skyrizi"], key_claims=["claim"], scoring_rationale="r",
    confidence_level="MIXED", citation_quality="MODERATE",
)
# the ValidationError case on line ~28
ScoreResult(
    sentiment_score=1.5, competitive_position="AMONG_OPTIONS",
    brand_mentions=[], key_claims=[], scoring_rationale="r",
    confidence_level="MIXED", citation_quality="MODERATE",
)
# test_score_result_rejects_bad_competitive_position — line ~36
ScoreResult(
    sentiment_score=0.0, competitive_position="MAYBE",
    brand_mentions=[], key_claims=[], scoring_rationale="r",
    confidence_level="MIXED", citation_quality="MODERATE",
)
# test_score_response_returns_parsed_output — line ~43
expected = ScoreResult(
    sentiment_score=-0.4, competitive_position="SECOND_LINE",
    brand_mentions=["Skyrizi", "Humira"], key_claims=["c1"], scoring_rationale="why",
    confidence_level="ASSERTIVE", citation_quality="HIGH",
)
# test_score_response_call_shape_opus48_rules — line ~56
client = _FakeClient(ScoreResult(
    sentiment_score=0.0, competitive_position="NOT_MENTIONED",
    brand_mentions=[], key_claims=[], scoring_rationale="r",
    confidence_level="HEDGED", citation_quality="NONE",
))
```

**`tests/scoring/test_alert_rule.py`** — `_score()` helper:

```python
def _score(sentiment=0.5, position="AMONG_OPTIONS", mentions=None):
    return ScoreResult(
        sentiment_score=sentiment, competitive_position=position,
        brand_mentions=mentions or [], key_claims=[], scoring_rationale="r",
        confidence_level="MIXED", citation_quality="MODERATE",
    )
```

**`tests/scoring/test_pipeline.py`** — 3 locations inside `_fake_scorer` dict:

```python
"X is first-line and excellent.": ScoreResult(
    sentiment_score=0.8, competitive_position="FIRST_LINE_RECOMMENDED",
    brand_mentions=["Skyrizi"], key_claims=["effective"], scoring_rationale="positive",
    confidence_level="ASSERTIVE", citation_quality="NONE",
),
"X is not recommended; use Humira.": ScoreResult(
    sentiment_score=-0.6, competitive_position="NOT_RECOMMENDED",
    brand_mentions=["Skyrizi", "Humira"], key_claims=["avoid"], scoring_rationale="negative",
    confidence_level="HEDGED", citation_quality="LOW",
),
# idempotency test
ScoreResult(
    sentiment_score=0.1, competitive_position="AMONG_OPTIONS",
    brand_mentions=[], key_claims=[], scoring_rationale="r",
    confidence_level="MIXED", citation_quality="NONE",
)
```

**`tests/scoring/test_scoring_integration.py`** — 2 locations:

```python
"Skyrizi is first-line and well tolerated.": ScoreResult(
    sentiment_score=0.7, competitive_position="FIRST_LINE_RECOMMENDED",
    brand_mentions=["Skyrizi"], key_claims=["tolerated"], scoring_rationale="pos",
    confidence_level="ASSERTIVE", citation_quality="NONE",
),
"Skyrizi is not recommended.": ScoreResult(
    sentiment_score=-0.6, competitive_position="NOT_RECOMMENDED",
    brand_mentions=["Skyrizi"], key_claims=["avoid"], scoring_rationale="neg",
    confidence_level="HEDGED", citation_quality="NONE",
),
```

**`tests/test_cli_integration.py`** — `_fake_scorer` function:

```python
def _fake_scorer(client, *, response_text, **kw):
    return ScoreResult(
        sentiment_score=0.6, competitive_position="FIRST_LINE_RECOMMENDED",
        brand_mentions=["Skyrizi"], key_claims=["effective"], scoring_rationale="r",
        confidence_level="ASSERTIVE", citation_quality="NONE",
    )
```

**`tests/dashboard/test_dashboard_integration.py`** — `_scorer` function:

```python
def _scorer(client, *, response_text, **kw):
    return ScoreResult(
        sentiment_score=-0.6, competitive_position="NOT_RECOMMENDED",
        brand_mentions=["Skyrizi"], key_claims=["avoid"], scoring_rationale="negative tone",
        confidence_level="HEDGED", citation_quality="LOW",
    )
```

**`tests/playground/test_service.py`** — `FakeScoreResult` class (duck-type, NOT a real `ScoreResult`, just needs the attributes):

```python
class FakeScoreResult:
    def __init__(self):
        self.sentiment_score = 0.5
        self.competitive_position = "AMONG_OPTIONS"
        self.brand_mentions = ["Skyrizi"]
        self.key_claims = []
        self.scoring_rationale = "because"
        self.confidence_level = "MIXED"
        self.citation_quality = "MODERATE"
```

- [ ] **Step 6: Run the full scorer test file to confirm it's green**

```bash
cd /Users/partha/Work/ema-poc && source .venv/bin/activate && python -m pytest tests/scoring/test_scorer.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit Task 1**

```bash
cd /Users/partha/Work/ema-poc && git add ema_poc/scoring/scorer.py tests/scoring/test_scorer.py tests/scoring/test_alert_rule.py tests/scoring/test_pipeline.py tests/scoring/test_scoring_integration.py tests/test_cli_integration.py tests/dashboard/test_dashboard_integration.py tests/playground/test_service.py
git commit -m "feat: add confidence_level + citation_quality to ScoreResult and update fakes"
```

---

### Task 2: Add optional fields to `Score` model (`models.py`)

**Files:**
- Modify: `ema_poc/models.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_models.py` (already exists), add a test that constructs a `Score` with both new fields and also without them:

Open `tests/test_models.py` and add:

```python
from ema_poc.models import Score, CompetitivePosition


def test_score_accepts_new_optional_dimensions():
    """Score must accept confidence_level and citation_quality as optional str."""
    s = Score(
        score_id="s1", response_id="r1",
        sentiment_score=0.5, competitive_position=CompetitivePosition.AMONG_OPTIONS,
        scoring_model="claude-opus-4-8",
        confidence_level="ASSERTIVE", citation_quality="HIGH",
    )
    assert s.confidence_level == "ASSERTIVE"
    assert s.citation_quality == "HIGH"


def test_score_new_fields_default_to_none():
    """Existing Score construction without new fields must still work."""
    s = Score(
        score_id="s1", response_id="r1",
        sentiment_score=0.5, competitive_position=CompetitivePosition.AMONG_OPTIONS,
        scoring_model="claude-opus-4-8",
    )
    assert s.confidence_level is None
    assert s.citation_quality is None
```

- [ ] **Step 2: Run the failing tests**

```bash
cd /Users/partha/Work/ema-poc && source .venv/bin/activate && python -m pytest tests/test_models.py::test_score_accepts_new_optional_dimensions tests/test_models.py::test_score_new_fields_default_to_none -v
```

Expected: FAIL — `Score` has no such fields.

- [ ] **Step 3: Implement — update `Score` model**

In `ema_poc/models.py`, add two fields to `Score` after `scoring_rationale`:

```python
class Score(BaseModel):
    score_id: str
    response_id: str
    version: int = 1
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    competitive_position: CompetitivePosition
    brand_mentions: list[str] = Field(default_factory=list)
    key_claims: list[str] = Field(default_factory=list)
    scoring_rationale: str | None = None
    confidence_level: str | None = None
    citation_quality: str | None = None
    scoring_model: str
    human_override: bool = False
    override_rationale: str | None = None
    created_at: datetime | None = None
```

- [ ] **Step 4: Run the new tests**

```bash
cd /Users/partha/Work/ema-poc && source .venv/bin/activate && python -m pytest tests/test_models.py::test_score_accepts_new_optional_dimensions tests/test_models.py::test_score_new_fields_default_to_none -v
```

Expected: both PASS.

- [ ] **Step 5: Commit Task 2**

```bash
cd /Users/partha/Work/ema-poc && git add ema_poc/models.py tests/test_models.py
git commit -m "feat: add optional confidence_level + citation_quality to Score model"
```

---

### Task 3: Add nullable columns to `scores` table DDL (`db.py`)

**Files:**
- Modify: `ema_poc/db.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_db.py` (already exists), add:

```python
def test_scores_table_has_new_columns(tmp_path):
    """scores table must expose confidence_level and citation_quality TEXT columns."""
    from ema_poc.db import connect, init_schema
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(scores)")}
    assert "confidence_level" in cols
    assert "citation_quality" in cols
    conn.close()
```

- [ ] **Step 2: Run the failing test**

```bash
cd /Users/partha/Work/ema-poc && source .venv/bin/activate && python -m pytest tests/test_db.py::test_scores_table_has_new_columns -v
```

Expected: FAIL — columns not present.

- [ ] **Step 3: Implement — update `SCHEMA` in `db.py`**

In `ema_poc/db.py`, locate the `scores` table DDL. Add two nullable columns after `scoring_rationale`:

```sql
CREATE TABLE IF NOT EXISTS scores (
    score_id             TEXT PRIMARY KEY,
    response_id          TEXT NOT NULL,
    version              INTEGER NOT NULL DEFAULT 1,
    sentiment_score      REAL NOT NULL,
    competitive_position TEXT NOT NULL,
    brand_mentions       TEXT NOT NULL,
    key_claims           TEXT NOT NULL,
    scoring_rationale    TEXT,
    confidence_level     TEXT,
    citation_quality     TEXT,
    scoring_model        TEXT NOT NULL,
    human_override       INTEGER NOT NULL DEFAULT 0,
    override_rationale   TEXT,
    created_at           TEXT NOT NULL,
    FOREIGN KEY (response_id) REFERENCES responses(response_id)
);
```

- [ ] **Step 4: Run the new test**

```bash
cd /Users/partha/Work/ema-poc && source .venv/bin/activate && python -m pytest tests/test_db.py::test_scores_table_has_new_columns -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
cd /Users/partha/Work/ema-poc && git add ema_poc/db.py tests/test_db.py
git commit -m "feat: add confidence_level + citation_quality nullable columns to scores DDL"
```

---

### Task 4: Update `save_score` INSERT and `_score_from_row` read-back (`scores.py`)

**Files:**
- Modify: `ema_poc/repositories/scores.py`
- Test: `tests/repositories/test_scores.py`

- [ ] **Step 1: Write the failing test**

In `tests/repositories/test_scores.py`, add a new test that saves a `Score` with the new fields and reads them back:

```python
def test_save_and_latest_score_roundtrips_new_dimensions(tmp_path):
    """confidence_level and citation_quality must survive a save/read roundtrip."""
    conn = _conn(tmp_path)
    _resp(conn, "resp-x")
    score = Score(
        score_id="resp-x-s1", response_id="resp-x", version=1,
        sentiment_score=0.7, competitive_position="FIRST_LINE_RECOMMENDED",
        brand_mentions=["Skyrizi"], key_claims=["effective"],
        scoring_rationale="good", scoring_model="claude-opus-4-8",
        confidence_level="ASSERTIVE", citation_quality="HIGH",
        created_at=NOW,
    )
    save_score(conn, score)
    got = latest_score(conn, "resp-x")
    assert got.confidence_level == "ASSERTIVE"
    assert got.citation_quality == "HIGH"
    conn.close()


def test_save_score_with_null_new_dimensions(tmp_path):
    """Scores without confidence/citation (old rows) must read back as None."""
    conn = _conn(tmp_path)
    _resp(conn, "resp-y")
    score = _score("resp-y")  # uses existing helper which omits new fields
    save_score(conn, score)
    got = latest_score(conn, "resp-y")
    assert got.confidence_level is None
    assert got.citation_quality is None
    conn.close()
```

- [ ] **Step 2: Run the failing tests**

```bash
cd /Users/partha/Work/ema-poc && source .venv/bin/activate && python -m pytest tests/repositories/test_scores.py::test_save_and_latest_score_roundtrips_new_dimensions tests/repositories/test_scores.py::test_save_score_with_null_new_dimensions -v
```

Expected: FAIL — INSERT column list and `_score_from_row` don't know about the new columns yet.

- [ ] **Step 3: Implement — update `save_score` and `_score_from_row`**

In `ema_poc/repositories/scores.py`, update `save_score`:

```python
def save_score(conn: sqlite3.Connection, score: Score) -> None:
    conn.execute(
        """
        INSERT INTO scores (
            score_id, response_id, version, sentiment_score, competitive_position,
            brand_mentions, key_claims, scoring_rationale,
            confidence_level, citation_quality,
            scoring_model, human_override, override_rationale, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            score.confidence_level,
            score.citation_quality,
            score.scoring_model,
            int(score.human_override),
            score.override_rationale,
            _iso(score.created_at),
        ),
    )
    conn.commit()
```

The `_score_from_row` function uses `Score(**data)` with `dict(row)` — since SQLite rows now include `confidence_level` and `citation_quality` columns, and `Score` accepts them as optional fields, **no change is needed** to `_score_from_row`. SQLite will return `None` for NULL columns and `dict(row)` will pass them through to `Score(**data)`. Verify this is the case by confirming `_score_from_row` is:

```python
def _score_from_row(row: sqlite3.Row) -> Score:
    data = dict(row)
    data["brand_mentions"] = json.loads(data["brand_mentions"]) if data["brand_mentions"] else []
    data["key_claims"] = json.loads(data["key_claims"]) if data["key_claims"] else []
    data["human_override"] = bool(data["human_override"])
    return Score(**data)
```

No changes needed to `_score_from_row` — `dict(row)` will include `confidence_level` and `citation_quality` automatically from the new columns.

- [ ] **Step 4: Run the new tests**

```bash
cd /Users/partha/Work/ema-poc && source .venv/bin/activate && python -m pytest tests/repositories/test_scores.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit Task 4**

```bash
cd /Users/partha/Work/ema-poc && git add ema_poc/repositories/scores.py tests/repositories/test_scores.py
git commit -m "feat: persist and read back confidence_level + citation_quality in scores repo"
```

---

### Task 5: Thread new fields through `pipeline.py`

**Files:**
- Modify: `ema_poc/scoring/pipeline.py`

- [ ] **Step 1: Write the failing test**

In `tests/scoring/test_pipeline.py`, add an assertion to the existing `test_score_pending_scores_persists_alerts_and_denormalizes` test (or add a new test after it):

Add the following new test function to `tests/scoring/test_pipeline.py`:

```python
def test_score_pending_propagates_new_dimensions(tmp_path):
    """pipeline must carry confidence_level + citation_quality from scorer into persisted Score."""
    conn = _conn(tmp_path)
    _resp(conn, "resp-a", "Therapy may help some patients.")

    scorer = _fake_scorer({
        "Therapy may help some patients.": ScoreResult(
            sentiment_score=0.2, competitive_position="AMONG_OPTIONS",
            brand_mentions=["Skyrizi"], key_claims=["may help"],
            scoring_rationale="hedged",
            confidence_level="HEDGED", citation_quality="LOW",
        ),
    })

    score_pending(
        conn, client=object(), config=_config(), scorer=scorer,
        id_factory=_ids(), now_factory=lambda: NOW,
    )

    persisted = latest_score(conn, "resp-a")
    assert persisted.confidence_level == "HEDGED"
    assert persisted.citation_quality == "LOW"
    conn.close()
```

- [ ] **Step 2: Run the failing test**

```bash
cd /Users/partha/Work/ema-poc && source .venv/bin/activate && python -m pytest tests/scoring/test_pipeline.py::test_score_pending_propagates_new_dimensions -v
```

Expected: FAIL — `Score(...)` in `pipeline.py` doesn't pass the new fields yet.

- [ ] **Step 3: Implement — update `pipeline.py`**

In `ema_poc/scoring/pipeline.py`, update the `Score(...)` construction inside `score_pending`:

```python
        score = Score(
            score_id=id_factory(),
            response_id=response.response_id,
            version=version,
            sentiment_score=result.sentiment_score,
            competitive_position=result.competitive_position,
            brand_mentions=result.brand_mentions,
            key_claims=result.key_claims,
            scoring_rationale=result.scoring_rationale,
            confidence_level=result.confidence_level,
            citation_quality=result.citation_quality,
            scoring_model=model,
            created_at=now_factory(),
        )
```

- [ ] **Step 4: Run the new test**

```bash
cd /Users/partha/Work/ema-poc && source .venv/bin/activate && python -m pytest tests/scoring/test_pipeline.py::test_score_pending_propagates_new_dimensions -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
cd /Users/partha/Work/ema-poc && git add ema_poc/scoring/pipeline.py tests/scoring/test_pipeline.py
git commit -m "feat: thread confidence_level + citation_quality through scoring pipeline"
```

---

### Task 6: Run full suite and fix any remaining breakage

**Files:** (any failing test file)

- [ ] **Step 1: Run the full test suite**

```bash
cd /Users/partha/Work/ema-poc && source .venv/bin/activate && python -m pytest -q
```

Expected: all pass. If anything fails, the most likely cause is a `ScoreResult(...)` call somewhere that still lacks the two new required fields (run `grep -rn "ScoreResult(" tests/` to find any missed location).

- [ ] **Step 2: Fix any remaining fake ScoreResult calls (if needed)**

If tests fail with `ValidationError` about missing `confidence_level` or `citation_quality`, locate the offending constructor:

```bash
grep -rn "ScoreResult(" /Users/partha/Work/ema-poc/tests/
```

For each hit that lacks the new fields, add `confidence_level="MIXED", citation_quality="MODERATE"`.

- [ ] **Step 3: Verify the full suite is green**

```bash
cd /Users/partha/Work/ema-poc && source .venv/bin/activate && python -m pytest -q
```

Expected: all tests pass, 0 failures.

- [ ] **Step 4: Final commit (all changed files)**

```bash
cd /Users/partha/Work/ema-poc && git add ema_poc/scoring/scorer.py ema_poc/models.py ema_poc/db.py ema_poc/repositories/scores.py ema_poc/scoring/pipeline.py tests/
git commit -m "feat: add confidence_level + citation_quality scoring dimensions"
```

---

## Self-Review Checklist

### 1. Spec Coverage

| Requirement | Task |
|-------------|------|
| `confidence_level` Literal on `ScoreResult` (HEDGED/MIXED/ASSERTIVE) | Task 1 |
| `citation_quality` Literal on `ScoreResult` (NONE/LOW/MODERATE/HIGH) | Task 1 |
| `_build_prompt` instructs Claude on both dimensions with rubric | Task 1 |
| Optional `confidence_level: str \| None` on `Score` | Task 2 |
| Optional `citation_quality: str \| None` on `Score` | Task 2 |
| `scores` table gets `confidence_level TEXT` nullable column | Task 3 |
| `scores` table gets `citation_quality TEXT` nullable column | Task 3 |
| `save_score` INSERT includes new columns | Task 4 |
| `latest_score` reads back new columns (via `_score_from_row`) | Task 4 |
| `pipeline.py` passes `confidence_level` and `citation_quality` when building `Score` | Task 5 |
| All fake `ScoreResult` instances in tests updated | Task 1, Step 5 |
| `FakeScoreResult` in `test_service.py` updated | Task 1, Step 5 |
| New tests: `ScoreResult` fields + `_build_prompt` content | Task 1, Step 1 |
| New test: `Score` optional fields + default None | Task 2, Step 1 |
| New test: DB columns present | Task 3, Step 1 |
| New test: save/read round-trip for new fields | Task 4, Step 1 |
| New test: pipeline propagates new fields | Task 5, Step 1 |

### 2. Placeholder Scan

No TBDs, TODOs, or fill-in-later placeholders found. Every step includes exact code.

### 3. Type Consistency

- `ScoreResult.confidence_level` is `Literal["HEDGED", "MIXED", "ASSERTIVE"]` — matches values used in all test fakes.
- `ScoreResult.citation_quality` is `Literal["NONE", "LOW", "MODERATE", "HIGH"]` — matches values used in all test fakes.
- `Score.confidence_level` is `str | None` — accepts the string values stored by pipeline.
- `Score.citation_quality` is `str | None` — accepts the string values stored by pipeline.
- `result.confidence_level` accessed in pipeline — correct, `ScoreResult` has this field.
- `result.citation_quality` accessed in pipeline — correct, `ScoreResult` has this field.
- `score.confidence_level` and `score.citation_quality` in `save_score` — correct, `Score` has these fields.
