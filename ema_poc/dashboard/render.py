"""Render a client-side audience dashboard from a dataset dict (FR-audience-dashboard).

`render_dashboard_html(dataset: dict) -> str`

Returns a single self-contained HTML string: no external scripts, no external
stylesheets, no remote fonts.  The full dataset is embedded as JSON inside a
<script type="application/json"> tag; all filtering, navigation, and rendering
is handled by inline vanilla JS."""

from __future__ import annotations

import html
import json


def _e(value) -> str:
    """HTML-escape a value (None -> empty string)."""
    return html.escape("" if value is None else str(value))


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
  --nav-w:210px;
}
*{box-sizing:border-box}
html{-webkit-font-smoothing:antialiased}
body{
  font-family:var(--sans); color:var(--ink); margin:0; line-height:1.5;
  background:var(--paper); display:flex; min-height:100vh;
}

/* ---- Side-nav ---- */
.sidenav{
  width:var(--nav-w); min-width:var(--nav-w); max-width:var(--nav-w);
  background:var(--accent-deep); position:fixed; top:0; left:0;
  height:100vh; overflow-y:auto; display:flex; flex-direction:column;
  z-index:10;
}
.sidenav .nav-brand{
  padding:1.2rem 1.1rem .9rem; border-bottom:1px solid rgba(255,255,255,.1);
}
.sidenav .nav-brand .kicker{
  font-family:var(--mono); font-size:9px; letter-spacing:.28em;
  text-transform:uppercase; color:rgba(255,255,255,.55); margin:0 0 .25rem;
}
.sidenav .nav-brand .brand-title{
  font-family:var(--serif); font-size:1.05rem; color:#f2efe6; line-height:1.2;
}
.sidenav ul{list-style:none; margin:0; padding:.6rem 0}
.sidenav ul li a{
  display:block; padding:.62rem 1.1rem; color:rgba(255,255,255,.75);
  text-decoration:none; font-size:13px; font-family:var(--sans);
  letter-spacing:.01em; border-left:3px solid transparent;
  transition:background .15s, color .15s;
}
.sidenav ul li a:hover{
  background:rgba(255,255,255,.08); color:#fff;
}
.sidenav ul li a.active{
  background:rgba(255,255,255,.13); color:#fff;
  border-left-color:#7ecab0; font-weight:600;
}

/* ---- Main area ---- */
.main-wrap{
  margin-left:var(--nav-w); flex:1; display:flex; flex-direction:column;
  min-height:100vh;
}

/* ---- Global header + filter bar ---- */
.top-bar{
  background:var(--surface); border-bottom:1px solid var(--rule);
  padding:.9rem 1.6rem; position:sticky; top:0; z-index:5;
  box-shadow:0 1px 8px -4px rgba(20,40,33,.18);
}
.top-bar h1{
  font-family:var(--serif); font-size:1.35rem; font-weight:600;
  letter-spacing:-.01em; color:var(--ink); margin:0 0 .7rem;
}
.filter-bar{
  display:flex; flex-wrap:wrap; gap:.6rem .9rem; align-items:flex-end;
}
.filter-bar label{
  display:flex; flex-direction:column; gap:.2rem;
  font-family:var(--mono); font-size:9.5px; letter-spacing:.12em;
  text-transform:uppercase; color:var(--ink-faint);
}
.filter-bar select,.filter-bar input[type=date]{
  font-family:var(--sans); font-size:12px; color:var(--ink);
  padding:.28rem .45rem; border:1px solid var(--rule); border-radius:2px;
  background:var(--surface); min-width:110px;
}
.filter-bar select:focus,.filter-bar input:focus{
  outline:none; border-color:var(--accent);
  box-shadow:0 0 0 2px rgba(31,92,77,.13);
}
#f-reset{
  font-family:var(--mono); font-size:11px; letter-spacing:.06em;
  text-transform:uppercase; cursor:pointer; padding:.3rem .8rem;
  border:1px solid var(--rule); border-radius:2px; background:var(--surface-2);
  color:var(--ink-soft); align-self:flex-end;
}
#f-reset:hover{border-color:var(--accent);color:var(--accent)}

/* ---- Content area ---- */
.content{padding:1.6rem; flex:1}
section.view{display:none}
section.view.active{display:block}

