# Evidence Monitoring Agent — Question Repository Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Question Repository (FR-1): a versioned, queryable store of persona-tagged questions with add/edit/deactivate/approve/reject/soft-delete operations that never destroy history, filtering, an active-and-approved view for the runner, and CSV/Excel import for Medical Affairs curation.

**Architecture:** A single data-access module `ema_poc/repositories/questions.py` — the only code that touches the `questions` table. Every mutation writes a NEW version row (immutable history, FR-103); "current" = the highest-version row per `question_id`. Functions accept primitive fields, return validated `Question` model instances, and take an injectable `now` timestamp for deterministic tests. Built on the Phase 1 foundations (`ema_poc/db.py`, `ema_poc/models.py`), already merged to `develop`.

**Tech Stack:** Python 3.11+, stdlib `sqlite3` + `csv`, Pydantic v2 (`ema_poc.models.Question`), `openpyxl` for Excel import, pytest.

**Spec:** `docs/superpowers/specs/2026-06-13-evidence-monitoring-agent-poc-design.md` (§3 repositories, §4 data model, FR-1, SE-002, BR-009).

**Conventions:**
- Mutations create a new version row; `created_at` is preserved across versions, `updated_at` is set per version.
- `now` is an injectable ISO-8601 UTC string (defaults to `datetime.now(timezone.utc).isoformat()`).
- Tests open a DB via `connect`/`init_schema`, and call `conn.close()` at the end (Python 3.14 ResourceWarning hygiene, matching Phase 1).
- Activate the venv with `. .venv/bin/activate` before pytest.

---

### Task 1: Repository package + add/get core

**Files:**
- Create: `ema_poc/repositories/__init__.py`
- Create: `ema_poc/repositories/questions.py`
- Test: `tests/repositories/__init__.py`
- Test: `tests/repositories/test_questions_core.py`

- [ ] **Step 1: Write the failing test**

`tests/repositories/__init__.py`:
```python
```

`tests/repositories/test_questions_core.py`:
```python
import pytest

from ema_poc.db import connect, init_schema
from ema_poc.models import ApprovalStatus, Domain, Persona
from ema_poc.repositories.questions import add_question, get_current, get_version


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def test_add_question_creates_version_1(tmp_path):
    conn = _conn(tmp_path)
    q = add_question(
        conn,
        question_id="Q1",
        question_text="Is drug X first-line?",
        persona="Provider",
        domain="Comparative",
        therapeutic_area="Immunology",
        brand_focus="Skyrizi",
        now="2026-06-13T00:00:00+00:00",
    )
    assert q.version == 1
    assert q.persona is Persona.PROVIDER
    assert q.domain is Domain.COMPARATIVE
    assert q.active is True
    assert q.approval_status is ApprovalStatus.PENDING
    assert q.therapeutic_area == "Immunology"
    conn.close()


def test_get_current_and_get_version(tmp_path):
    conn = _conn(tmp_path)
    add_question(
        conn,
        question_id="Q1",
        question_text="t",
        persona="Patient",
        domain="Safety",
        now="2026-06-13T00:00:00+00:00",
    )
    cur = get_current(conn, "Q1")
    assert cur is not None and cur.version == 1
    assert get_version(conn, "Q1", 1).question_text == "t"
    assert get_version(conn, "Q1", 2) is None
    assert get_current(conn, "Q-missing") is None
    conn.close()


def test_add_duplicate_question_id_raises(tmp_path):
    conn = _conn(tmp_path)
    add_question(
        conn,
        question_id="Q1",
        question_text="t",
        persona="Prospect",
        domain="General",
        now="2026-06-13T00:00:00+00:00",
    )
    with pytest.raises(ValueError):
        add_question(
            conn,
            question_id="Q1",
            question_text="dup",
            persona="Prospect",
            domain="General",
        )
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/repositories/test_questions_core.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.repositories'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/repositories/__init__.py`:
```python
"""Repository layer — the only code that touches SQL (spec §3)."""
```

