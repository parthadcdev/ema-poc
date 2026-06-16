# Surface Scoring Failures + Sandbox Rescore — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record and surface playground scoring failures (instead of swallowing them) and add a CLI tool to rescore unscored sandbox responses.

**Architecture:** A nullable `scoring_error` column on `sandbox_responses`, written by the playground service's scoring `except` and cleared on a successful score. It's exposed through the query-detail API (playground card) and the dashboard dataset (Responses view). A new `rescore_sandbox` function + `ema rescore-sandbox` CLI command re-runs scoring on unscored SUCCESS responses.

**Tech Stack:** Python 3.11+, sqlite3 (stdlib), FastAPI, vanilla-JS self-contained dashboard. Tests offline with fakes.

**Spec:** `docs/superpowers/specs/2026-06-16-surface-scoring-failures-design.md`. **Branch:** `feature/scoring-failures`.

**Run the suite with the venv:** `.venv/bin/python -m pytest`. Baseline is **662 passing**.

---

### Task 1: Schema + repo (scoring_error column, setter, clear-on-score, listings)

**Files:**
- Modify: `ema_poc/db.py` (`_ADDITIVE_COLUMNS`)
- Modify: `ema_poc/repositories/sandbox.py` (`SandboxResponse`, `set_response_score`, `list_query_responses`, + two new functions)
- Test: `tests/repositories/test_sandbox_jobs.py` (append)

- [ ] **Step 1: Write the failing test** (append; the file already imports `connect, init_schema` and `sandbox as S`, and has a `_conn(tmp_path)` helper):

```python
def test_set_response_scoring_error_stores_and_score_clears(tmp_path):
    c = _conn(tmp_path)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus="Skyrizi",
                         now="t0", status="RUNNING", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="a", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1")
    S.set_response_scoring_error(c, sandbox_response_id=rid, error="credit balance too low")
    got = S.list_query_responses(c, qid)[0]
    assert got.scoring_error == "credit balance too low"
    # a successful score clears the error
    S.set_response_score(c, sandbox_response_id=rid, sentiment_score=0.5,
                         competitive_position="LEADER", scoring_rationale="r",
                         brand_mentions=["Skyrizi"])
    got2 = S.list_query_responses(c, qid)[0]
    assert got2.scoring_error is None and got2.sentiment_score == 0.5


def test_list_unscored_sandbox_returns_only_rescore_candidates(tmp_path):
    c = _conn(tmp_path)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus="Skyrizi",
                         now="t0", status="RUNNING", target_count=3, started_at="t0")
    # candidate: SUCCESS, no score, has text
    cand = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                           grounded=False, answer_text="real answer", response_tokens=1,
                           finish_reason="stop", status="SUCCESS", now="t1")
    # not a candidate: already scored
    scored = S.save_response(c, query_id=qid, llm_name="B", llm_model_version="v",
                             grounded=False, answer_text="x", response_tokens=1,
                             finish_reason="stop", status="SUCCESS", now="t1")
    S.set_response_score(c, sandbox_response_id=scored, sentiment_score=0.1,
                         competitive_position="AMONG_OPTIONS", scoring_rationale="r")
    # not a candidate: FAILED (no text to score)
    S.save_response(c, query_id=qid, llm_name="C", llm_model_version="v",
                    grounded=False, answer_text="", response_tokens=0,
                    finish_reason="error", status="FAILED", now="t1")
    ids = [r["sandbox_response_id"] for r in S.list_unscored_sandbox(c)]
    assert ids == [cand]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/repositories/test_sandbox_jobs.py -k "scoring_error or unscored" -v`
Expected: FAIL (no `scoring_error` field / `set_response_scoring_error` / `list_unscored_sandbox`).

- [ ] **Step 3: Implement**

In `ema_poc/db.py`, append to `_ADDITIVE_COLUMNS`:
```python
    ("sandbox_responses", "scoring_error", "TEXT"),
```

In `ema_poc/repositories/sandbox.py`:

(a) Add a field to the `SandboxResponse` dataclass — insert `scoring_error` after
`created_at` and before `citations`:
```python
    created_at: str
    scoring_error: str | None = None
    citations: list[Citation] = field(default_factory=list)
```

