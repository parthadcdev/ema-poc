# Evidence Monitoring Agent — Dashboard Implementation Plan (Phase 7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a single self-contained HTML dashboard from the repository data — sentiment by LLM and therapy, competitive positioning by LLM, alert count + flagged list, response volume over time — with client-side filtering (persona/TA/LLM/date) and click-to-expand response detail, exposed via an `ema dashboard` command (FR-6: FR-601–605).

**Architecture:** `ema_poc/dashboard/` with three focused modules: `data.py` (query + aggregate into a `DashboardData` structure), `render.py` (pure `render_dashboard_html(data) -> str` producing one self-contained HTML document — inline CSS + vanilla JS, no external `<script src>`/`<link>`), and `build.py` (`build_dashboard(conn, out_path)` glue). The `ema dashboard --out` command wires through the existing injectable `Deps`. Charts are rendered as inline CSS bars / HTML tables (no JS charting library) so the file is fully offline-viewable. All rendered content is HTML-escaped.

**Tech Stack:** Python 3.11+, stdlib `sqlite3` + `html`. Built on Phases 1–6 (merged to `develop`). Pure functions are unit-tested; no network.

**Spec:** `docs/superpowers/specs/2026-06-13-evidence-monitoring-agent-poc-design.md` (§6 dashboard, FR-6).

**Conventions:**
- The dashboard reads the response rows' denormalized scoring columns (`sentiment_score`, `competitive_position`, `alert_triggered`) populated by Phase 5, plus the latest score's `scoring_rationale`.
- Self-contained: no remote resources; everything inline. All dynamic content escaped via `html.escape`.
- Activate the venv with `. .venv/bin/activate` before pytest.

---

### Task 1: Dashboard data collection + aggregation

**Files:**
- Create: `ema_poc/dashboard/__init__.py`
- Create: `ema_poc/dashboard/data.py`
- Test: `tests/dashboard/__init__.py`
- Test: `tests/dashboard/test_dashboard_data.py`

- [ ] **Step 1: Write the failing test**

`tests/dashboard/__init__.py`:
```python
```