`ema_poc/repositories/questions.py`:
```python
"""Question Repository: versioned, queryable question store (FR-1).

Every mutation writes a new version row; "current" is the highest-version row
per question_id. History is never destroyed (FR-103). Functions accept an
injectable `now` ISO-8601 UTC timestamp for deterministic tests.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from ema_poc.models import Question


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def _question_from_row(row: sqlite3.Row) -> Question:
    return Question(**dict(row))


def _insert_version(conn: sqlite3.Connection, q: Question) -> None:
    conn.execute(
        """
        INSERT INTO questions (
            question_id, version, question_text, persona, therapeutic_area,
            brand_focus, domain, active, approval_status, approver_name,
            created_at, updated_at, deleted_at, delete_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            q.question_id,
            q.version,
            q.question_text,
            q.persona.value,
            q.therapeutic_area,
            q.brand_focus,
            q.domain.value,
            int(q.active),
            q.approval_status.value,
            q.approver_name,
            _iso(q.created_at),
            _iso(q.updated_at),
            _iso(q.deleted_at),
            q.delete_reason,
        ),
    )
    conn.commit()


def get_version(
    conn: sqlite3.Connection, question_id: str, version: int
) -> Question | None:
    row = conn.execute(
        "SELECT * FROM questions WHERE question_id = ? AND version = ?",
        (question_id, version),
    ).fetchone()
    return _question_from_row(row) if row else None


def get_current(conn: sqlite3.Connection, question_id: str) -> Question | None:
    row = conn.execute(
        "SELECT * FROM questions WHERE question_id = ? ORDER BY version DESC LIMIT 1",
        (question_id,),
    ).fetchone()
    return _question_from_row(row) if row else None


def add_question(
    conn: sqlite3.Connection,
    *,
    question_id: str,
    question_text: str,
    persona: str,
    domain: str,
    therapeutic_area: str | None = None,
    brand_focus: str | None = None,
    now: str | None = None,
) -> Question:
    if get_current(conn, question_id) is not None:
        raise ValueError(f"Question already exists: {question_id}")
    now = now or _now_iso()
    q = Question(
        question_id=question_id,
        version=1,
        question_text=question_text,
        persona=persona,
        domain=domain,
        therapeutic_area=therapeutic_area,
        brand_focus=brand_focus,
        created_at=now,
        updated_at=now,
    )
    _insert_version(conn, q)
    return get_version(conn, question_id, 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/repositories/test_questions_core.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/repositories/__init__.py ema_poc/repositories/questions.py tests/repositories/__init__.py tests/repositories/test_questions_core.py
git commit -m "feat: question repository add/get with versioned rows"
```

---

### Task 2: list_questions with filtering

**Files:**
- Modify: `ema_poc/repositories/questions.py` (append `list_questions`)
- Test: `tests/repositories/test_questions_list.py`

- [ ] **Step 1: Write the failing test**

`tests/repositories/test_questions_list.py`:
```python
from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import add_question, list_questions

NOW = "2026-06-13T00:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def _seed(conn):
    add_question(conn, question_id="Q1", question_text="a", persona="Provider",
                 domain="Comparative", therapeutic_area="Immunology",
                 brand_focus="Skyrizi", now=NOW)
    add_question(conn, question_id="Q2", question_text="b", persona="Patient",
                 domain="Safety", therapeutic_area="Immunology",
                 brand_focus="Rinvoq", now=NOW)
    add_question(conn, question_id="Q3", question_text="c", persona="Provider",
                 domain="Efficacy", therapeutic_area="Oncology",
                 brand_focus="Venclexta", now=NOW)


def test_list_all(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    ids = [q.question_id for q in list_questions(conn)]
    assert ids == ["Q1", "Q2", "Q3"]  # ordered by question_id
    conn.close()


def test_filter_by_persona_and_domain(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    providers = [q.question_id for q in list_questions(conn, persona="Provider")]
    assert providers == ["Q1", "Q3"]
    safety = [q.question_id for q in list_questions(conn, domain="Safety")]
    assert safety == ["Q2"]
    conn.close()


def test_filter_by_ta_and_brand(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    immuno = [q.question_id for q in list_questions(conn, therapeutic_area="Immunology")]
    assert immuno == ["Q1", "Q2"]
    skyrizi = [q.question_id for q in list_questions(conn, brand_focus="Skyrizi")]
    assert skyrizi == ["Q1"]
    conn.close()


def test_filter_by_active_flag(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    # all active by default
    assert len(list_questions(conn, active=True)) == 3
    assert list_questions(conn, active=False) == []
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/repositories/test_questions_list.py -v`
Expected: FAIL with `ImportError: cannot import name 'list_questions'`.