(b) In `set_response_score`, add `scoring_error = NULL` to the SET clause (no new
param — a successful score clears any prior error):
```python
        """UPDATE sandbox_responses
           SET sentiment_score = ?, competitive_position = ?, scoring_rationale = ?,
               brand_mentions = ?, scoring_error = NULL
           WHERE sandbox_response_id = ?""",
```

(c) In `list_query_responses`, pass the column into the dataclass — add
`scoring_error=d.get("scoring_error")` to the `SandboxResponse(...)` constructor (e.g.
right after `created_at=d["created_at"],`):
```python
            scoring_rationale=d["scoring_rationale"], created_at=d["created_at"],
            scoring_error=d.get("scoring_error"),
            citations=_citations_for(conn, d["sandbox_response_id"]),
```

(d) Add two new functions (after `set_response_score`):
```python
def set_response_scoring_error(conn, sandbox_response_id, *, error, commit: bool = True) -> None:
    cur = conn.execute(
        "UPDATE sandbox_responses SET scoring_error = ? WHERE sandbox_response_id = ?",
        (error, sandbox_response_id))
    if cur.rowcount == 0:
        raise ValueError(f"No sandbox_response with id={sandbox_response_id!r}")
    if commit:
        conn.commit()


def list_unscored_sandbox(conn):
    """Rescore candidates: SUCCESS responses with no score yet and non-empty text,
    with their query's brand_focus. Returns sqlite Rows."""
    return conn.execute(
        """SELECT sr.sandbox_response_id, sr.answer_text, q.brand_focus
           FROM sandbox_responses sr JOIN sandbox_queries q ON sr.query_id = q.query_id
           WHERE sr.status = 'SUCCESS' AND sr.sentiment_score IS NULL
             AND TRIM(COALESCE(sr.answer_text, '')) <> ''
           ORDER BY sr.created_at, sr.sandbox_response_id""").fetchall()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/repositories/test_sandbox_jobs.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest` (expect 662 + 2 new = 664).
```bash
git add ema_poc/db.py ema_poc/repositories/sandbox.py tests/repositories/test_sandbox_jobs.py
git commit -m "feat: sandbox scoring_error column + setter/clear/list_unscored"
```

---

### Task 2: Service persists the scoring error (stop swallowing)

**Files:**
- Modify: `ema_poc/playground/service.py` (scoring `except` block)
- Test: `tests/playground/test_service_scoring_error.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/playground/test_service_scoring_error.py
from ema_poc.db import connect, init_schema
from ema_poc.playground.service import run_playground
from ema_poc.repositories import sandbox as S
from ema_poc.adapters.base import LLMResponse


class FakeAdapter:
    name = "A"; model_version = "v"; grounded = False
    def query(self, sp, q):
        return LLMResponse(text="ans", finish_reason="stop", status="SUCCESS",
                           completion_tokens=3)


def _boom_scorer(*a, **k):
    raise RuntimeError("credit balance too low")


def test_scoring_failure_is_persisted_not_swallowed(tmp_path):
    c = connect(str(tmp_path / "s.sqlite")); init_schema(c)
    list(run_playground(
        c, adapters=[FakeAdapter()], scoring_client=object(), scorer=_boom_scorer,
        abbvie_brands=[], competitor_brands=[], system_prompts={"default": "x"},
        question_text="q", persona=None, brand_focus=None, model="m",
        id_factory=lambda: __import__("uuid").uuid4().hex, now="t1",
        max_retries=0, backoff=[0]))
    row = c.execute("SELECT sentiment_score, scoring_error FROM sandbox_responses").fetchone()
    assert row[0] is None                       # still unscored
    assert "credit balance too low" in (row[1] or "")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/playground/test_service_scoring_error.py -v`
Expected: FAIL (`scoring_error` is NULL — the except swallows it).

- [ ] **Step 3: Implement**