`tests/dashboard/test_dashboard_data.py`:
```python
from ema_poc.dashboard.data import build_dashboard_data
from ema_poc.db import connect, init_schema
from ema_poc.models import Alert, Response, Score
from ema_poc.repositories.alerts import save_alert
from ema_poc.repositories.responses import save_response, update_response_scoring
from ema_poc.repositories.runs import create_run
from ema_poc.repositories.scores import save_score

T1 = "2026-06-13T01:00:00+00:00"
T2 = "2026-06-14T02:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=T1)
    return conn


def _resp(conn, rid, *, llm, ts, brand, text="ans"):
    save_response(conn, Response(
        response_id=rid, run_id="r1", timestamp_utc=ts, llm_name=llm,
        llm_model_version="m", persona="Provider", question_id="Q1",
        question_text="q", therapeutic_area="Immunology", brand_focus=brand,
        domain="Safety", response_text=text, response_tokens=1,
        finish_reason="stop", status="SUCCESS", created_at=ts,
    ))


def _score_and_denorm(conn, rid, *, sentiment, position, alert, rationale="why"):
    save_score(conn, Score(
        score_id=f"{rid}-s1", response_id=rid, version=1, sentiment_score=sentiment,
        competitive_position=position, brand_mentions=["Skyrizi"], key_claims=["c"],
        scoring_rationale=rationale, scoring_model="claude-opus-4-8", created_at=T1,
    ))
    update_response_scoring(conn, rid, sentiment_score=sentiment,
                            competitive_position=position, alert_triggered=alert)


def test_build_dashboard_data_aggregates(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "a", llm="GPT-4o", ts=T1, brand="Skyrizi")
    _score_and_denorm(conn, "a", sentiment=0.8, position="FIRST_LINE_RECOMMENDED", alert=False)
    _resp(conn, "b", llm="Gemini", ts=T1, brand="Skyrizi")
    _score_and_denorm(conn, "b", sentiment=-0.6, position="NOT_RECOMMENDED", alert=True,
                      rationale="negative")
    save_alert(conn, Alert(alert_id="al-1", score_id="b-s1",
                           reason="SENTIMENT_BELOW_THRESHOLD", created_at=T1))
    _resp(conn, "c", llm="GPT-4o", ts=T2, brand="Rinvoq")
    _score_and_denorm(conn, "c", sentiment=0.2, position="AMONG_OPTIONS", alert=False)

    data = build_dashboard_data(conn)

    assert data.total_responses == 3
    assert data.total_alerts == 1
    # sentiment by LLM: GPT-4o mean of 0.8 and 0.2 = 0.5; Gemini = -0.6
    assert data.sentiment_by_llm["GPT-4o"] == 0.5
    assert data.sentiment_by_llm["Gemini"] == -0.6
    # sentiment by therapy (brand_focus)
    assert round(data.sentiment_by_therapy["Skyrizi"], 3) == round((0.8 + -0.6) / 2, 3)
    assert data.sentiment_by_therapy["Rinvoq"] == 0.2
    # competitive position counts by LLM
    assert data.position_by_llm["GPT-4o"]["FIRST_LINE_RECOMMENDED"] == 1
    assert data.position_by_llm["GPT-4o"]["AMONG_OPTIONS"] == 1
    assert data.position_by_llm["Gemini"]["NOT_RECOMMENDED"] == 1
    # volume by date
    assert data.volume_by_date["2026-06-13"] == 2
    assert data.volume_by_date["2026-06-14"] == 1
    # alert list carries the reason + rationale on the row
    assert data.alerts[0]["response_id"] == "b"
    assert data.alerts[0]["reason"] == "SENTIMENT_BELOW_THRESHOLD"
    # rows carry the latest scoring rationale
    row_b = next(r for r in data.rows if r["response_id"] == "b")
    assert row_b["scoring_rationale"] == "negative"

    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/dashboard/test_dashboard_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.dashboard'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/dashboard/__init__.py`:
```python
"""Dashboard — self-contained HTML report of monitoring results (§6, FR-6)."""
```

`ema_poc/dashboard/data.py`:
```python
"""Query + aggregate repository data for the dashboard (FR-602)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass
class DashboardData:
    rows: list[dict] = field(default_factory=list)
    sentiment_by_llm: dict = field(default_factory=dict)
    sentiment_by_therapy: dict = field(default_factory=dict)
    position_by_llm: dict = field(default_factory=dict)
    volume_by_date: dict = field(default_factory=dict)
    alerts: list[dict] = field(default_factory=list)
    total_responses: int = 0
    total_alerts: int = 0


def _alert_reasons(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT r.response_id AS response_id, a.reason AS reason
        FROM alerts a
        JOIN scores s ON a.score_id = s.score_id
        JOIN responses r ON s.response_id = r.response_id
        """
    ).fetchall()
    return {r["response_id"]: r["reason"] for r in rows}


def collect_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT r.response_id, r.llm_name, r.persona, r.therapeutic_area,
               r.brand_focus, r.domain, r.timestamp_utc, r.status,
               r.sentiment_score, r.competitive_position, r.alert_triggered,
               r.response_text,
               (SELECT scoring_rationale FROM scores s
                WHERE s.response_id = r.response_id
                ORDER BY version DESC LIMIT 1) AS scoring_rationale
        FROM responses r
        ORDER BY r.timestamp_utc ASC, r.response_id ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_dashboard_data(conn: sqlite3.Connection) -> DashboardData:
    rows = collect_rows(conn)
    reasons = _alert_reasons(conn)

    by_llm: dict[str, list[float]] = {}
    by_therapy: dict[str, list[float]] = {}
    position_by_llm: dict[str, dict[str, int]] = {}
    volume_by_date: dict[str, int] = {}

    for r in rows:
        if r["sentiment_score"] is not None:
            by_llm.setdefault(r["llm_name"], []).append(r["sentiment_score"])
            by_therapy.setdefault(r["brand_focus"] or "Unknown", []).append(
                r["sentiment_score"]
            )
        if r["competitive_position"]:
            counts = position_by_llm.setdefault(r["llm_name"], {})
            counts[r["competitive_position"]] = (
                counts.get(r["competitive_position"], 0) + 1
            )
        date = (r["timestamp_utc"] or "")[:10]
        volume_by_date[date] = volume_by_date.get(date, 0) + 1

    sentiment_by_llm = {k: round(_mean(v), 3) for k, v in by_llm.items()}
    sentiment_by_therapy = {k: round(_mean(v), 3) for k, v in by_therapy.items()}

    alerts = [
        {
            "response_id": r["response_id"],
            "llm_name": r["llm_name"],
            "reason": reasons.get(r["response_id"], "ALERT"),
            "rationale": r["scoring_rationale"],
        }
        for r in rows
        if r["alert_triggered"]
    ]

    return DashboardData(
        rows=rows,
        sentiment_by_llm=sentiment_by_llm,
        sentiment_by_therapy=sentiment_by_therapy,
        position_by_llm=position_by_llm,
        volume_by_date=volume_by_date,
        alerts=alerts,
        total_responses=len(rows),
        total_alerts=len(alerts),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/dashboard/test_dashboard_data.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/dashboard/__init__.py ema_poc/dashboard/data.py tests/dashboard/__init__.py tests/dashboard/test_dashboard_data.py
git commit -m "feat: dashboard data collection and aggregation"
```

