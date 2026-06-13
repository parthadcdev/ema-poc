"""Render DashboardData into one self-contained HTML document (FR-601/603/604/605).

Charts are inline CSS bars / HTML tables (no JS chart library, no external
resources, no remote fonts). All dynamic content is HTML-escaped. Filtering and
row expansion use small inline vanilla JS. The visual language is a refined
"clinical intelligence report": warm parchment surface, petrol-ink serif
headings, a diverging sentiment scale, and colour-coded status/position chips."""

from __future__ import annotations

import html

from ema_poc.dashboard.data import DashboardData

_CSS = """<style>
:root{
  --paper:#efe9dc; --surface:#fbf9f4; --surface-2:#f5f1e8;
  --ink:#1d2b27; --ink-soft:#5f635c; --ink-faint:#8c8a7e;
  --rule:#ddd5c4; --rule-soft:#e7e0d2;
  --accent:#1f5c4d; --accent-deep:#143b31;
  --pos:#2f7d5b; --pos-soft:#dcebe0;
  --neu:#a9791a; --neu-soft:#f0e6cf;
  --neg:#9f3a2f; --neg-soft:#f2ddd6;
  --serif:"Iowan Old Style","Hoefler Text",Georgia,"Times New Roman",serif;
  --sans:ui-sans-serif,-apple-system,"Helvetica Neue",Helvetica,Arial,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
html{-webkit-font-smoothing:antialiased}
body{
  font-family:var(--sans); color:var(--ink); margin:0; line-height:1.5;
  background:
    radial-gradient(900px 500px at 88% -8%, rgba(31,92,77,.07), transparent 60%),
    radial-gradient(700px 600px at -5% 110%, rgba(159,58,47,.05), transparent 55%),
    var(--paper);
  background-attachment:fixed;
}
.wrap{max-width:1180px; margin:0 auto; padding:2.6rem 1.6rem 4rem}

/* Masthead */
.masthead{border-bottom:2px solid var(--ink); padding-bottom:1.1rem; margin-bottom:1.8rem}
.kicker{font-family:var(--mono); font-size:11px; letter-spacing:.28em; text-transform:uppercase;
  color:var(--accent); margin:0 0 .5rem}
.masthead h1{font-family:var(--serif); font-weight:600; font-size:clamp(2rem,4.4vw,3.1rem);
  line-height:1.02; letter-spacing:-.015em; margin:0}
.masthead .sub{font-family:var(--serif); font-style:italic; color:var(--ink-soft);
  font-size:1.05rem; margin:.45rem 0 0}

/* Stat tiles */
.tiles{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:1px;
  background:var(--rule); border:1px solid var(--rule); margin:1.8rem 0 2.4rem}
.tile{background:var(--surface); padding:1rem 1.1rem}
.tile .lab{font-family:var(--mono); font-size:10.5px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--ink-faint); margin:0 0 .35rem}
.tile .num{font-family:var(--serif); font-size:2rem; line-height:1; font-weight:600}
.tile .num.pos{color:var(--pos)} .tile .num.neg{color:var(--neg)} .tile .num.neu{color:var(--neu)}
.tile.flag .num{color:var(--neg)}

/* Sections */
.section{background:var(--surface); border:1px solid var(--rule); border-radius:2px;
  padding:1.5rem 1.6rem; margin:0 0 1.5rem;
  box-shadow:0 1px 0 rgba(20,40,33,.03), 0 14px 30px -26px rgba(20,40,33,.5);
  opacity:0; transform:translateY(10px); animation:rise .55s cubic-bezier(.2,.7,.2,1) forwards}
.section:nth-child(2){animation-delay:.04s}.section:nth-child(3){animation-delay:.08s}
.section:nth-child(4){animation-delay:.12s}.section:nth-child(5){animation-delay:.16s}
.section:nth-child(6){animation-delay:.20s}.section:nth-child(7){animation-delay:.24s}
@keyframes rise{to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.section{animation:none;opacity:1;transform:none}}
.section>h2{font-family:var(--serif); font-weight:600; font-size:1.3rem; letter-spacing:-.01em;
  margin:0 0 .2rem; display:flex; align-items:baseline; gap:.6rem}
.section>h2 .idx{font-family:var(--mono); font-size:11px; color:var(--accent);
  letter-spacing:.1em; transform:translateY(-2px)}
.section>.hint{color:var(--ink-faint); font-size:12.5px; margin:.1rem 0 1.1rem}

/* Diverging + magnitude bars */
.chart{display:flex; flex-direction:column; gap:.5rem; margin-top:.4rem}
.brow{display:grid; grid-template-columns:185px 1fr 64px; align-items:center; gap:.7rem}
.brow .lab{font-size:13px; color:var(--ink-soft); overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.brow .val{font-family:var(--mono); font-size:12px; color:var(--ink-soft); text-align:right}
.track{position:relative; height:18px; background:
  linear-gradient(var(--rule-soft),var(--rule-soft)) center/100% 1px no-repeat, var(--surface-2);
  border-radius:2px}
.track.div::before{content:""; position:absolute; left:50%; top:-2px; bottom:-2px; width:1px;
  background:var(--ink-faint); opacity:.55}
.fill{position:absolute; top:3px; bottom:3px; border-radius:2px;
  background:linear-gradient(180deg, var(--accent), var(--accent-deep))}
.fill.pos{background:linear-gradient(180deg,#3a9069,#256249)}
.fill.neg{background:linear-gradient(180deg,#b3473a,#7e2b22)}

/* Tables */
.tbl-wrap{overflow:auto; border:1px solid var(--rule); border-radius:2px; max-height:560px}
table{border-collapse:collapse; width:100%; font-size:13px}
thead th{position:sticky; top:0; z-index:2; background:var(--accent-deep); color:#f2efe6;
  font-family:var(--mono); font-weight:500; font-size:10.5px; letter-spacing:.12em; text-transform:uppercase;
  text-align:left; padding:.6rem .75rem; white-space:nowrap}
tbody td{border-bottom:1px solid var(--rule-soft); padding:.5rem .75rem; vertical-align:top}
tbody tr:nth-child(4n+1) td, tbody tr:nth-child(4n+2) td{background:rgba(255,255,255,.45)}
.pos-tbl tbody tr:hover td{background:var(--surface-2)}
td.num{font-family:var(--mono); text-align:right; color:var(--ink-soft)}
td.qid strong{font-family:var(--mono); font-size:11.5px; color:var(--accent)}
.t-time{font-family:var(--mono); font-size:11px; color:var(--ink-faint); white-space:nowrap}

/* Chips */
.chip{display:inline-block; font-family:var(--mono); font-size:10.5px; letter-spacing:.04em;
  padding:.16rem .5rem; border-radius:999px; border:1px solid transparent; white-space:nowrap}
.c-pos{background:var(--pos-soft); color:#1f5a3e; border-color:#bcd9c5}
.c-neu{background:var(--neu-soft); color:#7c5908; border-color:#e4d2a6}
.c-neg{background:var(--neg-soft); color:#86281d; border-color:#e3c2b8}
.c-mut{background:var(--surface-2); color:var(--ink-faint); border-color:var(--rule)}
.sent{font-family:var(--mono); font-weight:600; font-size:12.5px}
.sent.pos{color:var(--pos)} .sent.neu{color:var(--neu)} .sent.neg{color:var(--neg)}

/* Responses interaction */
tr.resp{cursor:pointer; transition:background .12s}
tr.resp:hover td{background:var(--surface-2)}
tr.resp td:first-child{border-left:3px solid transparent}
tr.resp.flagged td:first-child{border-left-color:var(--neg)}
tr.detail td{background:#fffdf7; border-left:3px solid var(--accent)}
.detail-grid{display:grid; gap:.7rem; padding:.3rem .1rem .5rem}
.detail-grid .dl{font-family:var(--mono); font-size:9.5px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--ink-faint); margin-bottom:.2rem}
.detail-grid .dv{font-size:13px; white-space:pre-wrap; line-height:1.55}

/* Filters */
.controls{display:flex; flex-wrap:wrap; gap:.8rem 1rem; align-items:flex-end; margin:0 0 1.1rem}
.controls label{display:flex; flex-direction:column; gap:.25rem; font-family:var(--mono);
  font-size:9.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--ink-faint)}
.controls select,.controls input{font-family:var(--sans); font-size:13px; color:var(--ink);
  padding:.34rem .5rem; border:1px solid var(--rule); border-radius:2px; background:var(--surface)}
.controls select:focus,.controls input:focus{outline:none; border-color:var(--accent);
  box-shadow:0 0 0 2px rgba(31,92,77,.13)}

/* Alerts */
.alert-row td:first-child{font-family:var(--mono); font-size:11px}
.alert-reason{color:var(--neg); font-weight:600}
.empty{color:var(--ink-faint); font-style:italic; font-family:var(--serif); margin:.3rem 0}
footer{margin-top:2.4rem; padding-top:1rem; border-top:1px solid var(--rule);
  font-family:var(--mono); font-size:10.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--ink-faint)}
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


def _sent_class(v) -> str:
    if v is None or not isinstance(v, (int, float)):
        return "neu"
    if v >= 0.15:
        return "pos"
    if v <= -0.15:
        return "neg"
    return "neu"


_POS_CLASS = {
    "FIRST_LINE_RECOMMENDED": "c-pos",
    "AMONG_OPTIONS": "c-pos",
    "SECOND_LINE": "c-neu",
    "NOT_RECOMMENDED": "c-neg",
    "NOT_MENTIONED": "c-mut",
}
_STATUS_CLASS = {
    "SUCCESS": "c-pos", "TRUNCATED": "c-neu", "FAILED": "c-neg", "BLOCKED": "c-mut",
}


def _chip(value, cls: str) -> str:
    if value is None or value == "":
        return "<span class='chip c-mut'>&mdash;</span>"
    return "<span class='chip " + cls + "'>" + _e(value) + "</span>"


def _bars(d: dict, *, signed: bool = False) -> str:
    if not d:
        return "<p class='empty'>No data available.</p>"
    mx = max((abs(v) for v in d.values()), default=1) or 1
    out = ["<div class='chart'>"]
    for k, v in d.items():
        numeric = isinstance(v, (int, float))
        if signed and numeric:
            half = abs(v) / mx * 50.0
            if v < 0:
                fill = ("<span class='fill neg' style='right:50%%;width:%.1f%%'></span>" % half)
                valtxt = "%+.2f" % v
            else:
                fill = ("<span class='fill pos' style='left:50%%;width:%.1f%%'></span>" % half)
                valtxt = "%+.2f" % v
            track = "<div class='track div'>" + fill + "</div>"
        else:
            pct = abs(v) / mx * 100.0
            fill = ("<span class='fill' style='left:0;width:%.1f%%'></span>" % pct)
            track = "<div class='track'>" + fill + "</div>"
            valtxt = ("%.2f" % v) if isinstance(v, float) else _e(v)
        out.append(
            "<div class='brow'><span class='lab'>" + _e(k) + "</span>"
            + track + "<span class='val'>" + valtxt + "</span></div>"
        )
    out.append("</div>")
    return "".join(out)


def _position_table(pos: dict) -> str:
    if not pos:
        return "<p class='empty'>No data available.</p>"
    positions = sorted({p for counts in pos.values() for p in counts})
    head = ("<thead><tr><th>LLM</th>"
            + "".join("<th>" + _e(p) + "</th>" for p in positions)
            + "</tr></thead>")
    body = "<tbody>"
    for llm, counts in pos.items():
        body += "<tr><td>" + _e(llm) + "</td>"
        for p in positions:
            n = counts.get(p, 0)
            cell = ("<span class='chip " + _POS_CLASS.get(p, "c-mut") + "'>" + str(n) + "</span>"
                    if n else "<span class='c-mut' style='font-family:var(--mono);font-size:11px'>0</span>")
            body += "<td>" + cell + "</td>"
        body += "</tr>"
    body += "</tbody>"
    return "<div class='tbl-wrap'><table class='pos-tbl'>" + head + body + "</table></div>"


def _alerts_table(alerts: list[dict]) -> str:
    if not alerts:
        return "<p class='empty'>No alerts triggered &mdash; all responses within thresholds.</p>"
    body = "".join(
        "<tr class='alert-row'><td>" + _e(a["response_id"]) + "</td><td>" + _e(a["llm_name"])
        + "</td><td class='alert-reason'>" + _e(a["reason"]) + "</td></tr>"
        for a in alerts
    )
    return ("<div class='tbl-wrap'><table><thead><tr><th>Response</th><th>LLM</th>"
            "<th>Reason</th></tr></thead><tbody>" + body + "</tbody></table></div>")


def _select(el_id: str, label: str, options) -> str:
    opts = "<option value=''>All</option>" + "".join(
        "<option value='" + _e(o) + "'>" + _e(o) + "</option>" for o in options
    )
    return "<label>" + _e(label) + "<select id='" + _e(el_id) + "'>" + opts + "</select></label>"


def _responses_table(rows: list[dict]) -> str:
    personas = sorted({r["persona"] for r in rows if r["persona"]})
    tas = sorted({r["therapeutic_area"] for r in rows if r["therapeutic_area"]})
    llms = sorted({r["llm_name"] for r in rows if r["llm_name"]})
    controls = (
        "<div class='controls'>"
        + _select("f-persona", "Persona", personas)
        + _select("f-ta", "Therapeutic area", tas)
        + _select("f-llm", "LLM", llms)
        + "<label>From<input type='date' id='f-from'></label>"
        + "<label>To<input type='date' id='f-to'></label>"
        + "</div>"
    )
    head = ("<thead><tr><th>Time</th><th>Question</th><th>LLM</th><th>Persona</th>"
            "<th>Brand</th><th>Status</th><th>Sentiment</th><th>Position</th></tr></thead>")
    body = "<tbody>"
    for r in rows:
        date = (r["timestamp_utc"] or "")[:10]
        flagged = " flagged" if r["alert_triggered"] else ""
        sv = r["sentiment_score"]
        sentiment_cell = ("<span class='sent " + _sent_class(sv) + "'>" + ("%+.2f" % sv) + "</span>"
                          if isinstance(sv, (int, float)) else "<span class='c-mut'>&mdash;</span>")
        qid = _e(r.get("question_id"))
        qtext = r.get("question_text") or ""
        qshort = qtext if len(qtext) <= 72 else qtext[:69] + "…"
        question_cell = "<span class='qid'><strong>" + qid + "</strong></span> " + _e(qshort)
        status_cell = _chip(r["status"], _STATUS_CLASS.get(r["status"], "c-mut"))
        pos_cell = _chip(r["competitive_position"] or None,
                         _POS_CLASS.get(r["competitive_position"], "c-mut"))
        body += (
            "<tr class='resp" + flagged + "' data-persona='" + _e(r["persona"]) + "' data-ta='"
            + _e(r["therapeutic_area"]) + "' data-llm='" + _e(r["llm_name"])
            + "' data-date='" + _e(date) + "'>"
            + "<td class='t-time'>" + _e(r["timestamp_utc"]) + "</td><td>" + question_cell
            + "</td><td>" + _e(r["llm_name"])
            + "</td><td>" + _e(r["persona"]) + "</td><td>" + _e(r["brand_focus"])
            + "</td><td>" + status_cell + "</td><td>" + sentiment_cell
            + "</td><td>" + pos_cell + "</td></tr>"
        )
        detail = (
            "<div class='detail-grid'>"
            + "<div><div class='dl'>Question</div><div class='dv'>" + _e(qtext) + "</div></div>"
            + "<div><div class='dl'>Response</div><div class='dv'>" + _e(r["response_text"]) + "</div></div>"
            + "<div><div class='dl'>Scoring rationale</div><div class='dv'>"
            + _e(r["scoring_rationale"]) + "</div></div></div>"
        )
        body += ("<tr class='detail' style='display:none'><td colspan='8'>" + detail + "</td></tr>")
    body += "</tbody>"
    return controls + "<div class='tbl-wrap'><table>" + head + body + "</table></div>"


def _stat_tiles(data: DashboardData) -> str:
    sentiments = [v for v in data.sentiment_by_llm.values() if isinstance(v, (int, float))]
    avg = sum(sentiments) / len(sentiments) if sentiments else None
    avg_txt = "%+.2f" % avg if avg is not None else "—"
    avg_cls = _sent_class(avg)
    tiles = [
        ("Responses", str(data.total_responses), ""),
        ("Alerts", str(data.total_alerts), "flag" if data.total_alerts else ""),
        ("Models tracked", str(len(data.sentiment_by_llm)), ""),
        ("Avg sentiment", avg_txt, ""),
    ]
    out = "<div class='tiles'>"
    for lab, num, extra in tiles:
        cls = avg_cls if lab == "Avg sentiment" else ""
        out += ("<div class='tile " + extra + "'><div class='lab'>" + lab
                + "</div><div class='num " + cls + "'>" + num + "</div></div>")
    return out + "</div>"


def _section(idx: str, title: str, hint: str, inner: str) -> str:
    return ("<div class='section'><h2><span class='idx'>" + idx + "</span>" + _e(title) + "</h2>"
            + ("<p class='hint'>" + _e(hint) + "</p>" if hint else "")
            + inner + "</div>")


def render_dashboard_html(data: DashboardData) -> str:
    parts = [
        "<!DOCTYPE html>",
        "<html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Evidence Monitoring Dashboard</title>",
        _CSS,
        "</head><body><div class='wrap'>",
        "<header class='masthead'><p class='kicker'>Evidence Monitoring &middot; Medical Affairs</p>"
        "<h1>Evidence Monitoring Dashboard</h1>"
        "<p class='sub'>How large language models represent the brand across personas and therapies.</p>"
        "</header>",
        _stat_tiles(data),
        _section("01", "Sentiment by LLM", "Mean brand sentiment per model, −1 to +1.",
                 _bars(data.sentiment_by_llm, signed=True)),
        _section("02", "Sentiment by therapy", "Mean brand sentiment per therapeutic area.",
                 _bars(data.sentiment_by_therapy, signed=True)),
        _section("03", "Competitive positioning by LLM",
                 "How each model positions the brand against competitors.",
                 _position_table(data.position_by_llm)),
        _section("04", "Response volume over time", "Captured responses per day.",
                 _bars(data.volume_by_date)),
        _section("05", "Alerts (" + str(data.total_alerts) + ")",
                 "Responses crossing a sentiment or positioning threshold.",
                 _alerts_table(data.alerts)),
        _section("06", "Responses", "Click any row to expand the full question, answer, and rationale.",
                 _responses_table(data.rows)),
        "<footer>Evidence Monitoring Agent &middot; self-contained report</footer>",
        "</div>",
        _JS,
        "</body></html>",
    ]
    return "\n".join(parts)
