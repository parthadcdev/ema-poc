# Per-Response Rescore (Dashboard) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Rescore" button on realtime responses in the dashboard Responses view that re-runs scoring for that one response and refreshes the row + charts live.

**Architecture:** A `rescore_one` function (shares the scorer-call/persist logic with the batch `rescore_sandbox`), a `get_sandbox_response` repo read-back, a `POST /api/responses/{id}/rescore` endpoint (auth + rate-limited), and a dashboard button that POSTs then updates the in-memory `DATA` + re-renders.

**Tech Stack:** Python 3.11+, sqlite3, FastAPI, vanilla-JS self-contained dashboard. Tests offline with fakes.

**Spec:** `docs/superpowers/specs/2026-06-16-per-response-rescore-design.md`. **Branch:** `feature/per-response-rescore`.

**Run the suite with the venv:** `.venv/bin/python -m pytest`. Baseline is **676 passing**.

---

### Task 1: `rescore_one` + `get_sandbox_response` (+ DRY refactor)

**Files:**
- Modify: `ema_poc/playground/rescore.py` (extract shared scorer step; add `rescore_one`)
- Modify: `ema_poc/repositories/sandbox.py` (add `get_sandbox_response`; extract a row→dataclass helper)
- Test: `tests/playground/test_rescore.py` (append), `tests/repositories/test_sandbox_jobs.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/repositories/test_sandbox_jobs.py`:
```python
def test_get_sandbox_response_roundtrip(tmp_path):
    c = _conn(tmp_path)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus="Skyrizi",
                         now="t0", status="DONE", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="ans", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1")
    S.set_response_scoring_error(c, sandbox_response_id=rid, error="boom")
    got = S.get_sandbox_response(c, rid)
    assert got is not None and got.sandbox_response_id == rid
    assert got.scoring_error == "boom" and got.answer_text == "ans"
    assert S.get_sandbox_response(c, "missing") is None
```

Append to `tests/playground/test_rescore.py` (it already has `connect/init_schema`, `S`, `FakeScore`, `_cfg`, `_seed_unscored`):
```python
from ema_poc.playground.rescore import rescore_one


def test_rescore_one_scores_and_clears(tmp_path):
    c, rid = _seed_unscored(tmp_path)
    S.set_response_scoring_error(c, sandbox_response_id=rid, error="old")
    ok = rescore_one(c, rid, scoring_client=object(),
                     scorer=lambda *a, **k: FakeScore(), config=_cfg())
    assert ok is True
    got = S.get_sandbox_response(c, rid)
    assert got.sentiment_score == 0.5 and got.scoring_error is None


def test_rescore_one_records_error(tmp_path):
    c, rid = _seed_unscored(tmp_path)
    def boom(*a, **k): raise RuntimeError("still no credits")
    ok = rescore_one(c, rid, scoring_client=object(), scorer=boom, config=_cfg())
    assert ok is False
    got = S.get_sandbox_response(c, rid)
    assert got.sentiment_score is None and "still no credits" in got.scoring_error


def test_rescore_one_unknown_id_raises_keyerror(tmp_path):
    c, _ = _seed_unscored(tmp_path)
    import pytest
    with pytest.raises(KeyError):
        rescore_one(c, "nope", scoring_client=object(),
                    scorer=lambda *a, **k: FakeScore(), config=_cfg())
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/playground/test_rescore.py tests/repositories/test_sandbox_jobs.py -k "rescore_one or get_sandbox_response" -v`
Expected: FAIL (`rescore_one`/`get_sandbox_response` undefined).

- [ ] **Step 3: Implement the repo read-back** — in `ema_poc/repositories/sandbox.py`:

(a) Extract a row→dataclass helper (DRY) used by `list_query_responses` and the new
getter. Add it near `list_query_responses`:
```python
def _response_from_row(conn, d: dict) -> SandboxResponse:
    return SandboxResponse(
        sandbox_response_id=d["sandbox_response_id"], query_id=d["query_id"],
        llm_name=d["llm_name"], llm_model_version=d["llm_model_version"],
        grounded=bool(d["grounded"]), answer_text=d["answer_text"],
        response_tokens=d["response_tokens"], finish_reason=d["finish_reason"],
        status=d["status"], sentiment_score=d["sentiment_score"],
        competitive_position=d["competitive_position"],
        scoring_rationale=d["scoring_rationale"], created_at=d["created_at"],
        scoring_error=d.get("scoring_error"),
        citations=_citations_for(conn, d["sandbox_response_id"]),
    )
```
Refactor `list_query_responses`' loop body to `out.append(_response_from_row(conn, dict(r)))`.