- [ ] **Step 3: Append the implementation to `ema_poc/repositories/questions.py`**

```python
def _enum_value(x):
    return x.value if hasattr(x, "value") else x


def list_questions(
    conn: sqlite3.Connection,
    *,
    persona=None,
    therapeutic_area: str | None = None,
    brand_focus: str | None = None,
    domain=None,
    active: bool | None = None,
    approval_status=None,
    include_deleted: bool = False,
) -> list[Question]:
    """Return the current version of each question, filtered. Excludes
    soft-deleted questions unless include_deleted=True."""
    sql = [
        "SELECT q.* FROM questions q",
        "JOIN (SELECT question_id, MAX(version) AS v FROM questions"
        " GROUP BY question_id) m",
        "ON q.question_id = m.question_id AND q.version = m.v",
    ]
    where: list[str] = []
    params: list = []
    if persona is not None:
        where.append("q.persona = ?")
        params.append(_enum_value(persona))
    if therapeutic_area is not None:
        where.append("q.therapeutic_area = ?")
        params.append(therapeutic_area)
    if brand_focus is not None:
        where.append("q.brand_focus = ?")
        params.append(brand_focus)
    if domain is not None:
        where.append("q.domain = ?")
        params.append(_enum_value(domain))
    if active is not None:
        where.append("q.active = ?")
        params.append(int(active))
    if approval_status is not None:
        where.append("q.approval_status = ?")
        params.append(_enum_value(approval_status))
    if not include_deleted:
        where.append("q.deleted_at IS NULL")
    if where:
        sql.append("WHERE " + " AND ".join(where))
    sql.append("ORDER BY q.question_id")
    rows = conn.execute("\n".join(sql), params).fetchall()
    return [_question_from_row(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/repositories/test_questions_list.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/repositories/questions.py tests/repositories/test_questions_list.py
git commit -m "feat: list_questions with persona/TA/brand/domain/active/approval filters"
```

---

### Task 3: update / deactivate / approve / reject (versioned)

**Files:**
- Modify: `ema_poc/repositories/questions.py` (append four functions)
- Test: `tests/repositories/test_questions_update.py`

- [ ] **Step 1: Write the failing test**

`tests/repositories/test_questions_update.py`:
```python
import pytest

from ema_poc.db import connect, init_schema
from ema_poc.models import ApprovalStatus
from ema_poc.repositories.questions import (
    add_question,
    approve_question,
    deactivate_question,
    get_current,
    get_version,
    reject_question,
    update_question,
)

NOW = "2026-06-13T00:00:00+00:00"
LATER = "2026-06-14T00:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def _seed(conn):
    add_question(conn, question_id="Q1", question_text="original",
                 persona="Provider", domain="Comparative", now=NOW)


def test_update_creates_new_version_and_keeps_history(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    updated = update_question(conn, "Q1", question_text="edited", now=LATER)
    assert updated.version == 2
    assert updated.question_text == "edited"
    # history preserved
    assert get_version(conn, "Q1", 1).question_text == "original"
    # created_at preserved across versions; updated_at advanced
    assert get_version(conn, "Q1", 2).created_at == get_version(conn, "Q1", 1).created_at
    conn.close()


def test_update_missing_raises(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(KeyError):
        update_question(conn, "missing", question_text="x")
    conn.close()


def test_approve_sets_status_and_approver(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    approve_question(conn, "Q1", approver_name="Dr. Reviewer", now=LATER)
    cur = get_current(conn, "Q1")
    assert cur.approval_status is ApprovalStatus.APPROVED
    assert cur.approver_name == "Dr. Reviewer"
    assert cur.version == 2
    conn.close()


def test_reject_sets_status(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    reject_question(conn, "Q1", approver_name="Dr. Reviewer", now=LATER)
    assert get_current(conn, "Q1").approval_status is ApprovalStatus.REJECTED
    conn.close()


def test_deactivate_sets_active_false(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    deactivate_question(conn, "Q1", now=LATER)
    assert get_current(conn, "Q1").active is False
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/repositories/test_questions_update.py -v`
Expected: FAIL with `ImportError: cannot import name 'update_question'`.

