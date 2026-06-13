# Evidence Monitoring Agent — Response Repository Implementation Plan (Phase 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Response Repository read surface (FR-303, FR-305, FR-306, FR-307): query stored responses by any combination of filters with pagination, export query results to CSV and JSON, and detect change between the current and previous response for a given question/LLM pair (change detection, BR-004).

**Architecture:** Extends `ema_poc/repositories/responses.py` (which already has the write path + `completed_keys` from Phase 3B) with read/query/diff functions, plus a small `ema_poc/export.py` for CSV/JSON serialization. The write path stays immutable; this phase is read-only over the `responses` table. Filters compose into a single parameterized WHERE clause; ISO-8601 UTC timestamp strings compare lexicographically for date ranges.

**Tech Stack:** Python 3.11+, stdlib `sqlite3` + `csv` + `json` + `difflib`, Pydantic `Response` model (Phase 1). Built on Phases 1–3B (all merged to `develop`).

**Spec:** `docs/superpowers/specs/2026-06-13-evidence-monitoring-agent-poc-design.md` (§3, FR-3, BR-004).

**Conventions:**
- Filters accept either enum members or their string values (normalized via `.value`).
- Query results are `Response` model instances, ordered by `timestamp_utc, response_id` for stable pagination.
- Activate the venv with `. .venv/bin/activate` before pytest.

---

### Task 1: Queryable response read API with pagination

**Files:**
- Modify: `ema_poc/repositories/responses.py` (append `_response_filters`, `query_responses`, `count_responses`)
- Test: `tests/repositories/test_responses_query.py`

- [ ] **Step 1: Write the failing test**

`tests/repositories/test_responses_query.py`:
```python
from ema_poc.db import connect, init_schema
from ema_poc.models import Response
from ema_poc.repositories.responses import (
    count_responses,
    query_responses,
    save_response,
)
from ema_poc.repositories.runs import create_run

T1 = "2026-06-13T01:00:00+00:00"
T2 = "2026-06-13T02:00:00+00:00"
T3 = "2026-06-13T03:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=T1)
    return conn


def _save(
    conn,
    response_id,
    *,
    llm="GPT-4o",
    persona="Provider",
    ta="Immunology",
    brand="Skyrizi",
    domain="Safety",
    ts=T1,
    sentiment=None,
    alert=False,
    status="SUCCESS",
    text="ans",
    question_id="Q1",
):
    r = Response(
        response_id=response_id, run_id="r1", timestamp_utc=ts, llm_name=llm,
        llm_model_version="m", persona=persona, question_id=question_id,
        question_text="q", therapeutic_area=ta, brand_focus=brand, domain=domain,
        response_text=text, response_tokens=10, finish_reason="stop", status=status,
        sentiment_score=sentiment, alert_triggered=alert, created_at=ts,
    )
    save_response(conn, r)


def test_query_all_ordered_by_timestamp(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "a", ts=T2)
    _save(conn, "b", ts=T1)
    _save(conn, "c", ts=T3)
    ids = [r.response_id for r in query_responses(conn)]
    assert ids == ["b", "a", "c"]  # ascending by timestamp
    conn.close()


def test_filter_by_llm_persona_domain(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "a", llm="GPT-4o", persona="Provider", domain="Safety")
    _save(conn, "b", llm="Gemini", persona="Patient", domain="Efficacy")
    assert [r.response_id for r in query_responses(conn, llm="Gemini")] == ["b"]
    assert [r.response_id for r in query_responses(conn, persona="Provider")] == ["a"]
    assert [r.response_id for r in query_responses(conn, domain="Efficacy")] == ["b"]
    conn.close()


def test_filter_by_date_range(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "a", ts=T1)
    _save(conn, "b", ts=T2)
    _save(conn, "c", ts=T3)
    got = [r.response_id for r in query_responses(conn, date_from=T2, date_to=T3)]
    assert got == ["b", "c"]
    conn.close()


def test_filter_by_sentiment_range_and_alert(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "a", sentiment=-0.5, alert=True)
    _save(conn, "b", sentiment=0.2, alert=False)
    _save(conn, "c", sentiment=None, alert=False)
    neg = [r.response_id for r in query_responses(conn, sentiment_max=-0.3)]
    assert neg == ["a"]
    alerted = [r.response_id for r in query_responses(conn, alert_triggered=True)]
    assert alerted == ["a"]
    conn.close()


def test_filter_by_ta_brand_status(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "a", ta="Immunology", brand="Skyrizi", status="SUCCESS")
    _save(conn, "b", ta="Oncology", brand="Venclexta", status="BLOCKED")
    assert [r.response_id for r in query_responses(conn, therapeutic_area="Oncology")] == ["b"]
    assert [r.response_id for r in query_responses(conn, brand_focus="Skyrizi")] == ["a"]
    assert [r.response_id for r in query_responses(conn, status="BLOCKED")] == ["b"]
    conn.close()


def test_pagination_and_count(tmp_path):
    conn = _conn(tmp_path)
    for i, ts in enumerate([T1, T2, T3]):
        _save(conn, f"r{i}", ts=ts)
    assert count_responses(conn) == 3
    page = query_responses(conn, limit=2, offset=0)
    assert [r.response_id for r in page] == ["r0", "r1"]
    page2 = query_responses(conn, limit=2, offset=2)
    assert [r.response_id for r in page2] == ["r2"]
    assert count_responses(conn, llm="Gemini") == 0
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/repositories/test_responses_query.py -v`
Expected: FAIL with `ImportError: cannot import name 'query_responses'`.