---

### Task 2: Self-contained HTML rendering

**Files:**
- Create: `ema_poc/dashboard/render.py`
- Test: `tests/dashboard/test_dashboard_render.py`

- [ ] **Step 1: Write the failing test**

`tests/dashboard/test_dashboard_render.py`:
```python
from ema_poc.dashboard.data import DashboardData
from ema_poc.dashboard.render import render_dashboard_html


def _data():
    return DashboardData(
        rows=[
            {
                "response_id": "a", "llm_name": "GPT-4o", "persona": "Provider",
                "therapeutic_area": "Immunology", "brand_focus": "Skyrizi",
                "domain": "Safety", "timestamp_utc": "2026-06-13T01:00:00+00:00",
                "status": "SUCCESS", "sentiment_score": 0.8,
                "competitive_position": "FIRST_LINE_RECOMMENDED", "alert_triggered": 0,
                "response_text": "Skyrizi is <b>first-line</b>.",
                "scoring_rationale": "positive & clear",
            },
        ],
        sentiment_by_llm={"GPT-4o": 0.8}, sentiment_by_therapy={"Skyrizi": 0.8},
        position_by_llm={"GPT-4o": {"FIRST_LINE_RECOMMENDED": 1}},
        volume_by_date={"2026-06-13": 1},
        alerts=[{"response_id": "b", "llm_name": "Gemini",
                 "reason": "SENTIMENT_BELOW_THRESHOLD", "rationale": "neg"}],
        total_responses=1, total_alerts=1,
    )


def test_render_produces_self_contained_html():
    html = render_dashboard_html(_data())
    assert html.startswith("<!DOCTYPE html>")
    # self-contained: no external scripts/styles
    assert "<script src" not in html
    assert "<link" not in html
    assert "http://" not in html
    assert "https://" not in html.replace("2026-06-13T01:00:00+00:00", "")  # only data ts has +00:00, no urls


def test_render_includes_sections_and_data():
    html = render_dashboard_html(_data())
    assert "Evidence Monitoring Dashboard" in html
    assert "Sentiment by LLM" in html
    assert "Competitive positioning by LLM" in html
    assert "Response volume over time" in html
    assert "GPT-4o" in html
    assert "FIRST_LINE_RECOMMENDED" in html
    assert "SENTIMENT_BELOW_THRESHOLD" in html  # alert reason
    # filter controls present (FR-604)
    assert "id='f-persona'" in html or 'id="f-persona"' in html
    assert "id='f-llm'" in html or 'id="f-llm"' in html


def test_render_escapes_response_content():
    html = render_dashboard_html(_data())
    # the literal <b> in response_text must be escaped, not injected as a tag
    assert "&lt;b&gt;first-line&lt;/b&gt;" in html
    assert "positive &amp; clear" in html  # rationale escaped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. .venv/bin/activate && pytest tests/dashboard/test_dashboard_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ema_poc.dashboard.render'`.

