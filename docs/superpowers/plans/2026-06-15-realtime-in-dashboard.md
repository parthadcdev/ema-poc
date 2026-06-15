# Realtime Runs in Dashboard Analytics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold realtime playground (`sandbox_*`) runs into the dashboard analytics, tagged with a `source` so they're distinguishable, and persist `brand_mentions` for realtime so Share of Voice includes them.

**Architecture:** Persist the scorer's `brand_mentions` on sandbox responses; extend `collect_dataset` to UNION sandbox responses into the records list (same record shape, `source="realtime"`); monitoring records get `source="monitoring"`; add a Source filter + provenance badge to the dashboard.

**Tech Stack:** Python 3.11+, sqlite3 (stdlib, JSON-in-TEXT), vanilla-JS self-contained dashboard. Tests offline with fakes.

**Spec:** `docs/superpowers/specs/2026-06-15-realtime-in-dashboard-design.md`. **Branch:** `feature/realtime-dashboard`.

**Run the suite with the venv:** `.venv/bin/python -m pytest`. Baseline is **642 passing**.

---

### Task 1: Persist brand_mentions on sandbox responses (schema + repo)

**Files:**
- Modify: `ema_poc/db.py` (`_ADDITIVE_COLUMNS`)
- Modify: `ema_poc/repositories/sandbox.py` (`set_response_score`, add `import json`)
- Test: `tests/repositories/test_sandbox_jobs.py` (append)

- [ ] **Step 1: Write the failing test** (append to `tests/repositories/test_sandbox_jobs.py`; the file already has `from ema_poc.db import connect, init_schema`, `from ema_poc.repositories import sandbox as S`, and a `_conn(tmp_path)` helper):

```python
import json as _json


def test_sandbox_responses_has_brand_mentions_column(tmp_path):
    c = _conn(tmp_path)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(sandbox_responses)")}
    assert "brand_mentions" in cols


def test_set_response_score_persists_brand_mentions(tmp_path):
    c = _conn(tmp_path)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus="Skyrizi",
                         now="t0", status="RUNNING", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="a", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1")
    S.set_response_score(c, sandbox_response_id=rid, sentiment_score=0.5,
                         competitive_position="LEADER", scoring_rationale="r",
                         brand_mentions=["Skyrizi", "Humira"])
    raw = c.execute("SELECT brand_mentions FROM sandbox_responses WHERE sandbox_response_id=?",
                    (rid,)).fetchone()[0]
    assert _json.loads(raw) == ["Skyrizi", "Humira"]


def test_set_response_score_brand_mentions_defaults_null(tmp_path):
    c = _conn(tmp_path)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None,
                         now="t0", status="RUNNING", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="a", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1")
    S.set_response_score(c, sandbox_response_id=rid, sentiment_score=0.5,
                         competitive_position="LEADER", scoring_rationale="r")
    raw = c.execute("SELECT brand_mentions FROM sandbox_responses WHERE sandbox_response_id=?",
                    (rid,)).fetchone()[0]
    assert raw is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/repositories/test_sandbox_jobs.py -k brand_mentions -v`
Expected: FAIL (no column; `set_response_score` has no `brand_mentions` kwarg).

- [ ] **Step 3: Implement**

In `ema_poc/db.py`, append to `_ADDITIVE_COLUMNS` (after the `sandbox_queries` entries):
```python
    ("sandbox_responses", "brand_mentions", "TEXT"),
```

In `ema_poc/repositories/sandbox.py`, add `import json` to the imports at the top (after `import sqlite3`). Replace `set_response_score` with:
```python
def set_response_score(
    conn, *, sandbox_response_id, sentiment_score, competitive_position,
    scoring_rationale, brand_mentions=None, commit: bool = True,
) -> None:
    cur = conn.execute(
        """UPDATE sandbox_responses
           SET sentiment_score = ?, competitive_position = ?, scoring_rationale = ?,
               brand_mentions = ?
           WHERE sandbox_response_id = ?""",
        (sentiment_score, competitive_position, scoring_rationale,
         json.dumps(brand_mentions) if brand_mentions is not None else None,
         sandbox_response_id),
    )
    if cur.rowcount == 0:
        raise ValueError(f"No sandbox_response with id={sandbox_response_id!r}")
    if commit:
        conn.commit()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/repositories/test_sandbox_jobs.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest` (expect 642 + 3 new = 645).
```bash
git add ema_poc/db.py ema_poc/repositories/sandbox.py tests/repositories/test_sandbox_jobs.py
git commit -m "feat: persist scorer brand_mentions on sandbox responses"
```