- [ ] **Step 3: Append the implementation to `ema_poc/repositories/responses.py`**

```python
def _enum_value(x):
    return x.value if hasattr(x, "value") else x


def _response_filters(
    *,
    llm=None,
    persona=None,
    therapeutic_area: str | None = None,
    brand_focus: str | None = None,
    domain=None,
    date_from: str | None = None,
    date_to: str | None = None,
    sentiment_min: float | None = None,
    sentiment_max: float | None = None,
    alert_triggered: bool | None = None,
    status=None,
) -> tuple[str, list]:
    """Build a parameterized WHERE clause (FR-303). Returns (clause, params)
    where clause is '' or ' WHERE ...'."""
    where: list[str] = []
    params: list = []
    if llm is not None:
        where.append("llm_name = ?")
        params.append(llm)
    if persona is not None:
        where.append("persona = ?")
        params.append(_enum_value(persona))
    if therapeutic_area is not None:
        where.append("therapeutic_area = ?")
        params.append(therapeutic_area)
    if brand_focus is not None:
        where.append("brand_focus = ?")
        params.append(brand_focus)
    if domain is not None:
        where.append("domain = ?")
        params.append(_enum_value(domain))
    if date_from is not None:
        where.append("timestamp_utc >= ?")
        params.append(date_from)
    if date_to is not None:
        where.append("timestamp_utc <= ?")
        params.append(date_to)
    if sentiment_min is not None:
        where.append("sentiment_score >= ?")
        params.append(sentiment_min)
    if sentiment_max is not None:
        where.append("sentiment_score <= ?")
        params.append(sentiment_max)
    if alert_triggered is not None:
        where.append("alert_triggered = ?")
        params.append(int(alert_triggered))
    if status is not None:
        where.append("status = ?")
        params.append(_enum_value(status))
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params


def query_responses(
    conn: sqlite3.Connection,
    *,
    llm=None,
    persona=None,
    therapeutic_area: str | None = None,
    brand_focus: str | None = None,
    domain=None,
    date_from: str | None = None,
    date_to: str | None = None,
    sentiment_min: float | None = None,
    sentiment_max: float | None = None,
    alert_triggered: bool | None = None,
    status=None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Response]:
    """Query responses by any combination of filters, ordered by timestamp then
    id for stable pagination (FR-303, FR-307)."""
    clause, params = _response_filters(
        llm=llm, persona=persona, therapeutic_area=therapeutic_area,
        brand_focus=brand_focus, domain=domain, date_from=date_from,
        date_to=date_to, sentiment_min=sentiment_min, sentiment_max=sentiment_max,
        alert_triggered=alert_triggered, status=status,
    )
    sql = (
        f"SELECT * FROM responses{clause} "
        "ORDER BY timestamp_utc ASC, response_id ASC"
    )
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = params + [limit, offset]
    rows = conn.execute(sql, params).fetchall()
    return [Response(**dict(r)) for r in rows]


def count_responses(conn: sqlite3.Connection, **filters) -> int:
    """Count responses matching the same filters as query_responses (FR-307)."""
    clause, params = _response_filters(**filters)
    row = conn.execute(
        f"SELECT COUNT(*) AS c FROM responses{clause}", params
    ).fetchone()
    return row["c"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/repositories/test_responses_query.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/repositories/responses.py tests/repositories/test_responses_query.py
git commit -m "feat: queryable response read API with filters and pagination"
```