- [ ] **Step 3: Append the implementation to `ema_poc/repositories/questions.py`**

```python
def update_question(
    conn: sqlite3.Connection, question_id: str, *, now: str | None = None, **changes
) -> Question:
    """Write a new version with `changes` applied. `created_at` is preserved
    from the current version; `updated_at` is set to `now`. Raises KeyError if
    the question does not exist."""
    current = get_current(conn, question_id)
    if current is None:
        raise KeyError(f"No such question: {question_id}")
    data = current.model_dump()
    data.update(changes)
    data["version"] = current.version + 1
    data["updated_at"] = now or _now_iso()
    new = Question(**data)  # re-validates the applied changes
    _insert_version(conn, new)
    return get_version(conn, question_id, new.version)


def deactivate_question(
    conn: sqlite3.Connection, question_id: str, *, now: str | None = None
) -> Question:
    return update_question(conn, question_id, active=False, now=now)


def approve_question(
    conn: sqlite3.Connection,
    question_id: str,
    approver_name: str,
    *,
    now: str | None = None,
) -> Question:
    return update_question(
        conn,
        question_id,
        approval_status="APPROVED",
        approver_name=approver_name,
        now=now,
    )


def reject_question(
    conn: sqlite3.Connection,
    question_id: str,
    approver_name: str,
    *,
    now: str | None = None,
) -> Question:
    return update_question(
        conn,
        question_id,
        approval_status="REJECTED",
        approver_name=approver_name,
        now=now,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/repositories/test_questions_update.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/repositories/questions.py tests/repositories/test_questions_update.py
git commit -m "feat: versioned update/deactivate/approve/reject for questions"
```

---

### Task 4: soft-delete / history / active_approved

**Files:**
- Modify: `ema_poc/repositories/questions.py` (append three functions)
- Test: `tests/repositories/test_questions_lifecycle.py`

- [ ] **Step 1: Write the failing test**

`tests/repositories/test_questions_lifecycle.py`:
```python
from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import (
    active_approved,
    add_question,
    approve_question,
    deactivate_question,
    get_current,
    history,
    list_questions,
    soft_delete_question,
)

NOW = "2026-06-13T00:00:00+00:00"
LATER = "2026-06-14T00:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def test_soft_delete_marks_tombstone_and_hides_from_list(tmp_path):
    conn = _conn(tmp_path)
    add_question(conn, question_id="Q1", question_text="t", persona="Provider",
                 domain="General", now=NOW)
    soft_delete_question(conn, "Q1", reason="duplicate", now=LATER)
    cur = get_current(conn, "Q1")
    assert cur.deleted_at is not None
    assert cur.delete_reason == "duplicate"
    assert cur.active is False
    # excluded from default listing, visible with include_deleted
    assert list_questions(conn) == []
    assert [q.question_id for q in list_questions(conn, include_deleted=True)] == ["Q1"]
    conn.close()


def test_history_returns_all_versions(tmp_path):
    conn = _conn(tmp_path)
    add_question(conn, question_id="Q1", question_text="v1", persona="Provider",
                 domain="General", now=NOW)
    approve_question(conn, "Q1", approver_name="R", now=LATER)
    versions = history(conn, "Q1")
    assert [h.version for h in versions] == [1, 2]
    assert versions[0].question_text == "v1"
    conn.close()


def test_active_approved_view(tmp_path):
    conn = _conn(tmp_path)
    # Q1: approved + active -> included
    add_question(conn, question_id="Q1", question_text="a", persona="Provider",
                 domain="General", now=NOW)
    approve_question(conn, "Q1", approver_name="R", now=LATER)
    # Q2: approved then deactivated -> excluded
    add_question(conn, question_id="Q2", question_text="b", persona="Provider",
                 domain="General", now=NOW)
    approve_question(conn, "Q2", approver_name="R", now=LATER)
    deactivate_question(conn, "Q2", now=LATER)
    # Q3: active but pending -> excluded
    add_question(conn, question_id="Q3", question_text="c", persona="Provider",
                 domain="General", now=NOW)
    # Q4: approved then soft-deleted -> excluded
    add_question(conn, question_id="Q4", question_text="d", persona="Provider",
                 domain="General", now=NOW)
    approve_question(conn, "Q4", approver_name="R", now=LATER)
    soft_delete_question(conn, "Q4", reason="x", now=LATER)

    assert [q.question_id for q in active_approved(conn)] == ["Q1"]
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/repositories/test_questions_lifecycle.py -v`
Expected: FAIL with `ImportError: cannot import name 'soft_delete_question'`.