- [ ] **Step 3: Write the implementation**

`ema_poc/dashboard/render.py`:
```python
"""Render DashboardData into one self-contained HTML document (FR-601/603/604/605).

Charts are inline CSS bars / HTML tables (no JS chart library, no external
resources). All dynamic content is HTML-escaped. Filtering and row expansion
use small inline vanilla JS."""

from __future__ import annotations

import html

from ema_poc.dashboard.data import DashboardData

_CSS = """<style>
body{font-family:system-ui,Arial,sans-serif;margin:2rem;color:#222;background:#faf9f7}
h1{margin-bottom:.2rem}
.summary{font-size:18px;margin-top:0}
.section{margin:2rem 0}
.bar-row{display:flex;align-items:center;margin:2px 0}
.bar-label{width:180px;font-size:13px}
.bar{height:14px;background:#4a8a6f;margin:0 8px;border-radius:3px;min-width:1px}
.bar.neg{background:#c0584f}
.bar-val{font-size:12px;color:#555}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:.5rem}
th,td{border:1px solid #ddd;padding:4px 8px;text-align:left;vertical-align:top}
tr.resp{cursor:pointer}
tr.resp:hover{background:#f0ede6}
tr.detail td{background:#f4f1ea;font-size:12px;white-space:pre-wrap}
.controls{margin:1rem 0;font-size:13px}
.controls label{margin-right:12px}
.alert{color:#b00}
</style>"""

_JS = """<script>
function applyFilters(){
  var p=document.getElementById('f-persona').value;
  var t=document.getElementById('f-ta').value;
  var l=document.getElementById('f-llm').value;
  var df=document.getElementById('f-from').value;
  var dt=document.getElementById('f-to').value;
  document.querySelectorAll('tr.resp').forEach(function(row){
    var d=row.dataset;
    var show=(!p||d.persona===p)&&(!t||d.ta===t)&&(!l||d.llm===l)&&(!df||d.date>=df)&&(!dt||d.date<=dt);
    row.style.display=show?'':'none';
    var det=row.nextElementSibling;
    if(det&&det.classList.contains('detail')) det.style.display='none';
  });
}
document.addEventListener('DOMContentLoaded',function(){
  document.querySelectorAll('.controls select,.controls input').forEach(function(el){
    el.addEventListener('change',applyFilters); el.addEventListener('input',applyFilters);
  });
  document.querySelectorAll('tr.resp').forEach(function(row){
    row.addEventListener('click',function(){
      var det=row.nextElementSibling;
      if(det&&det.classList.contains('detail'))
        det.style.display=(!det.style.display||det.style.display==='none')?'table-row':'none';
    });
  });
});
</script>"""


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _bars(d: dict, *, signed: bool = False) -> str:
    if not d:
        return "<p>No data.</p>"
    mx = max((abs(v) for v in d.values()), default=1) or 1
    out = []
    for k, v in d.items():
        pct = abs(v) / mx * 100
        cls = "bar neg" if (signed and isinstance(v, (int, float)) and v < 0) else "bar"
        val = ("%.3f" % v) if isinstance(v, float) else _e(v)
        out.append(
            "<div class='bar-row'><span class='bar-label'>" + _e(k)
            + "</span><span class='" + cls + "' style='width:" + ("%.0f" % pct)
            + "%'></span><span class='bar-val'>" + val + "</span></div>"
        )
    return "\n".join(out)


def _position_table(pos: dict) -> str:
    if not pos:
        return "<p>No data.</p>"
    positions = sorted({p for counts in pos.values() for p in counts})
    head = "<tr><th>LLM</th>" + "".join("<th>" + _e(p) + "</th>" for p in positions) + "</tr>"
    body = ""
    for llm, counts in pos.items():
        body += (
            "<tr><td>" + _e(llm) + "</td>"
            + "".join("<td>" + str(counts.get(p, 0)) + "</td>" for p in positions)
            + "</tr>"
        )
    return "<table>" + head + body + "</table>"


def _alerts_table(alerts: list[dict]) -> str:
    if not alerts:
        return "<p>No alerts.</p>"
    body = "".join(
        "<tr><td>" + _e(a["response_id"]) + "</td><td>" + _e(a["llm_name"])
        + "</td><td class='alert'>" + _e(a["reason"]) + "</td></tr>"
        for a in alerts
    )
    return "<table><tr><th>Response</th><th>LLM</th><th>Reason</th></tr>" + body + "</table>"


def _select(el_id: str, label: str, options) -> str:
    opts = "<option value=''>All</option>" + "".join(
        "<option value='" + _e(o) + "'>" + _e(o) + "</option>" for o in options
    )
    return "<label>" + _e(label) + ": <select id='" + el_id + "'>" + opts + "</select></label>"


def _responses_table(rows: list[dict]) -> str:
    personas = sorted({r["persona"] for r in rows if r["persona"]})
    tas = sorted({r["therapeutic_area"] for r in rows if r["therapeutic_area"]})
    llms = sorted({r["llm_name"] for r in rows if r["llm_name"]})
    controls = (
        "<div class='controls'>"
        + _select("f-persona", "Persona", personas)
        + _select("f-ta", "Therapeutic area", tas)
        + _select("f-llm", "LLM", llms)
        + "<label>From <input type='date' id='f-from'></label>"
        + "<label>To <input type='date' id='f-to'></label>"
        + "</div>"
    )
    head = ("<tr><th>Time</th><th>LLM</th><th>Persona</th><th>Brand</th>"
            "<th>Status</th><th>Sentiment</th><th>Position</th></tr>")
    body = ""
    for r in rows:
        date = (r["timestamp_utc"] or "")[:10]
        mark = " ⚠" if r["alert_triggered"] else ""
        sentiment = "" if r["sentiment_score"] is None else _e(r["sentiment_score"])
        body += (
            "<tr class='resp' data-persona='" + _e(r["persona"]) + "' data-ta='"
            + _e(r["therapeutic_area"]) + "' data-llm='" + _e(r["llm_name"])
            + "' data-date='" + _e(date) + "'>"
            + "<td>" + _e(r["timestamp_utc"]) + "</td><td>" + _e(r["llm_name"])
            + "</td><td>" + _e(r["persona"]) + "</td><td>" + _e(r["brand_focus"])
            + "</td><td>" + _e(r["status"]) + mark + "</td><td>" + sentiment
            + "</td><td>" + _e(r["competitive_position"]) + "</td></tr>"
        )
        detail = ("Response: " + _e(r["response_text"]) + "\n\nRationale: "
                  + _e(r["scoring_rationale"]))
        body += ("<tr class='detail' style='display:none'><td colspan='7'>"
                 + detail + "</td></tr>")
    return controls + "<table>" + head + body + "</table>"


def render_dashboard_html(data: DashboardData) -> str:
    parts = [
        "<!DOCTYPE html>",
        "<html lang='en'><head><meta charset='utf-8'>"
        "<title>Evidence Monitoring Dashboard</title>",
        _CSS,
        "</head><body>",
        "<h1>Evidence Monitoring Dashboard</h1>",
        "<p class='summary'>" + str(data.total_responses)
        + " responses &middot; <span class='alert'>" + str(data.total_alerts)
        + " alerts</span></p>",
        "<div class='section'><h2>Sentiment by LLM</h2>"
        + _bars(data.sentiment_by_llm, signed=True) + "</div>",
        "<div class='section'><h2>Sentiment by therapy</h2>"
        + _bars(data.sentiment_by_therapy, signed=True) + "</div>",
        "<div class='section'><h2>Competitive positioning by LLM</h2>"
        + _position_table(data.position_by_llm) + "</div>",
        "<div class='section'><h2>Response volume over time</h2>"
        + _bars(data.volume_by_date) + "</div>",
        "<div class='section'><h2>Alerts (" + str(data.total_alerts) + ")</h2>"
        + _alerts_table(data.alerts) + "</div>",
        "<div class='section'><h2>Responses</h2>"
        + _responses_table(data.rows) + "</div>",
        _JS,
        "</body></html>",
    ]
    return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. .venv/bin/activate && pytest tests/dashboard/test_dashboard_render.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/dashboard/render.py tests/dashboard/test_dashboard_render.py
git commit -m "feat: self-contained HTML dashboard rendering"
```

