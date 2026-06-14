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

/* ---- Medical Affairs: review queue ---- */
.med-note{
  font-family:var(--mono); font-size:10.5px; letter-spacing:.04em;
  color:var(--ink-faint); background:var(--surface-2); border:1px solid var(--rule);
  border-radius:2px; padding:.45rem .85rem; margin:0 0 1.2rem;
}
.queue-item{
  border:1px solid var(--rule); border-radius:2px; margin:0 0 .7rem;
  background:var(--surface); overflow:hidden;
  box-shadow:0 1px 0 rgba(20,40,33,.03);
}
.queue-item-header{
  display:flex; flex-wrap:wrap; gap:.4rem .7rem; align-items:baseline;
  padding:.65rem .9rem; cursor:pointer; user-select:none;
  border-left:4px solid var(--rule); transition:background .12s;
}
.queue-item-header:hover{background:var(--surface-2)}
.queue-item.risk-high .queue-item-header{border-left-color:#9f3a2f}
.queue-item.risk-medium .queue-item-header{border-left-color:#a9791a}
.queue-item.risk-low .queue-item-header{border-left-color:#5ba4a0}
.queue-item.risk-none .queue-item-header{border-left-color:var(--rule-soft)}
.qi-id{font-family:var(--mono); font-size:11px; font-weight:700; color:var(--accent); flex-shrink:0}
.qi-text{font-size:13px; color:var(--ink); flex:1 1 200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:400px}
.qi-meta{font-family:var(--mono); font-size:10.5px; color:var(--ink-faint)}
.qi-badges{display:flex; flex-wrap:wrap; gap:.3rem; align-items:center; margin-left:auto}
/* Hallucination risk badges */
.badge{
  display:inline-block; font-family:var(--mono); font-size:10px; font-weight:600;
  letter-spacing:.04em; padding:.16rem .52rem; border-radius:999px; white-space:nowrap;
}
.badge-hall-high{background:#fde8e8; color:#7a1f1f; border:1px solid #f0bebe}
.badge-hall-medium{background:var(--neu-soft); color:#7c5908; border:1px solid #e4d2a6}
.badge-hall-low{background:#e6f5ef; color:#1f5a3e; border:1px solid #b8dcca}
.badge-drift{background:#e8edf8; color:#2b4a8c; border:1px solid #bfcbe8}
.badge-alert{background:var(--surface-2); color:var(--ink-soft); border:1px solid var(--rule)}
/* Severity badges for flagged claims */
.sev-high{background:#fde8e8; color:#7a1f1f; border:1px solid #f0bebe}
.sev-medium{background:var(--neu-soft); color:#7c5908; border:1px solid #e4d2a6}
.sev-low{background:#e6f5ef; color:#1f5a3e; border:1px solid #b8dcca}
/* Expandable detail panel */
.queue-detail{
  display:none; padding:.75rem 1rem .9rem 1rem;
  border-top:1px solid var(--rule-soft); background:#fffdf7;
}
.queue-detail.open{display:block}
.qd-section{margin:0 0 .9rem}
.qd-label{
  font-family:var(--mono); font-size:9px; letter-spacing:.16em;
  text-transform:uppercase; color:var(--ink-faint); margin:0 0 .25rem;
}
.qd-value{font-size:13px; white-space:pre-wrap; line-height:1.55}
.qd-claim{
  border-left:3px solid var(--rule); padding:.3rem .65rem; margin:.35rem 0;
  border-radius:0 2px 2px 0; font-size:12.5px; background:rgba(159,58,47,.03);
}
.qd-claim-text{color:var(--ink); margin-bottom:.18rem}
.qd-claim-conflict{color:var(--ink-soft); font-style:italic; font-size:12px}
.signal-chips{display:flex; flex-wrap:wrap; gap:.35rem; margin-top:.25rem}
.signal-chip{
  display:inline-flex; align-items:center; gap:.3rem;
  font-family:var(--mono); font-size:10.5px; padding:.18rem .5rem;
  border:1px solid var(--rule); border-radius:2px; background:var(--surface-2);
  color:var(--ink-soft);
}
.signal-chip .sc-label{color:var(--ink-faint); font-size:9.5px; letter-spacing:.1em; text-transform:uppercase}

/* ---- Share of Voice / Stacked bar tracks ---- */
.sov-row{display:flex;align-items:center;gap:.7rem;margin:.45rem 0;font-size:12.5px}
.sov-label{width:160px;flex-shrink:0;text-align:right;color:var(--ink-soft);font-family:var(--sans);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
.sov-track{flex:1;height:18px;background:var(--rule-soft);border-radius:2px;overflow:hidden;display:flex;min-width:120px}
.sov-abbvie{background:var(--accent);height:100%}
.sov-comp{background:#d9a64b;height:100%}
.sov-meta{width:130px;flex-shrink:0;font-family:var(--mono);font-size:10.5px;color:var(--ink-faint);white-space:nowrap}

/* ---- Positioning mix bars ---- */
.pos-row{display:flex;align-items:center;gap:.7rem;margin:.45rem 0}
.pos-label{width:160px;flex-shrink:0;text-align:right;color:var(--ink-soft);font-family:var(--sans);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
.pos-track{flex:1;height:18px;border-radius:2px;overflow:hidden;display:flex;min-width:120px}
.pos-meta{width:60px;flex-shrink:0;font-family:var(--mono);font-size:10.5px;color:var(--ink-faint)}
.pos-legend{display:flex;flex-wrap:wrap;gap:.4rem .9rem;margin:.7rem 0 1rem}
.pos-swatch{display:inline-flex;align-items:center;gap:.35rem;font-family:var(--mono);font-size:10px;color:var(--ink-soft)}
.pos-swatch span{display:inline-block;width:12px;height:12px;border-radius:2px;flex-shrink:0}

/* ---- Heatmap ---- */
.heatmap-wrap{overflow-x:auto;margin:.5rem 0}
.heatmap-tbl{border-collapse:collapse;font-size:12px}
.heatmap-tbl th{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;padding:.35rem .55rem;background:var(--accent-deep);color:#f2efe6;white-space:nowrap}
.heatmap-tbl td.row-head{font-family:var(--sans);font-size:12px;color:var(--ink-soft);padding:.35rem .55rem;white-space:nowrap;background:var(--surface-2);border:1px solid var(--rule-soft)}
.heatmap-tbl td.cell{width:72px;height:36px;text-align:center;vertical-align:middle;font-family:var(--mono);font-size:11px;font-weight:600;border:1px solid rgba(0,0,0,.06)}
.heatmap-tbl td.cell.empty{background:var(--surface-2);color:var(--ink-faint);font-weight:400}
.hmscale{display:flex;align-items:center;gap:.5rem;margin:.6rem 0 .2rem;font-family:var(--mono);font-size:10px;color:var(--ink-faint)}
.hmscale-bar{width:140px;height:10px;border-radius:2px;background:linear-gradient(to right,#9f3a2f,#a9791a,#2f7d5b);border:1px solid var(--rule)}

/* ---- SVG trend ---- */
.trend-svg-wrap{overflow-x:auto;margin:.5rem 0}
.trend-legend{display:flex;flex-wrap:wrap;gap:.4rem .9rem;margin:.6rem 0 .4rem}
.trend-swatch{display:inline-flex;align-items:center;gap:.35rem;font-family:var(--mono);font-size:10px;color:var(--ink-soft)}
.trend-swatch span{display:inline-block;width:14px;height:3px;border-radius:1px;flex-shrink:0}

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
   renderMarketing
   ==================================================================== */
function renderMarketing(rows){

  /* -- 1. Share of Voice (by therapeutic area) -- */
  var sovMap = {}; /* ta -> {abbvie:N, comp:N} */
  rows.forEach(function(r){
    var ta = r.therapeutic_area || '(none)';
    if(!sovMap[ta]) sovMap[ta] = {abbvie:0, comp:0};
    (r.brand_mentions || []).forEach(function(m){
      if(DATA.abbvie_brands.indexOf(m) >= 0)      sovMap[ta].abbvie++;
      else if(DATA.competitor_brands.indexOf(m) >= 0) sovMap[ta].comp++;
    });
  });
  var sovAreas = Object.keys(sovMap).sort(function(a,b){
    var ta = sovMap[a].abbvie+sovMap[a].comp;
    var tb = sovMap[b].abbvie+sovMap[b].comp;
    return tb - ta;
  });
  var sovHtml;
  var totalMentions = sovAreas.reduce(function(s,a){return s+sovMap[a].abbvie+sovMap[a].comp;},0);
  if(totalMentions === 0){
    sovHtml = "<p class='empty'>No brand mentions in current filter view.</p>";
  } else {
    sovHtml = sovAreas.map(function(ta){
      var d = sovMap[ta];
      var tot = d.abbvie + d.comp;
      if(tot === 0) return '';
      var abbviePct = Math.round(100*d.abbvie/tot);
      var compPct   = 100 - abbviePct;
      return "<div class='sov-row'>" +
        "<div class='sov-label' title='"+esc(ta)+"'>"+esc(ta)+"</div>" +
        "<div class='sov-track'>" +
          "<div class='sov-abbvie' style='width:"+abbviePct+"%'></div>" +
          "<div class='sov-comp'   style='width:"+compPct+"%'></div>" +
        "</div>" +
        "<div class='sov-meta'>AbbVie "+esc(abbviePct)+"% &middot; "+esc(tot)+" mentions</div>" +
        "</div>";
    }).join('');
    sovHtml += "<div style='display:flex;gap:1.2rem;margin:.7rem 0 0;font-family:var(--mono);font-size:10px;color:var(--ink-faint)'>" +
      "<span><span style='display:inline-block;width:12px;height:12px;background:var(--accent);border-radius:2px;vertical-align:middle;margin-right:.3rem'></span>AbbVie</span>" +
      "<span><span style='display:inline-block;width:12px;height:12px;background:#d9a64b;border-radius:2px;vertical-align:middle;margin-right:.3rem'></span>Competitor</span>" +
      "</div>";
  }

  /* -- 2. Competitive Positioning Mix (by AbbVie brand) -- */
  var POSITIONS = ['FIRST_LINE_RECOMMENDED','AMONG_OPTIONS','SECOND_LINE','NOT_RECOMMENDED','NOT_MENTIONED'];
  var POS_COLORS = {
    FIRST_LINE_RECOMMENDED: '#2f7d5b',
    AMONG_OPTIONS:          '#5ba4a0',
    SECOND_LINE:            '#c9922a',
    NOT_RECOMMENDED:        '#9f3a2f',
    NOT_MENTIONED:          '#c0b8a8'
  };
  var POS_LABELS = {
    FIRST_LINE_RECOMMENDED: '1st Line',
    AMONG_OPTIONS:          'Among Options',
    SECOND_LINE:            '2nd Line',
    NOT_RECOMMENDED:        'Not Recommended',
    NOT_MENTIONED:          'Not Mentioned'
  };

  var posMap = {}; /* brand -> {pos->count, total} */
  rows.forEach(function(r){
    if(!r.competitive_position) return;
    var brand = r.brand_focus;
    if(!brand) return;
    if(!posMap[brand]) { posMap[brand] = {total:0}; POSITIONS.forEach(function(p){ posMap[brand][p]=0; }); }
    if(posMap[brand][r.competitive_position] !== undefined) posMap[brand][r.competitive_position]++;
    posMap[brand].total++;
  });
  var posKeys = Object.keys(posMap).filter(function(b){
    return DATA.abbvie_brands.length === 0 || DATA.abbvie_brands.indexOf(b) >= 0;
  }).sort();
  /* If no abbvie brands configured, show all brands */
  if(posKeys.length === 0) posKeys = Object.keys(posMap).sort();

  var posLegend = "<div class='pos-legend'>" +
    POSITIONS.map(function(p){
      return "<span class='pos-swatch'><span style='background:"+POS_COLORS[p]+"'></span>"+esc(POS_LABELS[p])+"</span>";
    }).join('') +
    "</div>";

  var posHtml;
  if(posKeys.length === 0){
    posHtml = "<p class='empty'>No competitive position data in current filter view.</p>";
  } else {
    posHtml = posLegend + posKeys.map(function(brand){
      var d = posMap[brand] || {};
      var tot = d.total || 0;
      if(tot === 0) return '';
      var segments = POSITIONS.map(function(p){
        var cnt = d[p] || 0;
        var pct = Math.round(100*cnt/tot);
        return cnt > 0
          ? "<div style='width:"+pct+"%;height:100%;background:"+POS_COLORS[p]+";flex-shrink:0' title='"+esc(POS_LABELS[p])+": "+esc(cnt)+"'></div>"
          : '';
      }).join('');
      return "<div class='pos-row'>" +
        "<div class='pos-label' title='"+esc(brand)+"'>"+esc(brand)+"</div>" +
        "<div class='pos-track'>"+segments+"</div>" +
        "<div class='pos-meta'>n="+esc(tot)+"</div>" +
        "</div>";
    }).join('');
    if(!posHtml.trim()){
      posHtml = "<p class='empty'>No competitive position data in current filter view.</p>";
    }
  }

  /* -- 3. Therapy x Model favorability heatmap -- */
  var heatBrands = [];
  var heatModels = [];
  var heatData   = {}; /* brand|model -> [scores] */
  rows.forEach(function(r){
    if(r.sentiment_score == null || typeof r.sentiment_score !== 'number') return;
    var brand = r.brand_focus; var model = r.llm_name;
    if(!brand || !model) return;
    if(heatBrands.indexOf(brand) < 0) heatBrands.push(brand);
    if(heatModels.indexOf(model) < 0) heatModels.push(model);
    var key = brand+'|'+model;
    if(!heatData[key]) heatData[key] = [];
    heatData[key].push(r.sentiment_score);
  });
  heatBrands.sort(); heatModels.sort();

  function sentColor(v){
    /* v in [-1,1]; negative->oxblood, 0->amber, positive->green */
    if(v < 0){
      var t = Math.min(1, -v);
      /* amber(169,121,26) -> oxblood(159,58,47) */
      var r2 = Math.round(169 + t*(159-169));
      var g2 = Math.round(121 + t*(58-121));
      var b2 = Math.round(26  + t*(47-26));
      return 'rgb('+r2+','+g2+','+b2+')';
    } else {
      var t2 = Math.min(1, v);
      /* amber(169,121,26) -> green(47,125,91) */
      var r3 = Math.round(169 + t2*(47-169));
      var g3 = Math.round(121 + t2*(125-121));
      var b3 = Math.round(26  + t2*(91-26));
      return 'rgb('+r3+','+g3+','+b3+')';
    }
  }
  function textOnBg(v){
    /* dark text on light amber, light text on deep colors */
    return (v > -0.3 && v < 0.3) ? '#5a3c00' : '#f2efe6';
  }

  var heatHtml;
  if(heatBrands.length === 0 || heatModels.length === 0){
    heatHtml = "<p class='empty'>No scored records in current filter view.</p>";
  } else {
    var headerCells = heatModels.map(function(m){ return "<th>"+esc(m)+"</th>"; }).join('');
    var rows2 = heatBrands.map(function(brand){
      var cells = heatModels.map(function(model){
        var key = brand+'|'+model;
        var scores = heatData[key];
        if(!scores || scores.length === 0){
          return "<td class='cell empty'>&mdash;</td>";
        }
        var avg = scores.reduce(function(s,x){return s+x;},0)/scores.length;
        var bg  = sentColor(avg);
        var col = textOnBg(avg);
        return "<td class='cell' style='background:"+bg+";color:"+col+"'>"+avg.toFixed(2)+"</td>";
      }).join('');
      return "<tr><td class='row-head'>"+esc(brand)+"</td>"+cells+"</tr>";
    }).join('');

    var hmScale = "<div class='hmscale'>" +
      "<span>&minus;1</span><div class='hmscale-bar'></div><span>+1</span>" +
      "<span style='margin-left:.4rem;color:var(--ink-faint)'>(avg sentiment)</span></div>";

    heatHtml = "<div class='heatmap-wrap'>" +
      "<table class='heatmap-tbl'>" +
      "<thead><tr><th>Brand / Model</th>"+headerCells+"</tr></thead>" +
      "<tbody>"+rows2+"</tbody>" +
      "</table></div>" + hmScale;
  }

  /* -- 4. Sentiment trend over time (inline SVG) -- */
  /* Collect per-brand-per-date avg sentiment */
  var trendBrands = [];
  var trendDates  = [];
  var trendMap    = {}; /* brand|date -> [scores] */
  rows.forEach(function(r){
    if(r.sentiment_score == null || typeof r.sentiment_score !== 'number') return;
    var brand = r.brand_focus; var date = r.date;
    if(!brand || !date) return;
    if(trendBrands.indexOf(brand) < 0) trendBrands.push(brand);
    if(trendDates.indexOf(date)   < 0) trendDates.push(date);
    var key = brand+'|'+date;
    if(!trendMap[key]) trendMap[key] = [];
    trendMap[key].push(r.sentiment_score);
  });
  trendBrands.sort(); trendDates.sort();

  var TREND_COLORS = ['#1f5c4d','#c9922a','#4a7db5','#9f3a2f','#6a5acd','#2f7d5b','#d9a64b'];

  var trendHtml;
  if(trendDates.length < 2){
    trendHtml = "<p class='empty'>Trend requires at least 2 distinct dates with scored records; not enough data in current filter view.</p>";
  } else {
    var W = 720, H = 240;
    var padL = 48, padR = 24, padT = 18, padB = 48;
    var plotW = W - padL - padR;
    var plotH = H - padT - padB;
    var nDates  = trendDates.length;
    var xStep   = nDates > 1 ? plotW / (nDates - 1) : plotW;

    function xOf(i){ return padL + i * xStep; }
    function yOf(v){ /* v in [-1,1] -> pixel */ return padT + plotH * (1 - (v + 1) / 2); }

    /* Gridlines & axes */
    var svgParts = [];
    svgParts.push('<svg xmlns="http://www.w3.org/2000/svg" width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" style="font-family:monospace;overflow:visible">');

    /* y-axis ticks at -1, 0, 1 */
    [-1, 0, 1].forEach(function(v){
      var y = yOf(v);
      var col = v === 0 ? '#c9922a' : '#ddd5c4';
      var dash = v === 0 ? '' : ' stroke-dasharray="4 3"';
      svgParts.push('<line x1="'+padL+'" y1="'+y+'" x2="'+(padL+plotW)+'" y2="'+y+'" stroke="'+col+'" stroke-width="'+(v===0?1.5:1)+'"'+dash+'/>');
      svgParts.push('<text x="'+(padL-6)+'" y="'+y+'" text-anchor="end" dominant-baseline="middle" font-size="10" fill="#8c8a7e">'+(v>=0?'+':'')+v+'</text>');
    });

    /* x-axis date labels: show first, last, and up to 3 middle ones */
    var labelIdxSet = [0, nDates-1];
    if(nDates > 2){
      var mid = Math.floor(nDates/2);
      labelIdxSet.push(mid);
      if(nDates > 4){ labelIdxSet.push(Math.floor(nDates/4)); labelIdxSet.push(Math.floor(3*nDates/4)); }
    }
    var labelIdxUniq = labelIdxSet.filter(function(x,i,a){ return a.indexOf(x)===i; }).sort(function(a,b){return a-b;});
    labelIdxUniq.forEach(function(i){
      var x = xOf(i);
      var d = trendDates[i];
      var label = d.length >= 10 ? d.slice(5) : d; /* MM-DD */
      svgParts.push('<line x1="'+x+'" y1="'+(padT+plotH)+'" x2="'+x+'" y2="'+(padT+plotH+4)+'" stroke="#c0b8a8" stroke-width="1"/>');
      svgParts.push('<text x="'+x+'" y="'+(padT+plotH+14)+'" text-anchor="middle" font-size="9" fill="#8c8a7e">'+esc(label)+'</text>');
    });

    /* Polylines per brand */
    trendBrands.forEach(function(brand, bi){
      var color = TREND_COLORS[bi % TREND_COLORS.length];
      var points = trendDates.map(function(date, di){
        var key = brand+'|'+date;
        var sc  = trendMap[key];
        if(!sc || sc.length === 0) return null;
        var avg = sc.reduce(function(s,x){return s+x;},0)/sc.length;
        return xOf(di)+','+yOf(avg);
      }).filter(function(p){ return p !== null; });
      if(points.length >= 1){
        svgParts.push('<polyline points="'+points.join(' ')+'" fill="none" stroke="'+color+'" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>');
        /* dots */
        points.forEach(function(pt){
          var xy = pt.split(',');
          svgParts.push('<circle cx="'+xy[0]+'" cy="'+xy[1]+'" r="3" fill="'+color+'" stroke="#fbf9f4" stroke-width="1.5"/>');
        });
      }
    });

    svgParts.push('</svg>');
    var svgEl = svgParts.join('');

    var legendItems = trendBrands.map(function(brand, bi){
      var color = TREND_COLORS[bi % TREND_COLORS.length];
      return "<span class='trend-swatch'><span style='background:"+color+"'></span>"+esc(brand)+"</span>";
    }).join('');

    trendHtml = "<div class='trend-legend'>"+legendItems+"</div>" +
      "<div class='trend-svg-wrap'>"+svgEl+"</div>";
  }

  /* -- Assemble -- */
  document.getElementById('view-marketing').innerHTML =
    "<div class='card'><h2>Share of Voice</h2>" +
    "<p class='hint'>Brand mentions per therapeutic area — AbbVie vs. competitor.</p>" +
    sovHtml + "</div>" +

    "<div class='card'><h2>Competitive Positioning Mix</h2>" +
    "<p class='hint'>Distribution of competitive position by AbbVie brand (scored records only).</p>" +
    posHtml + "</div>" +

    "<div class='card'><h2>Therapy &times; Model Favorability</h2>" +
    "<p class='hint'>Average sentiment score per brand / LLM pair. Cells with no data are muted.</p>" +
    heatHtml + "</div>" +

    "<div class='card'><h2>Sentiment Trend Over Time</h2>" +
    "<p class='hint'>Average sentiment per brand across dates (scored records). Requires ≥ 2 distinct dates.</p>" +
    trendHtml + "</div>";
}

/* ====================================================================
   renderMedical — Medical Affairs review queue
   ==================================================================== */
function renderMedical(rows){
  /* ---- 1. Summary counts ---- */
  var hallHigh   = rows.filter(function(r){ return r.hallucination_risk === 'HIGH'; }).length;
  var hallMedium = rows.filter(function(r){ return r.hallucination_risk === 'MEDIUM'; }).length;
  var hallLow    = rows.filter(function(r){ return r.hallucination_risk === 'LOW'; }).length;
  var hallNone   = rows.filter(function(r){ return r.hallucination_risk === 'NONE'; }).length;
  var driftCt    = rows.filter(function(r){
    return (r.alert_reasons||[]).some(function(a){ return a.startsWith('DRIFT:'); });
  }).length;
  var alertCt    = rows.filter(function(r){ return r.alert_triggered; }).length;

  var tilesHtml =
    "<div class='tiles'>" +
    "<div class='tile "+(hallHigh>0?'flag':'')+"'><div class='lab'>Hallucination HIGH</div><div class='num'>"+esc(hallHigh)+"</div></div>" +
    "<div class='tile "+(hallMedium>0?'warn':'')+"'><div class='lab'>Hallucination MEDIUM</div><div class='num'>"+esc(hallMedium)+"</div></div>" +
    "<div class='tile'><div class='lab'>Hallucination LOW</div><div class='num'>"+esc(hallLow)+"</div></div>" +
    "<div class='tile'><div class='lab'>Hallucination NONE</div><div class='num'>"+esc(hallNone)+"</div></div>" +
    "<div class='tile "+(driftCt>0?'warn':'')+"'><div class='lab'>Drift Alerts</div><div class='num'>"+esc(driftCt)+"</div></div>" +
    "<div class='tile "+(alertCt>0?'flag':'')+"'><div class='lab'>Alerts Triggered</div><div class='num'>"+esc(alertCt)+"</div></div>" +
    "</div>";

  var noteHtml = "<div class='med-note'>Review queue &mdash; approve or revise questions via the <code>ema</code> CLI (read-only view).</div>";

  /* ---- 2. Build review queue ---- */
  var HALL_NEEDS_REVIEW = {'HIGH':true,'MEDIUM':true};
  var queueRows = rows.filter(function(r){
    return r.alert_triggered || HALL_NEEDS_REVIEW[r.hallucination_risk];
  });

  /* Sort: HIGH hallucination first, then most flags, then others */
  queueRows.sort(function(a,b){
    var riskOrder = {HIGH:0,MEDIUM:1,LOW:2,NONE:3};
    var ra = riskOrder[a.hallucination_risk];
    var rb = riskOrder[b.hallucination_risk];
    if(ra !== undefined && rb !== undefined && ra !== rb) return ra - rb;
    if(ra !== undefined && rb === undefined) return -1;
    if(ra === undefined && rb !== undefined) return 1;
    var fa = (a.hallucination_flags||[]).length;
    var fb = (b.hallucination_flags||[]).length;
    if(fa !== fb) return fb - fa;
    return 0;
  });

  var queueHtml;
  if(queueRows.length === 0){
    queueHtml = "<p class='empty'>No items need review for the current filters.</p>";
  } else {
    queueHtml = queueRows.map(function(r, idx){
      var qtext  = r.question_text || '';
      var qshort = qtext.length > 90 ? qtext.slice(0,87)+'…' : qtext;
      var hrisk  = r.hallucination_risk || '';
      var flags  = r.hallucination_flags || [];
      var reasons= r.alert_reasons || [];

      /* Risk CSS class for left-border accent */
      var riskCls = {HIGH:'risk-high',MEDIUM:'risk-medium',LOW:'risk-low',NONE:'risk-none'}[hrisk] || '';

      /* Badges */
      var badges = '';
      if(hrisk === 'HIGH'){
        badges += "<span class='badge badge-hall-high'>Hallucination: HIGH</span>";
      } else if(hrisk === 'MEDIUM'){
        badges += "<span class='badge badge-hall-medium'>Hallucination: MEDIUM</span>";
      } else if(hrisk === 'LOW'){
        badges += "<span class='badge badge-hall-low'>Hallucination: LOW</span>";
      }
      var hasDrift = reasons.some(function(a){ return a.startsWith('DRIFT:'); });
      if(hasDrift){
        badges += "<span class='badge badge-drift'>DRIFT</span>";
      }
      var hasOtherAlert = r.alert_triggered && reasons.some(function(a){
        return !a.startsWith('DRIFT:') && !a.startsWith('HALLUCINATION:');
      });
      if(hasOtherAlert){
        badges += "<span class='badge badge-alert'>Alert</span>";
      }

      /* Flagged claims section */
      var claimsHtml = '';
      if(flags.length > 0){
        var flagItems = flags.map(function(f){
          var sevCls = {HIGH:'sev-high',MEDIUM:'sev-medium',LOW:'sev-low'}[f.severity] || '';
          return "<div class='qd-claim'>" +
            "<div class='qd-claim-text'>"+esc(f.claim||'')+"</div>" +
            "<div class='qd-claim-conflict'>conflicts with: "+esc(f.conflicts_with||'')+"</div>" +
            (f.severity ? "<span class='badge "+sevCls+"' style='margin-top:.25rem;display:inline-block'>"+esc(f.severity)+"</span>" : '') +
            "</div>";
        }).join('');
        claimsHtml =
          "<div class='qd-section'>" +
          "<div class='qd-label'>Flagged Claims</div>" +
          flagItems +
          "</div>";
      }

      /* Signals chips */
      var signalParts = [];
      if(r.confidence_level){
        signalParts.push("<span class='signal-chip'><span class='sc-label'>Confidence</span>"+esc(r.confidence_level)+"</span>");
      }
      if(r.citation_quality){
        signalParts.push("<span class='signal-chip'><span class='sc-label'>Citation</span>"+esc(r.citation_quality)+"</span>");
      }
      var signalsHtml = signalParts.length > 0
        ? "<div class='qd-section'><div class='qd-label'>Signals</div><div class='signal-chips'>"+signalParts.join('')+"</div></div>"
        : '';

      /* Alert reasons */
      var alertReasonsHtml = '';
      if(reasons.length > 0){
        var reasonItems = reasons.map(function(a){
          return "<div style='font-size:12px;color:var(--neg);margin:.1rem 0'>"+esc(a)+"</div>";
        }).join('');
        alertReasonsHtml =
          "<div class='qd-section'><div class='qd-label'>Alert Reasons</div>"+reasonItems+"</div>";
      }

      var detailId = 'qdet-'+idx;

      return "<div class='queue-item "+riskCls+"'>" +
        "<div class='queue-item-header' onclick=\"var d=document.getElementById('"+detailId+"');d.classList.toggle('open')\">" +
          "<span class='qi-id'>"+esc(r.question_id)+"</span>" +
          "<span class='qi-text' title='"+esc(qtext)+"'>"+esc(qshort)+"</span>" +
          "<span class='qi-meta'>"+esc(r.llm_name)+" &middot; "+esc(r.brand_focus)+"</span>" +
          "<span class='qi-badges'>"+badges+"</span>" +
        "</div>" +
        "<div class='queue-detail' id='"+detailId+"'>" +
          claimsHtml +
          "<div class='qd-section'><div class='qd-label'>Full Response</div><div class='qd-value'>"+esc(r.response_text||'')+"</div></div>" +
          "<div class='qd-section'><div class='qd-label'>Scoring Rationale</div><div class='qd-value'>"+esc(r.scoring_rationale||'')+"</div></div>" +
          signalsHtml +
          alertReasonsHtml +
        "</div>" +
        "</div>";
    }).join('');
  }

  document.getElementById('view-medical').innerHTML =
    tilesHtml +
    noteHtml +
    "<div class='card'>" +
    "<h2>Review Queue</h2>" +
    "<p class='hint'>Responses requiring Medical Affairs attention: hallucination risk MEDIUM/HIGH or alert triggered.</p>" +
    queueHtml +
    "</div>";
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
        "<section id='view-marketing' class='view'></section>"
        "<section id='view-medical' class='view'></section>"
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