---

### Task 2: Service stores brand_mentions from the scorer

**Files:**
- Modify: `ema_poc/playground/service.py` (the `set_response_score` call)
- Test: `tests/playground/test_service_brand_mentions.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/playground/test_service_brand_mentions.py
import json
from ema_poc.db import connect, init_schema
from ema_poc.playground.service import run_playground
from ema_poc.repositories import sandbox as S
from ema_poc.adapters.base import LLMResponse


class FakeAdapter:
    name = "A"; model_version = "v"; grounded = False
    def query(self, sp, q):
        return LLMResponse(text="ans", finish_reason="stop", status="SUCCESS",
                           completion_tokens=3)


class FakeScore:
    sentiment_score = 0.5
    competitive_position = "AMONG_OPTIONS"
    scoring_rationale = "r"
    brand_mentions = ["Skyrizi"]


def test_run_playground_persists_brand_mentions(tmp_path):
    c = connect(str(tmp_path / "s.sqlite")); init_schema(c)
    list(run_playground(
        c, adapters=[FakeAdapter()], scoring_client=object(),
        scorer=lambda *a, **k: FakeScore(), abbvie_brands=["Skyrizi"],
        competitor_brands=[], system_prompts={"default": "x"}, question_text="q",
        persona=None, brand_focus="Skyrizi", model="m",
        id_factory=lambda: __import__("uuid").uuid4().hex, now="t1",
        max_retries=0, backoff=[0]))
    raw = c.execute("SELECT brand_mentions FROM sandbox_responses").fetchone()[0]
    assert json.loads(raw) == ["Skyrizi"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/playground/test_service_brand_mentions.py -v`