- [ ] **Step 3: Append the implementation to `ema_poc/repositories/questions.py`**

```python
def soft_delete_question(
    conn: sqlite3.Connection, question_id: str, reason: str, *, now: str | None = None
) -> Question:
    """Tombstone the question via a new version with deleted_at set and
    active=False. History is preserved (no physical delete; DM-003)."""
    now = now or _now_iso()
    return update_question(
        conn,
        question_id,
        now=now,
        deleted_at=now,
        delete_reason=reason,
        active=False,
    )


def history(conn: sqlite3.Connection, question_id: str) -> list[Question]:
    rows = conn.execute(
        "SELECT * FROM questions WHERE question_id = ? ORDER BY version ASC",
        (question_id,),
    ).fetchall()
    return [_question_from_row(r) for r in rows]


def active_approved(conn: sqlite3.Connection) -> list[Question]:
    """Current questions that are active AND approved AND not soft-deleted —
    the set the runner dispatches (SE-002, BR-009)."""
    return list_questions(conn, active=True, approval_status="APPROVED")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/repositories/test_questions_lifecycle.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/repositories/questions.py tests/repositories/test_questions_lifecycle.py
git commit -m "feat: soft-delete, history, and active_approved view for questions"
```

---

### Task 5: CSV and Excel import

**Files:**
- Modify: `pyproject.toml` (add `openpyxl` dependency)
- Modify: `ema_poc/repositories/questions.py` (add `import csv` + import functions)
- Test: `tests/repositories/test_questions_import.py`

- [ ] **Step 1: Install openpyxl and add it to dependencies**

Run: `. .venv/bin/activate && pip install -q openpyxl`

In `pyproject.toml`, change:
```toml
dependencies = [
    "pydantic>=2",
    "pyyaml",
]
```
to:
```toml
dependencies = [
    "pydantic>=2",
    "pyyaml",
    "openpyxl",
]
```

- [ ] **Step 2: Write the failing test**

`tests/repositories/test_questions_import.py`:
```python
from openpyxl import Workbook

from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import (
    get_current,
    import_questions_csv,
    import_questions_excel,
)

NOW = "2026-06-13T00:00:00+00:00"
LATER = "2026-06-14T00:00:00+00:00"

CSV_TEXT = (
    "question_id,question_text,persona,domain,therapeutic_area,brand_focus\n"
    "Q1,Is X first-line?,Provider,Comparative,Immunology,Skyrizi\n"
    "Q2,Is X safe in pregnancy?,Patient,Safety,Immunology,\n"
)


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def test_import_csv_adds_questions(tmp_path):
    conn = _conn(tmp_path)
    path = tmp_path / "q.csv"
    path.write_text(CSV_TEXT)
    count = import_questions_csv(conn, str(path), now=NOW)
    assert count == 2
    q1 = get_current(conn, "Q1")
    assert q1.persona.value == "Provider"
    assert q1.brand_focus == "Skyrizi"
    # empty cell becomes None, not ""
    assert get_current(conn, "Q2").brand_focus is None
    conn.close()


def test_reimport_updates_existing_as_new_version(tmp_path):
    conn = _conn(tmp_path)
    path = tmp_path / "q.csv"
    path.write_text(CSV_TEXT)
    import_questions_csv(conn, str(path), now=NOW)

    changed = (
        "question_id,question_text,persona,domain,therapeutic_area,brand_focus\n"
        "Q1,Is X still first-line?,Provider,Comparative,Immunology,Skyrizi\n"
    )
    path.write_text(changed)
    count = import_questions_csv(conn, str(path), now=LATER)
    assert count == 1
    q1 = get_current(conn, "Q1")
    assert q1.version == 2
    assert q1.question_text == "Is X still first-line?"
    conn.close()


def test_import_excel_adds_questions(tmp_path):
    conn = _conn(tmp_path)
    wb = Workbook()
    ws = wb.active
    ws.append(
        ["question_id", "question_text", "persona", "domain",
         "therapeutic_area", "brand_focus"]
    )
    ws.append(["Q1", "Is X first-line?", "Provider", "Comparative",
               "Immunology", "Skyrizi"])
    xlsx = tmp_path / "q.xlsx"
    wb.save(xlsx)

    count = import_questions_excel(conn, str(xlsx), now=NOW)
    assert count == 1
    assert get_current(conn, "Q1").question_text == "Is X first-line?"
    conn.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/repositories/test_questions_import.py -v`