---

### Task 3: build_dashboard + `ema dashboard` CLI command

**Files:**
- Create: `ema_poc/dashboard/build.py`
- Modify: `ema_poc/cli.py` (add `build_dashboard` to `Deps` + `default_deps`, the `dashboard` subparser, and the dispatch branch)
- Test: `tests/dashboard/test_dashboard_build.py`
- Test: `tests/test_cli_dashboard.py`

- [ ] **Step 1: Write the failing tests**

`tests/dashboard/test_dashboard_build.py`:
```python
from ema_poc.dashboard.build import build_dashboard
from ema_poc.db import connect, init_schema
from ema_poc.models import Response
from ema_poc.repositories.responses import save_response
from ema_poc.repositories.runs import create_run

NOW = "2026-06-13T02:00:00+00:00"


def test_build_dashboard_writes_html_file(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=NOW)
    save_response(conn, Response(
        response_id="a", run_id="r1", timestamp_utc=NOW, llm_name="GPT-4o",
        llm_model_version="m", persona="Provider", question_id="Q1",
        question_text="q", brand_focus="Skyrizi", domain="Safety",
        response_text="ans", response_tokens=1, finish_reason="stop",
        status="SUCCESS", created_at=NOW,
    ))
    out = tmp_path / "dash.html"
    returned = build_dashboard(conn, str(out))
    assert returned == str(out)
    html = out.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "GPT-4o" in html
    conn.close()
```