---

### Task 2: Export query results to CSV and JSON

**Files:**
- Create: `ema_poc/export.py`
- Test: `tests/test_export.py`

- [ ] **Step 1: Write the failing test**

`tests/test_export.py`:
```python
import csv
import json

from ema_poc.export import export_csv, export_json
from ema_poc.models import Response


def _resp(rid, text="ans", sentiment=None):
    return Response(
        response_id=rid, run_id="r1", timestamp_utc="2026-06-13T02:00:00+00:00",
        llm_name="GPT-4o", llm_model_version="m", persona="Provider",
        question_id="Q1", question_text="q", domain="Safety",
        response_text=text, response_tokens=10, finish_reason="stop",
        status="SUCCESS", sentiment_score=sentiment,
        created_at="2026-06-13T02:00:00+00:00",
    )


def test_export_csv_writes_header_and_rows(tmp_path):
    path = tmp_path / "out.csv"
    n = export_csv([_resp("a", text="first"), _resp("b", text="second")], str(path))
    assert n == 2
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["response_id"] for r in rows] == ["a", "b"]
    assert rows[0]["response_text"] == "first"
    assert rows[0]["status"] == "SUCCESS"
    assert "llm_name" in rows[0]


def test_export_json_writes_list_of_objects(tmp_path):
    path = tmp_path / "out.json"
    n = export_json([_resp("a", sentiment=-0.4)], str(path))
    assert n == 1
    data = json.loads(path.read_text())
    assert isinstance(data, list)
    assert data[0]["response_id"] == "a"
    assert data[0]["sentiment_score"] == -0.4
    assert data[0]["status"] == "SUCCESS"  # enum serialized to its value


def test_export_csv_empty_list_writes_header_only(tmp_path):
    path = tmp_path / "empty.csv"
    n = export_csv([], str(path))
    assert n == 0
    lines = path.read_text().splitlines()
    assert len(lines) == 1  # header row only
    assert "response_id" in lines[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/test_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.export'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/export.py`:
```python
"""Export query results to CSV and JSON for stakeholder review (FR-305).

Serializes Response models via model_dump(mode="json") so enums become their
string values and timestamps become ISO strings — safe for both CSV cells and
JSON."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable

from ema_poc.models import Response

_FIELDS = list(Response.model_fields.keys())


def export_csv(responses: Iterable[Response], path: str) -> int:
    rows = [r.model_dump(mode="json") for r in responses]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def export_json(responses: Iterable[Response], path: str) -> int:
    rows = [r.model_dump(mode="json") for r in responses]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)
    return len(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/test_export.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/export.py tests/test_export.py
git commit -m "feat: export responses to CSV and JSON"
```

---

### Task 3: Change detection between latest two responses

**Files:**
- Modify: `ema_poc/repositories/responses.py` (add `import difflib`, `from dataclasses import dataclass`, and `ResponseChange`, `latest_responses`, `detect_change`)
- Test: `tests/repositories/test_responses_diff.py`

- [ ] **Step 1: Write the failing test**

`tests/repositories/test_responses_diff.py`:
```python
from ema_poc.db import connect, init_schema
from ema_poc.models import Response
from ema_poc.repositories.responses import detect_change, latest_responses, save_response
from ema_poc.repositories.runs import create_run

T1 = "2026-06-13T01:00:00+00:00"
T2 = "2026-06-13T02:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=T1)
    return conn


def _save(conn, rid, *, ts, text, question_id="Q1", llm="GPT-4o"):
    save_response(conn, Response(
        response_id=rid, run_id="r1", timestamp_utc=ts, llm_name=llm,
        llm_model_version="m", persona="Provider", question_id=question_id,
        question_text="q", domain="Safety", response_text=text, response_tokens=1,
        finish_reason="stop", status="SUCCESS", created_at=ts,
    ))


def test_latest_responses_returns_newest_first(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "old", ts=T1, text="v1")
    _save(conn, "new", ts=T2, text="v2")
    latest = latest_responses(conn, "Q1", "GPT-4o", limit=2)
    assert [r.response_id for r in latest] == ["new", "old"]
    conn.close()


def test_detect_change_flags_difference_with_diff(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "old", ts=T1, text="Drug X is first-line.")
    _save(conn, "new", ts=T2, text="Drug X is second-line.")
    change = detect_change(conn, "Q1", "GPT-4o")
    assert change.changed is True
    assert change.previous_text == "Drug X is first-line."
    assert change.current_text == "Drug X is second-line."
    assert "second-line" in change.diff
    conn.close()


def test_detect_change_false_when_identical(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "old", ts=T1, text="same")
    _save(conn, "new", ts=T2, text="same")
    change = detect_change(conn, "Q1", "GPT-4o")
    assert change.changed is False
    assert change.diff == ""
    conn.close()


def test_detect_change_no_previous_returns_unchanged(tmp_path):
    conn = _conn(tmp_path)
    _save(conn, "only", ts=T1, text="first ever")
    change = detect_change(conn, "Q1", "GPT-4o")
    assert change.changed is False
    assert change.previous_text is None
    assert change.current_text == "first ever"
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/repositories/test_responses_diff.py -v`
Expected: FAIL with `ImportError: cannot import name 'detect_change'`.