/* ---- Stat tiles ---- */
.tiles{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
  gap:1px; background:var(--rule); border:1px solid var(--rule);
  margin:0 0 1.8rem; border-radius:2px; overflow:hidden;
}
.tile{background:var(--surface); padding:.9rem 1rem}
.tile .lab{
  font-family:var(--mono); font-size:9.5px; letter-spacing:.16em;
  text-transform:uppercase; color:var(--ink-faint); margin:0 0 .3rem;
}
.tile .num{
  font-family:var(--serif); font-size:1.9rem; line-height:1; font-weight:600;
}
.tile.flag .num{color:var(--neg)}
.tile.warn .num{color:var(--neu)}

/* ---- Cards / sections ---- */
.card{
  background:var(--surface); border:1px solid var(--rule); border-radius:2px;
  padding:1.2rem 1.4rem; margin:0 0 1.2rem;
  box-shadow:0 1px 0 rgba(20,40,33,.03),0 10px 24px -20px rgba(20,40,33,.45);
}
.card h2{
  font-family:var(--serif); font-weight:600; font-size:1.2rem;
  letter-spacing:-.01em; margin:0 0 .8rem; color:var(--ink);
}
.card .hint{
  color:var(--ink-faint); font-size:12px; margin:-.4rem 0 .8rem;
  font-family:var(--mono); letter-spacing:.04em;
}

/* ---- Tables ---- */
.tbl-wrap{overflow:auto; border:1px solid var(--rule); border-radius:2px; max-height:560px}
table{border-collapse:collapse; width:100%; font-size:13px}
thead th{
  position:sticky; top:0; z-index:2; background:var(--accent-deep); color:#f2efe6;
  font-family:var(--mono); font-weight:500; font-size:10px; letter-spacing:.12em;
  text-transform:uppercase; text-align:left; padding:.55rem .7rem; white-space:nowrap;
}
tbody td{
  border-bottom:1px solid var(--rule-soft); padding:.45rem .7rem; vertical-align:top;
}
tbody tr:nth-child(4n+1) td,tbody tr:nth-child(4n+2) td{background:rgba(255,255,255,.45)}
.t-time{font-family:var(--mono); font-size:11px; color:var(--ink-faint); white-space:nowrap}
td.qid strong{font-family:var(--mono); font-size:11px; color:var(--accent)}