`tests/test_cli_dashboard.py`:
```python
from ema_poc.cli import Deps, main


class _Config:
    class settings:
        db_path = "ema.sqlite"


def test_dashboard_command_invokes_build_and_reports(tmp_path):
    calls = {}
    out = []

    def _build(conn, out_path):
        calls["out_path"] = out_path
        return out_path

    deps = Deps(
        load_config=lambda d: _Config(),
        connect=lambda p: "CONN",
        init_schema=lambda c: None,
        validate_credentials=lambda config, env: (_ for _ in ()).throw(
            AssertionError("dashboard must not validate credentials")),
        build_adapters=lambda config, env: [],
        make_scoring_client=lambda env: None,
        run=lambda *a, **k: None,
        score_pending=lambda *a, **k: None,
        check_targets=lambda adapters: [],
        import_csv=lambda c, p: 0,
        import_excel=lambda c, p: 0,
        env={},
        out=out.append,
        build_dashboard=_build,
    )
    rc = main(["dashboard", "--out", str(tmp_path / "d.html")], deps=deps)
    assert rc == 0
    assert calls["out_path"] == str(tmp_path / "d.html")
    assert any("Dashboard written" in line for line in out)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/dashboard/test_dashboard_build.py tests/test_cli_dashboard.py -v`
Expected: FAIL — `ema_poc.dashboard.build` missing and `Deps` has no `build_dashboard` field.

- [ ] **Step 3a: Write `ema_poc/dashboard/build.py`**

```python
"""Build the self-contained HTML dashboard from the repository (FR-601/603)."""

from __future__ import annotations

import sqlite3

from ema_poc.dashboard.data import build_dashboard_data
from ema_poc.dashboard.render import render_dashboard_html


def build_dashboard(conn: sqlite3.Connection, out_path: str) -> str:
    """Render the dashboard for all data in `conn` and write it to `out_path`.
    Returns the path written."""
    html = render_dashboard_html(build_dashboard_data(conn))
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out_path
```

- [ ] **Step 3b: Modify `ema_poc/cli.py`**