Expected: FAIL (`brand_mentions` is NULL — service doesn't pass it yet).

- [ ] **Step 3: Implement**

In `ema_poc/playground/service.py`, find the `S.set_response_score(...)` call inside the scoring block and add the `brand_mentions` argument:
```python
                    S.set_response_score(
                        conn, sandbox_response_id=rid,
                        sentiment_score=result.sentiment_score,
                        competitive_position=result.competitive_position,
                        scoring_rationale=result.scoring_rationale,
                        brand_mentions=result.brand_mentions,
                    )
```
(`result` is the scorer's `ScoreResult`, which has `brand_mentions: list[str]`. No other change.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/playground/test_service_brand_mentions.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest` (expect 645 + 1 new = 646).
```bash
git add ema_poc/playground/service.py tests/playground/test_service_brand_mentions.py
git commit -m "feat: playground persists scorer brand_mentions to the sandbox"
```

---

### Task 3: Union sandbox runs into collect_dataset with source tags

**Files:**
- Modify: `ema_poc/dashboard/dataset.py`
- Test: `tests/dashboard/test_dataset_realtime.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/dashboard/test_dataset_realtime.py
from ema_poc.db import connect, init_schema
from ema_poc.repositories import sandbox as S
from ema_poc.dashboard.dataset import collect_dataset

ABBVIE = ["Skyrizi"]
COMP = ["Humira"]


def _seed_one_monitoring(conn):
    # Minimal monitoring response so we can assert source tagging on it.
    conn.execute("INSERT INTO questions (question_id, text, persona, therapeutic_area, "
                 "brand_focus, domain) VALUES ('Q1','q','Provider','Immunology','Skyrizi','Efficacy')")
    conn.execute("INSERT INTO responses (response_id, run_id, question_id, timestamp_utc, "
                 "llm_name, persona, question_text, therapeutic_area, brand_focus, domain, "
                 "status, response_text) VALUES "
                 "('m1','run1','Q1','2026-06-01T00:00:00+00:00','GPT','Provider','q',"
                 "'Immunology','Skyrizi','Efficacy','SUCCESS','txt')")
    conn.commit()


def _seed_one_realtime(conn):
    qid = S.create_query(conn, question_text="rt q", persona="Patient",
                         brand_focus="Skyrizi", now="2026-06-02T00:00:00+00:00",
                         status="DONE", target_count=1, started_at="2026-06-02T00:00:00+00:00")
    rid = S.save_response(conn, query_id=qid, llm_name="Claude-Opus-4.8", llm_model_version="v",
                          grounded=True, answer_text="rt ans", response_tokens=2,
                          finish_reason="stop", status="SUCCESS", now="2026-06-02T00:00:00+00:00")
    S.set_response_score(conn, sandbox_response_id=rid, sentiment_score=0.7,
                         competitive_position="LEADER", scoring_rationale="rt r",
                         brand_mentions=["Skyrizi"])
    return rid


def _ds(tmp_path):
    c = connect(str(tmp_path / "d.sqlite")); init_schema(c)
    _seed_one_monitoring(c)
    rid = _seed_one_realtime(c)
    return collect_dataset(c, abbvie_brands=ABBVIE, competitor_brands=COMP), rid


def test_monitoring_record_tagged_source(tmp_path):
    ds, _ = _ds(tmp_path)
    mon = next(r for r in ds["records"] if r["response_id"] == "m1")
    assert mon["source"] == "monitoring"


def test_realtime_record_present_and_tagged(tmp_path):
    ds, rid = _ds(tmp_path)
    rt = next(r for r in ds["records"] if r["response_id"] == "sb-" + rid)
    assert rt["source"] == "realtime"
    assert rt["llm_name"] == "Claude-Opus-4.8"
    assert rt["grounded"] is True
    assert rt["brand_focus"] == "Skyrizi"
    assert rt["persona"] == "Patient"
    assert rt["therapeutic_area"] is None
    assert rt["sentiment_score"] == 0.7
    assert rt["competitive_position"] == "LEADER"
    assert rt["brand_mentions"] == ["Skyrizi"]
    assert rt["response_text"] == "rt ans"
    assert rt["date"] == "2026-06-02"
    assert rt["hallucination_flags"] == [] and rt["alert_reasons"] == []


def test_both_sources_counted(tmp_path):
    ds, _ = _ds(tmp_path)
    assert len(ds["records"]) == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/dashboard/test_dataset_realtime.py -v`
Expected: FAIL (no `source` key; sandbox records absent; count is 1).

- [ ] **Step 3: Implement**

In `ema_poc/dashboard/dataset.py`:

(a) Add `"source": "monitoring",` to the monitoring `record` dict (anywhere inside the dict literal, e.g. right after `"response_id": rid,`).

(b) After the monitoring `for` loop that appends to `records` (just before the final `return`), append the sandbox union:
```python
    # ------------------------------------------------------------------ #
    # 7. Realtime playground (sandbox) responses — folded in, tagged      #
    # ------------------------------------------------------------------ #
    sandbox_rows = conn.execute(
        """
        SELECT sr.sandbox_response_id, sr.query_id, sr.llm_name, sr.grounded,
               sr.answer_text, sr.status, sr.sentiment_score, sr.competitive_position,
               sr.scoring_rationale, sr.brand_mentions,
               q.timestamp_utc, q.question_text, q.persona, q.brand_focus
        FROM sandbox_responses sr
        JOIN sandbox_queries q ON sr.query_id = q.query_id
        ORDER BY q.timestamp_utc ASC, sr.sandbox_response_id ASC
        """
    ).fetchall()
    for row in sandbox_rows:
        d = dict(row)
        ts = d["timestamp_utc"] or ""
        sentiment_score = d["sentiment_score"]
        if sentiment_score is not None:
            sentiment_score = float(sentiment_score)
        raw_bm = d.get("brand_mentions") or ""
        try:
            bm = json.loads(raw_bm) if raw_bm.strip() else []
        except (json.JSONDecodeError, AttributeError):
            bm = []
        records.append({
            "response_id": "sb-" + d["sandbox_response_id"],
            "timestamp_utc": ts,
            "date": ts[:10],
            "llm_name": d["llm_name"],
            "grounded": bool(d["grounded"]),
            "persona": d["persona"],
            "question_id": d["query_id"],
            "question_text": d["question_text"],
            "therapeutic_area": None,
            "brand_focus": d["brand_focus"],
            "domain": None,
            "status": d["status"],
            "response_text": d["answer_text"],
            "sentiment_score": sentiment_score,
            "competitive_position": d["competitive_position"] or None,
            "confidence_level": None,
            "citation_quality": None,
            "brand_mentions": bm,
            "scoring_rationale": d["scoring_rationale"] or None,
            "hallucination_risk": None,
            "hallucination_flags": [],
            "alert_reasons": [],
            "alert_triggered": False,
            "source": "realtime",
        })
```
(`json` is already imported at the top of the file.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/dashboard/test_dataset_realtime.py -v`
Expected: PASS.

- [ ] **Step 5: Confirm existing dataset tests still pass**

Run: `.venv/bin/python -m pytest tests/dashboard -v`
Expected: PASS (the existing `seeded` fixture has no sandbox rows, so counts/order are unchanged; the new `source` key is additive and existing tests use field-level assertions).

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest` (expect 646 + 3 new = 649).
```bash
git add ema_poc/dashboard/dataset.py tests/dashboard/test_dataset_realtime.py
git commit -m "feat: fold realtime sandbox runs into collect_dataset (source-tagged)"
```

---

### Task 4: Source filter + provenance badge (dashboard render)

**Files:**
- Modify: `ema_poc/dashboard/render.py`
- Test: `tests/dashboard/test_dashboard_render.py` (append)

- [ ] **Step 1: Write the failing test** (append to `tests/dashboard/test_dashboard_render.py`. That file already has a module `@pytest.fixture() html` returning `render_dashboard_html(_dataset())` — reuse it by taking `html` as the test arg, exactly like the existing tests):

```python
def test_dashboard_has_source_filter(html):
    assert "id='f-source'" in html
    assert ">Monitoring<" in html and ">Realtime<" in html
    assert "r.source" in html                  # filter predicate references source


def test_dashboard_source_badge_in_responses(html):
    assert ">Source<" in html                  # provenance label in the Responses detail


def test_dashboard_still_self_contained_with_source(html):
    for marker in ["http://", "https://"]:
        for line in html.splitlines():
            if marker in line:
                assert "www.w3.org/2000/svg" in line, f"external resource: {line.strip()}"
```
> Take `html` as the test parameter (the existing pytest fixture supplies the rendered string). Do NOT weaken any existing assertion. NOTE: the markup uses single-quoted attributes (`id='f-source'`), matching the existing filter selects in this file.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/dashboard/test_dashboard_render.py -k source -v`
Expected: FAIL (no `f-source` in output).

- [ ] **Step 3: Implement** (in `ema_poc/dashboard/render.py`)

(a) **Filter-bar markup** — in the `"<div class='filter-bar'>"` block, add a Source select after the Persona `<label>` line:
```python
        "<label>Source<select id='f-source'><option value=''>All</option>"
        "<option value='monitoring'>Monitoring</option>"
        "<option value='realtime'>Realtime</option></select></label>"
```

(b) **applyFilters** — add the read + predicate:
```javascript
  const source  = document.getElementById('f-source').value;
```
and inside the `.filter(function(r){ ... })`:
```javascript
    if(source && r.source !== source)           return false;
```

(c) **Change listener** — add `#f-source` to the querySelectorAll on the line that wires the filter controls:
```javascript
document.querySelectorAll('#f-ta,#f-brand,#f-llm,#f-persona,#f-source,#f-from,#f-to').forEach(function(el){
```

(d) **Reset handler** — add:
```javascript
  document.getElementById('f-source').value  = '';
```

(e) **Provenance badge in the Responses detail** — in `renderResponses`, the per-row `detail` `"<div class='detail-grid'>...</div>"` block, add a Source field (after the Question field):
```javascript
      "<div><div class='dl'>Source</div><div class='dv'>"+esc(r.source==='realtime'?'Realtime':'Monitoring')+"</div></div>" +
```

(Optional CSS: none required — reuse the existing `.dl`/`.dv` styles.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/dashboard/test_dashboard_render.py -v`
Expected: PASS (new + all existing render tests).

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest` (expect 649 + 3 new = 652).
```bash
git add ema_poc/dashboard/render.py tests/dashboard/test_dashboard_render.py
git commit -m "feat: dashboard Source filter + realtime/monitoring provenance badge"
```

---

## Self-Review Notes (author)

- **Spec coverage:** persist brand_mentions (T1 schema+repo, T2 service), union sandbox into dataset + source tag (T3), Source filter + badge (T4). All spec sections mapped.
- **Type consistency:** `set_response_score(..., brand_mentions=None)` stores `json.dumps` or NULL; service passes `result.brand_mentions`; dataset parses `sr.brand_mentions` JSON → list with the same guard as the monitoring path; record `source` ∈ {"monitoring","realtime"}; sandbox `response_id` = `"sb-"+sandbox_response_id`; render reads `r.source` and `#f-source`.
- **Backward-compat:** `brand_mentions` column nullable (additive); existing dataset tests use a monitoring-only fixture so the union appends nothing and counts/order are unchanged; the added `source` key is additive (existing tests assert fields, not exact key sets — verified `test_base_fields` and `test_top_level_keys`).
- **Realtime gaps (intentional):** `therapeutic_area=None` (→ `(none)` bucket), no hallucination/alert data, `confidence_level`/`citation_quality` None — matches the spec's "Out of scope".