- [ ] **Step 3: Update imports and append to `ema_poc/repositories/responses.py`**

At the top of the file, add these imports (below the existing `import sqlite3` / `from datetime import datetime`):
```python
import difflib
from dataclasses import dataclass
```
Then append:
```python
@dataclass
class ResponseChange:
    """Change detection result for a (question_id, llm_name) pair (FR-306,
    BR-004). `changed` is False when there is no previous response."""

    question_id: str
    llm_name: str
    changed: bool
    previous_text: str | None
    current_text: str | None
    diff: str


def latest_responses(
    conn: sqlite3.Connection, question_id: str, llm_name: str, *, limit: int = 2
) -> list[Response]:
    """The most recent responses for a question/LLM pair, newest first."""
    rows = conn.execute(
        "SELECT * FROM responses WHERE question_id = ? AND llm_name = ? "
        "ORDER BY timestamp_utc DESC, response_id DESC LIMIT ?",
        (question_id, llm_name, limit),
    ).fetchall()
    return [Response(**dict(r)) for r in rows]


def detect_change(
    conn: sqlite3.Connection, question_id: str, llm_name: str
) -> ResponseChange:
    """Compare the current and previous response for a question/LLM pair and
    return a ResponseChange with a unified diff when the text differs."""
    recent = latest_responses(conn, question_id, llm_name, limit=2)
    current = recent[0] if recent else None
    previous = recent[1] if len(recent) > 1 else None
    current_text = current.response_text if current else None
    previous_text = previous.response_text if previous else None

    if previous is None:
        return ResponseChange(
            question_id, llm_name, False, None, current_text, ""
        )

    changed = current_text != previous_text
    diff = ""
    if changed:
        diff = "".join(
            difflib.unified_diff(
                previous_text.splitlines(keepends=True),
                current_text.splitlines(keepends=True),
                fromfile="previous",
                tofile="current",
            )
        )
    return ResponseChange(
        question_id, llm_name, changed, previous_text, current_text, diff
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/repositories/test_responses_diff.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/repositories/responses.py tests/repositories/test_responses_diff.py
git commit -m "feat: response change detection with unified diff"
```

---

### Task 4: Response Repository integration test

**Files:**
- Test: `tests/repositories/test_responses_integration.py`

- [ ] **Step 1: Write the integration test**