(i) Add a `build_dashboard` field to the `Deps` dataclass as the LAST field, with a default (so existing `Deps(...)` constructions in other tests keep working):
```python
    build_dashboard: Callable | None = None
```
(Add it immediately after the `out: Callable` line.)

(ii) In `default_deps()`, add the import and wire the field. Add to the imports inside the function:
```python
    from ema_poc.dashboard.build import build_dashboard
```
and add `build_dashboard=build_dashboard,` to the returned `Deps(...)`.

(iii) In `_parse_args`, register the `dashboard` subparser (alongside the others, e.g. after the `import-questions` parser):
```python
    p_dash = sub.add_parser("dashboard", help="Generate the self-contained HTML dashboard")
    p_dash.add_argument("--out", default="dashboard.html")
```

(iv) In `main`, add a dispatch branch for `dashboard` (it needs the DB but NOT credentials; place it after the `import-questions` branch and before the `dry-run/healthcheck` branch):
```python
    if args.command == "dashboard":
        conn = _open_db(deps, config)
        path = deps.build_dashboard(conn, args.out)
        deps.out(f"Dashboard written to {path}")
        return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/dashboard/test_dashboard_build.py tests/test_cli_dashboard.py -v`
Expected: PASS (1 + 1 = 2 passed). Then `. .venv/bin/activate && pytest -q` (confirm the existing CLI tests still pass — the new `Deps` field has a default so they are unaffected).

- [ ] **Step 5: Commit**

```bash
git add ema_poc/dashboard/build.py ema_poc/cli.py tests/dashboard/test_dashboard_build.py tests/test_cli_dashboard.py
git commit -m "feat: build_dashboard + ema dashboard CLI command"
```

---

### Task 4: Dashboard integration + README

**Files:**
- Modify: `README.md` (document `ema dashboard`)
- Test: `tests/dashboard/test_dashboard_integration.py`

- [ ] **Step 1: Write the integration test**

`tests/dashboard/test_dashboard_integration.py`:
```python
"""End-to-end: a scored run (via the pipeline) -> ema dashboard -> a
self-contained HTML file showing sentiment, positioning, and the alert."""

from ema_poc.adapters.base import LLMResponse
from ema_poc.cli import Deps, main
from ema_poc.config import AppConfig, BrandConfig, Settings
from ema_poc.dashboard.build import build_dashboard
from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import add_question, approve_question
from ema_poc.scoring.pipeline import score_pending
from ema_poc.scoring.scorer import ScoreResult

NOW = "2026-06-13T02:00:00+00:00"


class _Adapter:
    model_version = "m"

    def __init__(self, name):
        self.name = name

    def query(self, system_prompt, question_text):
        return LLMResponse("Skyrizi is not recommended.", "stop", "SUCCESS",
                           prompt_tokens=5, completion_tokens=5)


def _config():
    return AppConfig(
        settings=Settings(system_prompts={"default": "ctx"},
                          scoring_model="claude-opus-4-8"),
        brands=BrandConfig(abbvie_brands=["Skyrizi"], competitor_brands=["Humira"]),
        targets=[],
    )


def _scorer(client, *, response_text, **kw):
    return ScoreResult(
        sentiment_score=-0.6, competitive_position="NOT_RECOMMENDED",
        brand_mentions=["Skyrizi"], key_claims=["avoid"], scoring_rationale="negative tone",
    )


def test_run_score_dashboard_end_to_end(tmp_path):
    conn = connect(str(tmp_path / "ema.sqlite"))
    init_schema(conn)
    add_question(conn, question_id="Q1", question_text="Is Skyrizi first-line?",
                 persona="Provider", domain="Comparative",
                 therapeutic_area="Immunology", brand_focus="Skyrizi", now=NOW)
    approve_question(conn, "Q1", approver_name="Dr. A", now=NOW)
    out = []

    config = _config()
    out_path = str(tmp_path / "dashboard.html")

    deps = Deps(
        load_config=lambda d: config,
        connect=lambda p: conn,
        init_schema=lambda c: None,
        validate_credentials=lambda config, env: None,
        build_adapters=lambda config, env: [_Adapter("GPT-4o")],
        make_scoring_client=lambda env: object(),
        run=__import__("ema_poc.agent.runner", fromlist=["run"]).run,
        score_pending=lambda c, *, client, config: score_pending(
            c, client=client, config=config, scorer=_scorer),
        check_targets=lambda adapters: [],
        import_csv=lambda c, p: 0,
        import_excel=lambda c, p: 0,
        env={"ANTHROPIC_API_KEY": "k"},
        out=out.append,
        build_dashboard=build_dashboard,
    )

    # run + score, then build the dashboard
    assert main(["run", "--score"], deps=deps) == 0
    assert main(["dashboard", "--out", out_path], deps=deps) == 0

    html = open(out_path, encoding="utf-8").read()
    assert html.startswith("<!DOCTYPE html>")
    assert "GPT-4o" in html
    assert "NOT_RECOMMENDED" in html       # competitive position present
    assert "Alerts (1)" in html            # the negative response triggered an alert
    assert "negative tone" in html         # scoring rationale in the response detail
    assert "<script src" not in html       # self-contained
    conn.close()
```