In `ema_poc/playground/service.py`, find the scoring `except` block (it currently
yields a `score_error` event). Add the persistence call before the yield:
```python
                except Exception as exc:
                    S.set_response_scoring_error(conn, rid, error=str(exc)[:500])
                    yield {"event": "score_error", "llm_name": adapter.name, "message": str(exc)}
```
(`S` is already imported as `from ema_poc.repositories import sandbox as S`.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/playground/test_service_scoring_error.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest` (expect 664 + 1 new = 665).
```bash
git add ema_poc/playground/service.py tests/playground/test_service_scoring_error.py
git commit -m "feat: playground records the scoring-failure reason instead of swallowing it"
```

---

### Task 3: Rescore module + `ema rescore-sandbox` CLI

**Files:**
- Create: `ema_poc/playground/rescore.py`
- Modify: `ema_poc/cli.py` (add subparser + command branch + credential set)
- Test: `tests/playground/test_rescore.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/playground/test_rescore.py
from ema_poc.db import connect, init_schema
from ema_poc.repositories import sandbox as S
from ema_poc.playground.rescore import rescore_sandbox, RescoreResult
from ema_poc.config import AppConfig, Settings, BrandConfig


class FakeScore:
    sentiment_score = 0.5; competitive_position = "AMONG_OPTIONS"
    scoring_rationale = "r"; brand_mentions = ["Skyrizi"]


def _cfg():
    return AppConfig(settings=Settings(system_prompts={"default": "x"}),
                     brands=BrandConfig(abbvie_brands=["Skyrizi"], competitor_brands=[]),
                     targets=[])


def _seed_unscored(tmp_path):
    c = connect(str(tmp_path / "r.sqlite")); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus="Skyrizi",
                         now="t0", status="DONE", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="ans", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1")
    return c, rid


def test_rescore_scores_unscored_and_clears_error(tmp_path):
    c, rid = _seed_unscored(tmp_path)
    S.set_response_scoring_error(c, sandbox_response_id=rid, error="old failure")
    res = rescore_sandbox(c, scoring_client=object(), scorer=lambda *a, **k: FakeScore(),
                          config=_cfg())
    assert res == RescoreResult(scored=1, failed=0)
    got = S.list_query_responses(c, S.list_recent_queries(c)[0].query_id)[0]
    assert got.sentiment_score == 0.5 and got.scoring_error is None


def test_rescore_records_error_on_failure(tmp_path):
    c, rid = _seed_unscored(tmp_path)
    def boom(*a, **k): raise RuntimeError("still no credits")
    res = rescore_sandbox(c, scoring_client=object(), scorer=boom, config=_cfg())
    assert res == RescoreResult(scored=0, failed=1)
    row = c.execute("SELECT sentiment_score, scoring_error FROM sandbox_responses").fetchone()
    assert row[0] is None and "still no credits" in row[1]


def test_rescore_idempotent_when_nothing_unscored(tmp_path):
    c, _ = _seed_unscored(tmp_path)
    rescore_sandbox(c, scoring_client=object(), scorer=lambda *a, **k: FakeScore(), config=_cfg())
    res = rescore_sandbox(c, scoring_client=object(), scorer=lambda *a, **k: FakeScore(), config=_cfg())
    assert res == RescoreResult(scored=0, failed=0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/playground/test_rescore.py -v`
Expected: FAIL (`ema_poc.playground.rescore` does not exist).

- [ ] **Step 3: Implement the module**

```python
# ema_poc/playground/rescore.py
"""Rescore sandbox (playground) responses that were left unscored — e.g. when the
scoring API failed at run time. Idempotent: only touches SUCCESS responses with no
score yet. Per-item failures are recorded as scoring_error, never raised."""

from __future__ import annotations

from dataclasses import dataclass

from ema_poc.repositories import sandbox as S


@dataclass
class RescoreResult:
    scored: int
    failed: int


def rescore_sandbox(conn, *, scoring_client, scorer, config) -> RescoreResult:
    scored = failed = 0
    for row in S.list_unscored_sandbox(conn):
        rid = row["sandbox_response_id"]
        try:
            result = scorer(
                scoring_client, response_text=row["answer_text"],
                brand_focus=row["brand_focus"],
                abbvie_brands=config.brands.abbvie_brands,
                competitor_brands=config.brands.competitor_brands,
                model=config.settings.scoring_model)
            S.set_response_score(
                conn, sandbox_response_id=rid,
                sentiment_score=result.sentiment_score,
                competitive_position=result.competitive_position,
                scoring_rationale=result.scoring_rationale,
                brand_mentions=result.brand_mentions)
            scored += 1
        except Exception as exc:
            S.set_response_scoring_error(conn, sandbox_response_id=rid, error=str(exc)[:500])
            failed += 1
    return RescoreResult(scored=scored, failed=failed)
```

- [ ] **Step 4: Wire the CLI** (use the deps-injection pattern, exactly like `score_pending`, so it's testable with the fake string-`conn`)

In `ema_poc/cli.py`:

(a) Add an optional field to the `Deps` dataclass (after `find_run_gaps`):
```python
    rescore_sandbox: Callable | None = None
```

(b) In `default_deps()`, wire the real implementation (near the other imports/wirings).
Add the import and the field:
```python
    from ema_poc.playground.rescore import rescore_sandbox as _rescore_sandbox
    from ema_poc.scoring.scorer import score_response as _score_response
```
and in the `Deps(...)` construction add:
```python
        rescore_sandbox=lambda conn, *, client, config: _rescore_sandbox(
            conn, scoring_client=client, scorer=_score_response, config=config),
```

(c) Register the subcommand — near the other `sub.add_parser(...)` calls (after the
`run-gaps` one at line ~188):
```python
    sub.add_parser("rescore-sandbox", help="Rescore playground responses left unscored (e.g. after a scoring API failure)")
```

(d) Add `"rescore-sandbox"` to the credential-required command set (line ~215):
```python
    if args.command in ("run", "dry-run", "score", "healthcheck", "serve", "drift", "check-hallucinations", "suggest-questions", "rescore-sandbox"):
```

(e) Add the command branch — next to the `score` branch:
```python
    if args.command == "rescore-sandbox":
        conn = _open_db(deps, config)
        client = deps.make_scoring_client(deps.env)
        r = deps.rescore_sandbox(conn, client=client, config=config)
        deps.out(f"Rescored {r.scored}, still failed {r.failed}")
        return 0
```

- [ ] **Step 5: Test the CLI wiring** (append to `tests/test_cli.py` — it has a
`_fake_deps(**overrides)` helper building a `Deps` with fakes; `connect=lambda p:"CONN"`,
`make_scoring_client=lambda env:"CLIENT"`, and a `score` command test to mirror):

```python
def test_rescore_sandbox_command():
    from ema_poc.playground.rescore import RescoreResult
    calls = {}
    def _rescore(conn, *, client, config):
        calls["conn"] = conn; calls["client"] = client
        return RescoreResult(scored=3, failed=1)
    deps, out, _ = _fake_deps(rescore_sandbox=_rescore)
    rc = main(["rescore-sandbox"], deps=deps)
    assert rc == 0
    assert calls["conn"] == "CONN" and calls["client"] == "CLIENT"   # _open_db + scoring client wired
    assert any("Rescored 3" in line and "failed 1" in line for line in out)
```

- [ ] **Step 6: Run + commit**

Run: `.venv/bin/python -m pytest tests/playground/test_rescore.py tests/test_cli.py -v`
then `.venv/bin/python -m pytest` (expect all green).
```bash
git add ema_poc/playground/rescore.py ema_poc/cli.py tests/playground/test_rescore.py tests/test_cli.py
git commit -m "feat: ema rescore-sandbox to rescore unscored playground responses"
```

---

### Task 4: API exposes scoring_error

**Files:**
- Modify: `ema_poc/web/app.py` (`query_detail` responses dict, ~line 180)
- Test: `tests/web/test_jobs_api.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_query_detail_includes_scoring_error(tmp_path):
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories import sandbox as S
    d = _deps(tmp_path)
    # seed a query + a SUCCESS response with a scoring_error directly
    c = connect(d.db_path); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None, now="t0",
                         status="DONE", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="a", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1")
    S.set_response_scoring_error(c, sandbox_response_id=rid, error="credit balance too low")
    c.close()
    client = TestClient(create_app(d))
    detail = client.get(f"/api/queries/{qid}").json()
    assert detail["responses"][0]["scoring_error"] == "credit balance too low"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/web/test_jobs_api.py -k scoring_error -v`
Expected: FAIL (`scoring_error` key absent).

- [ ] **Step 3: Implement**

In `ema_poc/web/app.py`, in the `query_detail` `responses` list comprehension, add the
field (e.g. after `"scoring_rationale": r.scoring_rationale,`):
```python
                 "scoring_rationale": r.scoring_rationale,
                 "scoring_error": r.scoring_error,
```

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/web/test_jobs_api.py -v` then full suite.
```bash
git add ema_poc/web/app.py tests/web/test_jobs_api.py
git commit -m "feat: expose scoring_error on the query-detail API"
```

---

### Task 5: Playground UI shows the scoring failure

**Files:**
- Modify: `ema_poc/web/static/index.html` (`renderAnswerCard`)
- Test: `tests/web/test_index_jobs.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_index_renders_scoring_error():
    from pathlib import Path
    html = Path("ema_poc/web/static/index.html").read_text()
    assert "scoring_error" in html              # the card reads/handles it
    assert "Scoring failed" in html             # the user-facing label
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/web/test_index_jobs.py -k scoring_error -v`
Expected: FAIL.

- [ ] **Step 3: Implement** — READ the existing `renderAnswerCard(ev)` in
`ema_poc/web/static/index.html` first. It builds the answer card from a response object
(which now includes `scoring_error` from Task 4). Where it renders the score/sentiment,
add: when `ev.scoring_error` is set, render a warning line INSTEAD of the (absent)
score, using the existing `esc()` helper and the card's existing styling conventions:
```javascript
      (ev.scoring_error
        ? "<div class='score-fail'>⚠ Scoring failed: " + esc(ev.scoring_error) + "</div>"
        : /* existing score/sentiment markup */ )
```
Wire it into the card's existing structure (don't duplicate the score block); add a
minimal `.score-fail` style consistent with the file's theme if needed. Keep the file
self-contained (no external resources) and keep `esc`/`safeUrl`/`renderMarkdown` intact.

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/web/test_index_jobs.py -v` then full suite.
```bash
git add ema_poc/web/static/index.html tests/web/test_index_jobs.py
git commit -m "feat: playground answer card shows 'Scoring failed' with the reason"
```

---

### Task 6: Dashboard surfaces scoring_error (dataset + Responses detail)

**Files:**
- Modify: `ema_poc/dashboard/dataset.py` (monitoring + sandbox record dicts)
- Modify: `ema_poc/dashboard/render.py` (`renderResponses` detail panel)
- Test: `tests/dashboard/test_dataset_realtime.py`, `tests/dashboard/test_dataset.py`, `tests/dashboard/test_dashboard_render.py`

- [ ] **Step 1: Write the failing dataset test** (append to `tests/dashboard/test_dataset_realtime.py`; it has `_ds(tmp_path)` returning `(dataset, rid)` and seeds one monitoring + one realtime row):

```python
def test_records_carry_scoring_error_key(tmp_path):
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories import sandbox as S
    from ema_poc.dashboard.dataset import collect_dataset
    c = connect(str(tmp_path / "se.sqlite")); init_schema(c)
    _seed_one_monitoring(c)
    qid = S.create_query(c, question_text="rt", persona=None, brand_focus=None,
                         now="2026-06-02T00:00:00+00:00", status="DONE",
                         target_count=1, started_at="2026-06-02T00:00:00+00:00")
    rid = S.save_response(c, query_id=qid, llm_name="X", llm_model_version="v",
                          grounded=False, answer_text="a", response_tokens=1,
                          finish_reason="stop", status="SUCCESS",
                          now="2026-06-02T00:00:00+00:00")
    S.set_response_scoring_error(c, sandbox_response_id=rid, error="credit balance too low")
    ds = collect_dataset(c, abbvie_brands=ABBVIE, competitor_brands=COMP)
    rt = next(r for r in ds["records"] if r["response_id"] == "sb-" + rid)
    mon = next(r for r in ds["records"] if r["response_id"] == "m1")
    assert rt["scoring_error"] == "credit balance too low"
    assert mon["scoring_error"] is None
    assert set(mon.keys()) == set(rt.keys())     # key parity preserved
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/dashboard/test_dataset_realtime.py -k scoring_error -v`
Expected: FAIL (no `scoring_error` key).

- [ ] **Step 3: Implement dataset**

In `ema_poc/dashboard/dataset.py`:
- Add `"scoring_error": None,` to the MONITORING record dict.
- In the sandbox SELECT, add `sr.scoring_error` to the column list.
- Add `"scoring_error": d["scoring_error"],` to the sandbox (realtime) record dict.

Then update the exact-key contract in `tests/dashboard/test_dataset.py`: its
`REQUIRED_KEYS` set must gain `"scoring_error"` (24 → 25 keys). Read that test and add
the single key (do not loosen the exact-set assertion).

- [ ] **Step 4: Run dataset tests**

Run: `.venv/bin/python -m pytest tests/dashboard/test_dataset_realtime.py tests/dashboard/test_dataset.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing render test** (append to `tests/dashboard/test_dashboard_render.py`, uses the `html` fixture):

```python
def test_responses_detail_shows_scoring_error(html):
    # the Responses detail panel must surface a scoring_error when present
    assert "scoring_error" in html
    assert "Scoring failed" in html
```

- [ ] **Step 6: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/dashboard/test_dashboard_render.py -k scoring_error -v`
Expected: FAIL.

- [ ] **Step 7: Implement render**

In `ema_poc/dashboard/render.py`, in `renderResponses`' per-row `detail` block (the
`"<div class='detail-grid'>...</div>"`), add a conditional Scoring-failed field after
the existing Scoring Rationale field:
```javascript
      (r.scoring_error
        ? "<div><div class='dl'>Scoring failed</div><div class='dv'>"+esc(r.scoring_error)+"</div></div>"
        : "") +
```
Use `esc()`; reuse `.dl`/`.dv`. Keep self-contained.

- [ ] **Step 8: Run + commit**

Run: `.venv/bin/python -m pytest tests/dashboard -v` then full suite (expect all green).
```bash
git add ema_poc/dashboard/dataset.py ema_poc/dashboard/render.py tests/dashboard/test_dataset_realtime.py tests/dashboard/test_dataset.py tests/dashboard/test_dashboard_render.py
git commit -m "feat: dashboard surfaces realtime scoring_error in the Responses detail"
```

---

## Self-Review Notes (author)

- **Spec coverage:** schema+repo incl. clear-on-score, setter, list_unscored (T1); service persistence (T2); rescore module + CLI + credential set (T3); API field (T4); playground card (T5); dataset key-parity + render detail (T6). All spec sections mapped.
- **Type/name consistency:** `set_response_scoring_error(conn, sandbox_response_id, *, error)`, `list_unscored_sandbox(conn)->Rows`, `SandboxResponse.scoring_error`, `rescore_sandbox(conn, *, scoring_client, scorer, config)->RescoreResult(scored, failed)`, CLI `rescore-sandbox`, API/UI/dataset key `scoring_error`. Consistent across tasks.
- **Backward-compat:** `scoring_error` column additive/nullable (T1); monitoring records get `scoring_error=None` for key parity (T6); the exact-key contract is updated, not loosened.
- **Idempotency/safety:** `list_unscored_sandbox` only returns SUCCESS + null-sentiment + non-empty-text; `rescore_sandbox` never raises per-item; `set_response_score` clears the error on success.
- **CLI testability:** `rescore-sandbox` uses the deps-injection pattern (`deps.rescore_sandbox`, mirroring `deps.score_pending`), so the CLI test works with the fake string-`conn`; the real rescore logic is tested directly in `test_rescore.py`. No placeholders remain.
- **Concrete code throughout:** every step has runnable code; the only "read first" notes (renderAnswerCard in T5, the contract test in T6) point at existing structures the implementer adapts, with the exact additions shown.
