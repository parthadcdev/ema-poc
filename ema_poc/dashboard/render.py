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