/* ---- Chips ---- */
.chip{
  display:inline-block; font-family:var(--mono); font-size:10px;
  letter-spacing:.03em; padding:.14rem .45rem; border-radius:999px;
  border:1px solid transparent; white-space:nowrap;
}
.c-pos{background:var(--pos-soft);color:#1f5a3e;border-color:#bcd9c5}
.c-neu{background:var(--neu-soft);color:#7c5908;border-color:#e4d2a6}
.c-neg{background:var(--neg-soft);color:#86281d;border-color:#e3c2b8}
.c-mut{background:var(--surface-2);color:var(--ink-faint);border-color:var(--rule)}
.c-high{background:#fde8e8;color:#7a1f1f;border-color:#f0bebe}
.sent{font-family:var(--mono); font-weight:600; font-size:12px}
.sent.pos{color:var(--pos)} .sent.neu{color:var(--neu)} .sent.neg{color:var(--neg)}

/* ---- Expandable response rows ---- */
tr.resp{cursor:pointer; transition:background .12s}
tr.resp:hover td{background:var(--surface-2)}
tr.resp td:first-child{border-left:3px solid transparent}
tr.resp.flagged td:first-child{border-left-color:var(--neg)}
tr.detail td{background:#fffdf7;border-left:3px solid var(--accent)}
.detail-grid{display:grid;gap:.7rem;padding:.3rem .1rem .5rem}
.detail-grid .dl{
  font-family:var(--mono);font-size:9px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--ink-faint);margin-bottom:.18rem;
}
.detail-grid .dv{font-size:13px;white-space:pre-wrap;line-height:1.55}

/* ---- Alerts list ---- */
.alert-item{
  border-left:3px solid var(--neg); padding:.4rem .75rem;
  margin:.4rem 0; background:rgba(159,58,47,.04); border-radius:0 2px 2px 0;
  font-size:13px;
}
.alert-item .a-id{font-family:var(--mono);font-size:11px;color:var(--ink-faint)}
.alert-item .a-reasons{color:var(--neg);font-size:12px;margin-top:.18rem}

/* ---- Empty state ---- */
.empty{color:var(--ink-faint);font-style:italic;font-family:var(--serif);margin:.3rem 0}

/* ---- Placeholder section ---- */
.placeholder{
  border:2px dashed var(--rule); border-radius:4px; padding:2.5rem;
  text-align:center; color:var(--ink-faint); margin:1rem 0;
}
.placeholder p{font-family:var(--serif); font-size:1.05rem; font-style:italic; margin:0}

footer{
  margin-top:auto; padding:1rem 1.6rem; border-top:1px solid var(--rule);
  font-family:var(--mono); font-size:10px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--ink-faint);
}
</style>"""


_JS = r"""<script>
(function(){

/* ---- Bootstrap ---- */
const DATA = JSON.parse(document.getElementById('ema-data').textContent);

function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"']/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
}

/* ---- Populate filter selects ---- */
function distinct(field){
  const s = new Set();
  DATA.records.forEach(function(r){ if(r[field]) s.add(r[field]); });
  return Array.from(s).sort();
}

function populate(id, values){
  const sel = document.getElementById(id);
  values.forEach(function(v){
    const o = document.createElement('option');
    o.value = v; o.textContent = v;
    sel.appendChild(o);
  });
}

populate('f-ta',      distinct('therapeutic_area'));
populate('f-brand',   distinct('brand_focus'));
populate('f-llm',     distinct('llm_name'));
populate('f-persona', distinct('persona'));

/* ---- State ---- */
const STATE = { section: 'overview', filters: {} };

/* ---- Filter engine ---- */
function applyFilters(){
  const ta      = document.getElementById('f-ta').value;
  const brand   = document.getElementById('f-brand').value;
  const llm     = document.getElementById('f-llm').value;
  const persona = document.getElementById('f-persona').value;
  const from    = document.getElementById('f-from').value;
  const to      = document.getElementById('f-to').value;
  return DATA.records.filter(function(r){
    if(ta      && r.therapeutic_area !== ta)    return false;
    if(brand   && r.brand_focus      !== brand) return false;
    if(llm     && r.llm_name         !== llm)   return false;
    if(persona && r.persona          !== persona) return false;
    if(from    && r.date < from)                return false;
    if(to      && r.date > to)                  return false;
    return true;
  });
}

/* ---- Nav ---- */
document.querySelectorAll('.sidenav a[data-section]').forEach(function(link){
  link.addEventListener('click', function(e){
    e.preventDefault();
    STATE.section = link.dataset.section;
    document.querySelectorAll('.sidenav a[data-section]').forEach(function(l){
      l.classList.remove('active');
    });
    link.classList.add('active');
    render();
  });
});

/* ---- Filter events ---- */
document.querySelectorAll('#f-ta,#f-brand,#f-llm,#f-persona,#f-from,#f-to').forEach(function(el){
  el.addEventListener('change', render);
  el.addEventListener('input', render);
});
document.getElementById('f-reset').addEventListener('click', function(){
  document.getElementById('f-ta').value      = '';
  document.getElementById('f-brand').value   = '';
  document.getElementById('f-llm').value     = '';
  document.getElementById('f-persona').value = '';
  document.getElementById('f-from').value    = '';
  document.getElementById('f-to').value      = '';
  render();
});

/* ---- Section visibility ---- */
function showSection(id){
  document.querySelectorAll('section.view').forEach(function(s){
    s.classList.remove('active');
  });
  document.getElementById('view-'+id).classList.add('active');
}

/* ---- Sentiment helpers ---- */
function sentClass(v){
  if(v == null || typeof v !== 'number') return 'neu';
  if(v >=  0.15) return 'pos';
  if(v <= -0.15) return 'neg';
  return 'neu';
}
function fmtSent(v){
  if(v == null || typeof v !== 'number') return "<span class='chip c-mut'>&mdash;</span>";
  var cls = sentClass(v);
  return "<span class='sent "+cls+"'>"+(v>=0?'+':'')+v.toFixed(2)+"</span>";
}

/* ---- Chip helpers ---- */
var POS_CLS = {
  FIRST_LINE_RECOMMENDED:'c-pos', AMONG_OPTIONS:'c-pos',
  SECOND_LINE:'c-neu', NOT_RECOMMENDED:'c-neg', NOT_MENTIONED:'c-mut'
};
var STATUS_CLS = {SUCCESS:'c-pos',TRUNCATED:'c-neu',FAILED:'c-neg',BLOCKED:'c-mut'};
var HALLUC_CLS = {HIGH:'c-high',MEDIUM:'c-neu',LOW:'c-pos',NONE:'c-mut'};

function chip(val, cls){
  if(!val) return "<span class='chip c-mut'>&mdash;</span>";
  return "<span class='chip "+(cls||'c-mut')+"'>"+esc(val)+"</span>";
}

/* ====================================================================
   renderOverview
   ==================================================================== */
function renderOverview(rows){
  var total    = rows.length;
  var scored   = rows.filter(function(r){ return r.sentiment_score != null; }).length;
  var alerts   = rows.filter(function(r){ return r.alert_triggered; }).length;
  var hallHigh = rows.filter(function(r){ return r.hallucination_risk === 'HIGH'; }).length;
  var driftCt  = rows.filter(function(r){
    return r.alert_reasons && r.alert_reasons.some(function(a){ return a.startsWith('DRIFT:'); });
  }).length;

  var tilesHtml =
    "<div class='tiles'>" +
    "<div class='tile'><div class='lab'>Total Responses</div><div class='num'>"+esc(total)+"</div></div>" +
    "<div class='tile'><div class='lab'>Scored</div><div class='num'>"+esc(scored)+"</div></div>" +
    "<div class='tile "+(alerts>0?'flag':'')+"'><div class='lab'>Alerts Triggered</div><div class='num'>"+esc(alerts)+"</div></div>" +
    "<div class='tile "+(hallHigh>0?'flag':'')+"'><div class='lab'>Hallucination HIGH</div><div class='num'>"+esc(hallHigh)+"</div></div>" +
    "<div class='tile "+(driftCt>0?'warn':'')+"'><div class='lab'>Drift Alerts</div><div class='num'>"+esc(driftCt)+"</div></div>" +
    "</div>";

  var alertedRows = rows.filter(function(r){ return r.alert_triggered; });
  var alertsHtml;
  if(alertedRows.length === 0){
    alertsHtml = "<p class='empty'>No alerts in current filter view.</p>";
  } else {
    alertsHtml = alertedRows.map(function(r){
      var reasons = (r.alert_reasons||[]).map(function(a){ return esc(a); }).join(', ');
      return "<div class='alert-item'>" +
        "<span class='a-id'>"+esc(r.question_id)+" &middot; "+esc(r.llm_name)+"</span>" +
        "<div class='a-reasons'>"+reasons+"</div>" +
        "</div>";
    }).join('');
  }

  document.getElementById('view-overview').innerHTML =
    tilesHtml +
    "<div class='card'>" +
    "<h2>Headline Alerts</h2>" +
    "<p class='hint'>Responses that crossed a monitoring threshold in this filter view.</p>" +
    alertsHtml +
    "</div>";
}

/* ====================================================================
   renderMarketing — stub (Task 3)
   ==================================================================== */
function renderMarketing(rows){
  document.getElementById('view-marketing').innerHTML =
    "<div class='placeholder'><p>Marketing Analytics &mdash; coming soon.</p></div>";
}

/* ====================================================================
   renderMedical — stub (Task 4)
   ==================================================================== */
function renderMedical(rows){
  document.getElementById('view-medical').innerHTML =
    "<div class='placeholder'><p>Medical Affairs &mdash; coming soon.</p></div>";
}

/* ====================================================================
   renderResponses
   ==================================================================== */
function renderResponses(rows){
  var head = "<thead><tr>" +
    "<th>Time</th><th>Question</th><th>LLM</th><th>Persona</th>" +
    "<th>Brand</th><th>Status</th><th>Sentiment</th><th>Position</th>" +
    "<th>Confidence</th><th>Citation</th><th>Halluc</th>" +
    "</tr></thead>";

  var body = "<tbody>";
  rows.forEach(function(r){
    var flagged = r.alert_triggered ? ' flagged' : '';
    var qtext   = r.question_text || '';
    var qshort  = qtext.length > 72 ? qtext.slice(0,69)+'…' : qtext;
    var qcell   = "<span class='qid'><strong>"+esc(r.question_id)+"</strong></span> "+esc(qshort);
    var posCls  = POS_CLS[r.competitive_position] || 'c-mut';
    var statCls = STATUS_CLS[r.status] || 'c-mut';
    var hCls    = HALLUC_CLS[r.hallucination_risk] || 'c-mut';

    body += "<tr class='resp"+flagged+"' data-id='"+esc(r.response_id)+"'>" +
      "<td class='t-time'>"+esc((r.timestamp_utc||'').slice(0,10))+"</td>" +
      "<td>"+qcell+"</td>" +
      "<td>"+esc(r.llm_name)+"</td>" +
      "<td>"+esc(r.persona)+"</td>" +
      "<td>"+esc(r.brand_focus)+"</td>" +
      "<td>"+chip(r.status, statCls)+"</td>" +
      "<td>"+fmtSent(r.sentiment_score)+"</td>" +
      "<td>"+chip(r.competitive_position, posCls)+"</td>" +
      "<td>"+chip(r.confidence_level,'c-mut')+"</td>" +
      "<td>"+chip(r.citation_quality,'c-mut')+"</td>" +
      "<td>"+chip(r.hallucination_risk, hCls)+"</td>" +
      "</tr>";

    var rationale = r.scoring_rationale || '';
    var detail =
      "<div class='detail-grid'>" +
      "<div><div class='dl'>Question</div><div class='dv'>"+esc(qtext)+"</div></div>" +
      "<div><div class='dl'>Response</div><div class='dv'>"+esc(r.response_text||'')+"</div></div>" +
      "<div><div class='dl'>Scoring Rationale</div><div class='dv'>"+esc(rationale)+"</div></div>" +
      "</div>";
    body += "<tr class='detail' style='display:none'><td colspan='11'>"+detail+"</td></tr>";
  });
  body += "</tbody>";

  var suffix = rows.length === 0
    ? "<p class='empty'>No responses match the current filters.</p>"
    : "";

  document.getElementById('view-responses').innerHTML =
    "<div class='tbl-wrap'><table>"+head+body+"</table></div>" + suffix;

  /* Wire row-expand clicks */
  document.querySelectorAll('#view-responses tr.resp').forEach(function(row){
    row.addEventListener('click', function(){
      var det = row.nextElementSibling;
      if(det && det.classList.contains('detail')){
        det.style.display = (!det.style.display || det.style.display === 'none')
          ? 'table-row' : 'none';
      }
    });
  });
}

/* ====================================================================
   Main render dispatcher
   ==================================================================== */
function render(){
  var rows = applyFilters();
  showSection(STATE.section);
  switch(STATE.section){
    case 'overview':   renderOverview(rows);   break;
    case 'marketing':  renderMarketing(rows);  break;
    case 'medical':    renderMedical(rows);    break;
    case 'responses':  renderResponses(rows);  break;
  }
}

/* ---- Initial render ---- */
render();

})();
</script>"""


def render_dashboard_html(dataset: dict) -> str:
    """Render a self-contained HTML dashboard from a dataset dict.

    `dataset` must be the shape produced by `collect_dataset`:
    { generated_at, abbvie_brands, competitor_brands, records: [...] }
    """
    # Embed JSON safely: escape </ to prevent injection through </script>
    embedded_json = json.dumps(dataset, ensure_ascii=False).replace("</", r"<\/")

    generated_at = _e(dataset.get("generated_at") or "")

    filter_bar = (
        "<div class='filter-bar'>"
        "<label>Therapeutic Area<select id='f-ta'><option value=''>All</option></select></label>"
        "<label>Brand<select id='f-brand'><option value=''>All</option></select></label>"
        "<label>LLM<select id='f-llm'><option value=''>All</option></select></label>"
        "<label>Persona<select id='f-persona'><option value=''>All</option></select></label>"
        "<label>From<input type='date' id='f-from'></label>"
        "<label>To<input type='date' id='f-to'></label>"
        "<button id='f-reset'>Reset</button>"
        "</div>"
    )

    nav = (
        "<nav class='sidenav'>"
        "<div class='nav-brand'>"
        "<div class='kicker'>Evidence Monitoring</div>"
        "<div class='brand-title'>Audience<br>Dashboard</div>"
        "</div>"
        "<ul>"
        "<li><a href='#' data-section='overview' class='active'>Overview</a></li>"
        "<li><a href='#' data-section='marketing'>Marketing Analytics</a></li>"
        "<li><a href='#' data-section='medical'>Medical Affairs</a></li>"
        "<li><a href='#' data-section='responses'>Responses</a></li>"
        "</ul>"
        "</nav>"
    )

    sections = (
        "<section id='view-overview' class='view active'></section>"
        "<section id='view-marketing' class='view'>"
        "<p>Marketing Analytics &mdash; coming soon.</p>"
        "</section>"
        "<section id='view-medical' class='view'>"
        "<p>Medical Affairs &mdash; coming soon.</p>"
        "</section>"
        "<section id='view-responses' class='view'></section>"
    )

    parts = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Evidence Monitoring &mdash; Audience Dashboard</title>",
        _CSS,
        "</head>",
        "<body>",
        nav,
        "<div class='main-wrap'>",
        "<div class='top-bar'>",
        "<h1>Evidence Monitoring Dashboard</h1>",
        filter_bar,
        "</div>",
        "<div class='content'>",
        sections,
        "</div>",
        "<footer>Evidence Monitoring Agent &middot; self-contained report"
        + (" &middot; " + generated_at if generated_at else "") + "</footer>",
        "</div>",
        # Embedded data (must precede the app script)
        "<script type='application/json' id='ema-data'>" + embedded_json + "</script>",
        _JS,
        "</body>",
        "</html>",
    ]
    return "\n".join(parts)