(b) Add the getter:
```python
def get_sandbox_response(conn, sandbox_response_id) -> SandboxResponse | None:
    r = conn.execute("SELECT * FROM sandbox_responses WHERE sandbox_response_id = ?",
                     (sandbox_response_id,)).fetchone()
    return _response_from_row(conn, dict(r)) if r is not None else None
```

- [ ] **Step 4: Implement the rescore step** — in `ema_poc/playground/rescore.py`, extract
the per-row scorer logic and use it in both functions:
```python
def _score_response_row(conn, sandbox_response_id, answer_text, brand_focus,
                        *, scoring_client, scorer, config) -> bool:
    """Score one response row. True if scored (clears error); False if it failed
    (records scoring_error). Never raises on a scoring failure."""
    try:
        result = scorer(
            scoring_client, response_text=answer_text, brand_focus=brand_focus,
            abbvie_brands=config.brands.abbvie_brands,
            competitor_brands=config.brands.competitor_brands,
            model=config.settings.scoring_model)
        S.set_response_score(
            conn, sandbox_response_id=sandbox_response_id,
            sentiment_score=result.sentiment_score,
            competitive_position=result.competitive_position,
            scoring_rationale=result.scoring_rationale,
            brand_mentions=result.brand_mentions)
        return True
    except Exception as exc:
        S.set_response_scoring_error(conn, sandbox_response_id=sandbox_response_id,
                                     error=str(exc)[:500])
        return False


def rescore_one(conn, sandbox_response_id, *, scoring_client, scorer, config) -> bool:
    """Rescore a single sandbox response. Raises KeyError if the id is unknown."""
    row = conn.execute(
        "SELECT sr.answer_text, q.brand_focus FROM sandbox_responses sr "
        "JOIN sandbox_queries q ON sr.query_id = q.query_id "
        "WHERE sr.sandbox_response_id = ?", (sandbox_response_id,)).fetchone()
    if row is None:
        raise KeyError(sandbox_response_id)
    return _score_response_row(conn, sandbox_response_id, row["answer_text"],
                               row["brand_focus"], scoring_client=scoring_client,
                               scorer=scorer, config=config)
```
And refactor the existing `rescore_sandbox` loop body to call the shared helper:
```python
def rescore_sandbox(conn, *, scoring_client, scorer, config) -> RescoreResult:
    scored = failed = 0
    for row in S.list_unscored_sandbox(conn):
        ok = _score_response_row(conn, row["sandbox_response_id"], row["answer_text"],
                                 row["brand_focus"], scoring_client=scoring_client,
                                 scorer=scorer, config=config)
        scored += int(ok)
        failed += int(not ok)
    return RescoreResult(scored=scored, failed=failed)
```

- [ ] **Step 5: Run to verify pass + no regressions**

Run: `.venv/bin/python -m pytest tests/playground/test_rescore.py tests/repositories/test_sandbox_jobs.py -v`
Expected: PASS (incl. the EXISTING rescore_sandbox tests — the refactor preserves behavior).

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest` (expect 676 + 4 new = 680).
```bash
git add ema_poc/playground/rescore.py ema_poc/repositories/sandbox.py tests/playground/test_rescore.py tests/repositories/test_sandbox_jobs.py
git commit -m "feat: rescore_one + get_sandbox_response (shared scorer step)"
```

---

### Task 2: `POST /api/responses/{id}/rescore` endpoint

**Files:**
- Modify: `ema_poc/web/app.py`
- Test: `tests/web/test_jobs_api.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
def test_rescore_endpoint_scores_response(tmp_path):
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories import sandbox as S
    d = _deps(tmp_path)   # scorer = FakeScore() (sentiment_score=0.5)
    c = connect(d.db_path); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None, now="t0",
                         status="DONE", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="ans", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1")
    S.set_response_scoring_error(c, sandbox_response_id=rid, error="old"); c.close()
    client = TestClient(create_app(d))
    r = client.post(f"/api/responses/{rid}/rescore")
    assert r.status_code == 200
    body = r.json()
    assert body["sentiment_score"] == 0.5 and body["scoring_error"] is None
    # DB updated
    c2 = connect(d.db_path); init_schema(c2)
    assert S.get_sandbox_response(c2, rid).sentiment_score == 0.5