Expected: FAIL with `ImportError: cannot import name 'import_questions_csv'`.

- [ ] **Step 4: Append the implementation to `ema_poc/repositories/questions.py`**

Add `import csv` to the imports at the top of the file (below `import sqlite3`). Then append:
```python
def _coerce_optional(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _upsert_row(conn: sqlite3.Connection, row: dict, now: str) -> None:
    qid = str(row["question_id"]).strip()
    fields = dict(
        question_text=str(row["question_text"]).strip(),
        persona=str(row["persona"]).strip(),
        domain=str(row["domain"]).strip(),
        therapeutic_area=_coerce_optional(row.get("therapeutic_area")),
        brand_focus=_coerce_optional(row.get("brand_focus")),
    )
    if get_current(conn, qid) is None:
        add_question(conn, question_id=qid, now=now, **fields)
    else:
        update_question(conn, qid, now=now, **fields)


def import_questions_csv(
    conn: sqlite3.Connection, path: str, *, now: str | None = None
) -> int:
    """Upsert questions from a CSV with columns: question_id, question_text,
    persona, domain, therapeutic_area, brand_focus. Existing question_ids are
    updated as a new version; new ones are added (FR-105). Returns row count."""
    now = now or _now_iso()
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        _upsert_row(conn, row, now)
    return len(rows)


def import_questions_excel(
    conn: sqlite3.Connection, path: str, *, now: str | None = None
) -> int:
    """Upsert questions from an .xlsx whose first row is the header (same
    columns as CSV import). Returns the number of data rows processed."""
    from openpyxl import load_workbook

    now = now or _now_iso()
    wb = load_workbook(path, read_only=True)
    try:
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        headers = list(next(rows_iter))
        count = 0
        for values in rows_iter:
            if all(v is None for v in values):
                continue
            _upsert_row(conn, dict(zip(headers, values)), now)
            count += 1
        return count
    finally:
        wb.close()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/repositories/test_questions_import.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml ema_poc/repositories/questions.py tests/repositories/test_questions_import.py
git commit -m "feat: CSV/Excel question import with upsert semantics"
```

---

### Task 6: Question repository integration lifecycle test

**Files:**
- Test: `tests/repositories/test_questions_integration.py`

- [ ] **Step 1: Write the integration test**