- [ ] **Step 2: Run the integration test**

Run: `. .venv/bin/activate && pytest tests/dashboard/test_dashboard_integration.py -v`
Expected: PASS (1 passed). If it fails, the failure points at a real wiring gap — fix the referenced module, do not weaken the test.

- [ ] **Step 3: Document `ema dashboard` in `README.md`**

In the `## CLI` section, add this bullet to the command list:
```markdown
- `ema dashboard --out dashboard.html` — generate the self-contained HTML dashboard
  (sentiment, competitive positioning, alerts, response volume) for stakeholder review.
```

- [ ] **Step 4: Run the whole suite with coverage**

Run: `. .venv/bin/activate && pytest -q --cov` and `. .venv/bin/activate && pytest -q -W error::ResourceWarning`.
Expected: all green; no ResourceWarning. Note coverage for `ema_poc/dashboard/*`.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/dashboard/test_dashboard_integration.py
git commit -m "test: dashboard end-to-end; document ema dashboard"
```

---

## Self-Review

**Spec coverage (Phase 7 scope, FR-6):**
- FR-601 prototype dashboard for Medical Affairs/Commercial → `build_dashboard` + `ema dashboard` → Tasks 3, 4.
- FR-602 (a) sentiment distribution by LLM & therapy, (b) competitive positioning by LLM, (c) alert count + flagged list, (d) response volume over time → the four aggregations + render sections → Tasks 1, 2.
- FR-603 viewable without installing software → single self-contained HTML file (inline CSS/JS, no external resources), asserted by the render tests → Task 2.
- FR-604 filtering by persona/TA/LLM/date range → inline JS filter controls over the response table → Task 2.
- FR-605 click a response → full text + scoring rationale → click-to-expand detail rows → Task 2.

Deferred (correctly out of scope): FR-606 side-by-side same-question comparison view (a COULD — not implemented; the per-question rows are all present and filterable, so a comparison can be eyeballed); a hosted/shared-URL deployment (FR-603's alternative — the self-contained file is emailable, which satisfies the requirement). The Phase 5 `_iso` helper extraction remains a tracked cleanup.

**Placeholder scan:** No "TBD"/"add error handling"/"similar to" placeholders — every code and test step is complete.

**Type/name consistency:** `DashboardData` (Task 1) is consumed by `render_dashboard_html` (Task 2) and `build_dashboard` (Task 3). `build_dashboard(conn, out_path) -> str` matches the CLI `Deps.build_dashboard` call (Task 3) and the integration test (Task 4). The new `Deps.build_dashboard` field is added with a default so the existing Phase 6 CLI tests (which omit it) keep passing. The dashboard reads the response columns (`sentiment_score`, `competitive_position`, `alert_triggered`) populated by Phase 5's `update_response_scoring` and the latest score's `scoring_rationale` — all existing schema/columns.