`tests/repositories/test_responses_integration.py`:
```python
"""End-to-end read surface: store a mixed set of responses across two runs,
query by filters + pagination, export to CSV/JSON, and detect a change."""

import csv
import json

from ema_poc.db import connect, init_schema
from ema_poc.export import export_csv, export_json
from ema_poc.models import Response
from ema_poc.repositories.responses import (
    count_responses,
    detect_change,
    query_responses,
    save_response,
)
from ema_poc.repositories.runs import create_run

T1 = "2026-06-13T01:00:00+00:00"
T2 = "2026-06-13T02:00:00+00:00"


def _save(conn, rid, *, run_id, llm, ts, text, sentiment=None, alert=False,
          persona="Provider", question_id="Q1"):
    save_response(conn, Response(
        response_id=rid, run_id=run_id, timestamp_utc=ts, llm_name=llm,
        llm_model_version="m", persona=persona, question_id=question_id,
        question_text="q", therapeutic_area="Immunology", brand_focus="Skyrizi",
        domain="Safety", response_text=text, response_tokens=10,
        finish_reason="stop", status="SUCCESS", sentiment_score=sentiment,
        alert_triggered=alert, created_at=ts,
    ))


def test_read_surface_end_to_end(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "run-1", started_at=T1)
    create_run(conn, "run-2", started_at=T2)

    # run-1: GPT-4o positive, Gemini negative+alert
    _save(conn, "a", run_id="run-1", llm="GPT-4o", ts=T1, text="X is first-line.", sentiment=0.6)
    _save(conn, "b", run_id="run-1", llm="Gemini", ts=T1, text="X not recommended.", sentiment=-0.5, alert=True)
    # run-2: GPT-4o changed its answer
    _save(conn, "c", run_id="run-2", llm="GPT-4o", ts=T2, text="X is second-line.", sentiment=0.1)

    # query: all, then filtered
    assert count_responses(conn) == 3
    assert [r.response_id for r in query_responses(conn, llm="GPT-4o")] == ["a", "c"]
    assert [r.response_id for r in query_responses(conn, alert_triggered=True)] == ["b"]
    assert [r.response_id for r in query_responses(conn, sentiment_max=-0.3)] == ["b"]
    # pagination
    page = query_responses(conn, limit=2, offset=0)
    assert [r.response_id for r in page] == ["a", "b"]

    # export the GPT-4o responses
    gpt = query_responses(conn, llm="GPT-4o")
    csv_path = tmp_path / "gpt.csv"
    json_path = tmp_path / "gpt.json"
    assert export_csv(gpt, str(csv_path)) == 2
    assert export_json(gpt, str(json_path)) == 2
    with open(csv_path, newline="", encoding="utf-8") as fh:
        assert [row["response_id"] for row in csv.DictReader(fh)] == ["a", "c"]
    assert [o["response_id"] for o in json.loads(json_path.read_text())] == ["a", "c"]

    # change detection: GPT-4o changed between run-1 and run-2
    change = detect_change(conn, "Q1", "GPT-4o")
    assert change.changed is True
    assert change.previous_text == "X is first-line."
    assert change.current_text == "X is second-line."
    assert "second-line" in change.diff

    conn.close()
```

- [ ] **Step 2: Run the integration test**

Run: `. .venv/bin/activate && pytest tests/repositories/test_responses_integration.py -v`
Expected: PASS (1 passed). If it fails, the failure points at a real wiring gap — fix the referenced module, do not weaken the test.

- [ ] **Step 3: Run the whole suite with coverage**

Run: `. .venv/bin/activate && pytest -q --cov` and `. .venv/bin/activate && pytest -q -W error::ResourceWarning`.
Expected: all green; no ResourceWarning. Note the coverage % for `ema_poc/repositories/responses.py` and `ema_poc/export.py`.

- [ ] **Step 4: Commit**

```bash
git add tests/repositories/test_responses_integration.py
git commit -m "test: response repository read surface end-to-end"
```

---

## Self-Review

**Spec coverage (Phase 4 scope):**
- FR-303 query by any combination (LLM, persona, TA, brand, domain, date range, sentiment range, alert, status) → `query_responses` + `_response_filters` → Task 1.
- FR-307 simple query API returning paginated results, no direct DB access for routine queries → `query_responses(limit, offset)` + `count_responses` → Task 1.
- FR-305 export query results to CSV and JSON → `export_csv` / `export_json` → Task 2.
- FR-306 diff between current and previous response for the same question/LLM pair → `detect_change` (unified diff) → Task 3.
- BR-004 flag when an LLM changes its response materially between runs → `ResponseChange.changed` + diff → Task 3.

Deferred (correctly out of scope): the REST endpoint variant of FR-307 (a Python function API is provided; a REST wrapper is a later/optional concern); response soft-delete (DM-003 — responses are immutable and retained; no delete path is required by FR-3); FR-306 *storing* a materialized diff column (computed on demand here, which satisfies change detection without schema change). Scoring/alert population of `sentiment_score`/`alert_triggered` is Phase 5 (this phase only queries those columns).

**Placeholder scan:** No "TBD"/"add error handling"/"similar to" placeholders — every code and test step is complete.

**Type/name consistency:** `query_responses`, `count_responses`, `_response_filters`, `_enum_value`, `detect_change`, `latest_responses`, `ResponseChange` are referenced with identical names/signatures across Tasks 1, 3, 4. `export_csv`/`export_json` (Task 2) are used in Task 4. All operate on the `Response` model and the `responses` schema columns from Phase 1; filter columns (llm_name, persona, therapeutic_area, brand_focus, domain, timestamp_utc, sentiment_score, alert_triggered, status) all exist on that table. `_enum_value` mirrors the same helper already used in the questions repo (consistent convention).