def test_rescore_endpoint_reports_scoring_error(tmp_path):
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories import sandbox as S
    d = _deps(tmp_path)
    d.scorer = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("credit balance too low"))
    c = connect(d.db_path); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None, now="t0",
                         status="DONE", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="ans", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1"); c.close()
    client = TestClient(create_app(d))
    r = client.post(f"/api/responses/{rid}/rescore")
    assert r.status_code == 200
    assert "credit balance too low" in r.json()["scoring_error"]


def test_rescore_endpoint_unknown_id_404(tmp_path):
    client = TestClient(create_app(_deps(tmp_path)))
    assert client.post("/api/responses/nope/rescore").status_code == 404


def test_rescore_endpoint_rate_limited(tmp_path):
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories import sandbox as S
    d = _deps(tmp_path, env={"PLAYGROUND_MAX_QUERIES_PER_HOUR": "1"})
    c = connect(d.db_path); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None, now="t0",
                         status="DONE", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="ans", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1"); c.close()
    client = TestClient(create_app(d))
    assert client.post(f"/api/responses/{rid}/rescore").status_code == 200
    assert client.post(f"/api/responses/{rid}/rescore").status_code == 429
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/web/test_jobs_api.py -k rescore_endpoint -v`
Expected: FAIL (route 404/undefined).

- [ ] **Step 3: Implement**

In `ema_poc/web/app.py`, add the import at the top (near the other `ema_poc.playground` import):
```python
from ema_poc.playground import rescore as _rescore
```
Add the route inside `create_app` (next to the other `/api/...` routes):
```python
    @app.post("/api/responses/{sandbox_response_id}/rescore")
    def rescore_response(request: Request, sandbox_response_id: str):
        cap = int((deps.env or {}).get("PLAYGROUND_MAX_QUERIES_PER_HOUR", "60") or "60")
        ip = request.client.host if request.client else "unknown"
        if not _check_rate(app.state.rate_store, ip, cap, time.time()):
            raise HTTPException(status_code=429, detail="Query limit reached — try again later.")
        conn = connect(deps.db_path)
        try:
            init_schema(conn)
            try:
                _rescore.rescore_one(conn, sandbox_response_id,
                                     scoring_client=deps.scoring_client,
                                     scorer=deps.scorer, config=deps.config)
            except KeyError:
                raise HTTPException(status_code=404, detail="response not found")
            r = S.get_sandbox_response(conn, sandbox_response_id)
        finally:
            conn.close()
        return {"sentiment_score": r.sentiment_score,
                "competitive_position": r.competitive_position,
                "scoring_rationale": r.scoring_rationale,
                "scoring_error": r.scoring_error}
```
(`HTTPException` raised inside the inner try still propagates out through the `finally`,
which closes the connection — correct.)

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/web/test_jobs_api.py -v` then full suite (expect 680 + 4 new = 684).
```bash
git add ema_poc/web/app.py tests/web/test_jobs_api.py
git commit -m "feat: POST /api/responses/{id}/rescore endpoint"
```

---

### Task 3: Dashboard Rescore button + handler

**Files:**
- Modify: `ema_poc/dashboard/render.py` (`renderResponses` detail + wiring + CSS)
- Test: `tests/dashboard/test_dashboard_render.py` (append)

- [ ] **Step 1: Write the failing test** (uses the `html` fixture):

```python
def test_responses_detail_has_rescore_button(html):
    assert "rescore-btn" in html                       # the button class
    assert "/api/responses/" in html                   # the endpoint it calls
    assert "r.source === 'realtime'" in html or "r.source==='realtime'" in html  # gated on realtime
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/dashboard/test_dashboard_render.py -k rescore -v`
Expected: FAIL.