`tests/repositories/test_questions_integration.py`:
```python
"""Full question lifecycle: import -> approve -> filter -> edit -> deactivate,
verifying the active_approved view and version history end to end."""

from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import (
    active_approved,
    approve_question,
    deactivate_question,
    history,
    import_questions_csv,
    list_questions,
    update_question,
)

NOW = "2026-06-13T00:00:00+00:00"
T2 = "2026-06-14T00:00:00+00:00"
T3 = "2026-06-15T00:00:00+00:00"

CSV_TEXT = (
    "question_id,question_text,persona,domain,therapeutic_area,brand_focus\n"
    "Q1,first,Provider,Comparative,Immunology,Skyrizi\n"
    "Q2,second,Patient,Safety,Immunology,Rinvoq\n"
    "Q3,third,Provider,Efficacy,Oncology,Venclexta\n"
)


def test_question_lifecycle_end_to_end(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    path = tmp_path / "q.csv"
    path.write_text(CSV_TEXT)

    # 1. Import a 3-question bank
    assert import_questions_csv(conn, str(path), now=NOW) == 3
    assert len(list_questions(conn)) == 3
    # nothing approved yet -> runner sees nothing
    assert active_approved(conn) == []

    # 2. Medical Affairs approves Q1 and Q2 (SE-002 / BR-009)
    approve_question(conn, "Q1", approver_name="Dr. A", now=T2)
    approve_question(conn, "Q2", approver_name="Dr. A", now=T2)
    assert [q.question_id for q in active_approved(conn)] == ["Q1", "Q2"]

    # 3. Filter the bank by persona
    providers = [q.question_id for q in list_questions(conn, persona="Provider")]
    assert providers == ["Q1", "Q3"]

    # 4. Edit Q1 text (new version) and confirm history + still approved/active
    update_question(conn, "Q1", question_text="first (revised)", now=T3)
    assert [h.version for h in history(conn, "Q1")] == [1, 2, 3]
    assert [q.question_id for q in active_approved(conn)] == ["Q1", "Q2"]

    # 5. Deactivate Q2 -> drops out of the runner's view
    deactivate_question(conn, "Q2", now=T3)
    assert [q.question_id for q in active_approved(conn)] == ["Q1"]

    conn.close()
```

- [ ] **Step 2: Run the integration test**

Run: `. .venv/bin/activate && pytest tests/repositories/test_questions_integration.py -v`
Expected: PASS (1 passed). If it fails, the failure points at a real wiring gap — fix the referenced repository function, do not weaken the test.

- [ ] **Step 3: Run the whole suite with coverage**

Run: `. .venv/bin/activate && pytest -q --cov`
Expected: PASS (all Phase 1 + Phase 2 tests green); coverage report prints for `ema_poc`.

- [ ] **Step 4: Commit**

```bash
git add tests/repositories/test_questions_integration.py
git commit -m "test: question repository end-to-end lifecycle"
```

---

## Self-Review

**Spec coverage (FR-1, SE-002, BR-009, DM-003):**
- FR-101 versioned store → versioned rows via `_insert_version`, PK `(question_id, version)` (Phase 1 schema) → Task 1.
- FR-102 record fields → all present on the `Question` model + `questions` table (Phase 1); exercised here.
- FR-103 add/edit/deactivate/version without deleting history → `add_question`, `update_question` (new version), `deactivate_question`, `history` → Tasks 1, 3, 4.
- FR-104 ≥100 / scale to 1000+ → no architectural limit; `list_questions` uses an indexed MAX(version) join.
- FR-105 CSV/Excel import → `import_questions_csv`, `import_questions_excel` → Task 5.
- FR-106 filter by persona/TA/brand/domain/active(/approval) → `list_questions` → Task 2.
- SE-002 / BR-009 approval workflow → `approve_question`/`reject_question` + `active_approved` gate → Tasks 3, 4.
- DM-003 soft-delete (never physically delete) → `soft_delete_question` tombstone version → Task 4.
- FR-107 coverage-gap report (COULD) → intentionally deferred (nice-to-have, not in this plan).

Deferred to later phases: the CLI wrapper that exposes `import-questions`/`list-questions` to Medical Affairs without DB access (built in the scheduling/CLI phase as part of `ema_poc/cli.py`); the runner that consumes `active_approved` (Phase 3).

**Placeholder scan:** No "TBD"/"add validation"/"similar to" placeholders — every step has complete code.

**Type consistency:** `add_question`, `get_current`, `get_version`, `update_question`, `list_questions`, `soft_delete_question`, `history`, `active_approved`, `approve_question`, `reject_question`, `deactivate_question`, `import_questions_csv`, `import_questions_excel` are referenced with identical names/signatures across Tasks 1–6. `_insert_version`, `_question_from_row`, `_iso`, `_now_iso`, `_enum_value`, `_coerce_optional`, `_upsert_row` are defined once and reused. Field/enum names match `ema_poc/models.py` and the Phase 1 `questions` schema (persona/domain/approval_status as enum `.value` strings, `active` as int 0/1, timestamps as ISO strings, `deleted_at` nullable).
```