- [ ] **Step 3: Implement** (in `ema_poc/dashboard/render.py`, `renderResponses`)

(a) In the per-row `detail` string (the `"<div class='detail-grid'>...</div>"`), add a
Rescore control for realtime rows, after the `scoring_error` conditional block:
```javascript
      (r.source === 'realtime'
        ? "<div><div class='dl'>Rescore</div><div class='dv'><button class='rescore-btn' data-id='"
          + esc(r.response_id.replace(/^sb-/, '')) + "'>Rescore</button></div></div>"
        : "") +
```

(b) After the existing "Wire row-expand clicks" block (the
`document.querySelectorAll('#view-responses tr.resp').forEach(...)`), add the rescore
wiring:
```javascript
  document.querySelectorAll('#view-responses .rescore-btn').forEach(function(btn){
    btn.addEventListener('click', function(e){
      e.stopPropagation();
      var id = btn.getAttribute('data-id');
      btn.disabled = true; btn.textContent = 'Rescoring…';
      fetch('/api/responses/' + encodeURIComponent(id) + '/rescore', {method:'POST'})
        .then(function(res){ if(!res.ok) throw new Error('HTTP '+res.status); return res.json(); })
        .then(function(data){
          var rec = DATA.records.filter(function(x){ return x.response_id === 'sb-'+id; })[0];
          if(rec){
            rec.sentiment_score = data.sentiment_score;
            rec.competitive_position = data.competitive_position;
            rec.scoring_rationale = data.scoring_rationale;
            rec.scoring_error = data.scoring_error;
          }
          render();
        })
        .catch(function(){ btn.disabled = false; btn.textContent = 'Rescore (retry)'; });
    });
  });
```

(c) Add a minimal `.rescore-btn` CSS rule in the stylesheet (theme-consistent small
button), e.g. near the `#f-reset` rule:
```python
".rescore-btn{font-family:var(--sans);font-size:12px;cursor:pointer;padding:.3rem .8rem;border:1px solid var(--rule);border-radius:var(--radius);background:var(--surface-2);color:var(--ink-soft)}"
".rescore-btn:hover{border-color:var(--accent-deep);color:var(--accent-deep)}"
".rescore-btn:disabled{opacity:.6;cursor:default}"
```
Keep the file self-contained (no external resources); keep `esc`/`safeUrl`/`renderMarkdown` intact.

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/dashboard/test_dashboard_render.py -v` then full suite (expect 684 + 1 new = 685).
```bash
git add ema_poc/dashboard/render.py tests/dashboard/test_dashboard_render.py
git commit -m "feat: dashboard Rescore button for realtime responses (live update)"
```

---

## Self-Review Notes (author)

- **Spec coverage:** rescore_one + get_sandbox_response + DRY refactor (T1); endpoint with rate-limit/404/scoring-error-as-200 (T2); dashboard button gated on realtime + live DATA update + render() (T3). All spec sections mapped.
- **Type/name consistency:** `rescore_one(conn, sandbox_response_id, *, scoring_client, scorer, config)->bool` (KeyError if unknown), `_score_response_row(...)->bool`, `get_sandbox_response(conn, id)->SandboxResponse|None`, endpoint returns `{sentiment_score, competitive_position, scoring_rationale, scoring_error}`, button `data-id` = response_id minus `sb-`, JS finds record by `'sb-'+id`. Consistent.
- **DRY:** the scorer-call/persist logic is shared by `rescore_sandbox` and `rescore_one` (`_score_response_row`); the row→dataclass build is shared by `list_query_responses` and `get_sandbox_response` (`_response_from_row`). Existing rescore_sandbox tests must stay green after the refactor (Step 5 verifies).
- **Safety:** endpoint auth-gated (app-wide) + rate-limited before any paid call; scoring failure returns 200 with `scoring_error` (UI shows it); button realtime-only; `esc()` on the data-id; self-contained preserved.
- **Known minor UX:** `render()` after rescore rebuilds the Responses table, collapsing the expanded detail row; the row's Sentiment cell still updates immediately, and re-expanding shows the new rationale/error. Acceptable for v1 (noted, not a gap).
