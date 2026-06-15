# Safe Markdown Rendering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Render LLM response markdown (headings/bold/lists/tables/code/links) formatted + XSS-safe in the dashboard and playground, self-contained.

**Branch:** `feature/markdown-rendering`. **Spec:** `docs/superpowers/specs/2026-06-15-markdown-rendering-design.md`.

## Reference `renderMarkdown` (add VERBATIM to BOTH files' inline JS)
```javascript
function renderMarkdown(src){
  if (src == null) return "";
  function mdEsc(s){ return String(s).replace(/[&<>"']/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]; }); }
  function mdUrl(u){ u = String(u||""); return /^https?:\/\//i.test(u) ? u : "#"; }
  function inl(s){
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function(m,t,u){
      return '<a href="' + mdEsc(mdUrl(u)) + '" target="_blank" rel="noopener noreferrer">' + t + '</a>'; });
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
    return s;
  }
  var lines = mdEsc(src).split(/\r?\n/), out = [], i = 0;
  function cells(row){
    var c = row.split('|'); 
    if (c.length && c[0].trim()==='') c.shift();
    if (c.length && c[c.length-1].trim()==='') c.pop();
    return c.map(function(x){ return x.trim(); });
  }
  while (i < lines.length){
    var line = lines[i];
    if (/^```/.test(line)){ var b=[]; i++; while(i<lines.length && !/^```/.test(lines[i])){ b.push(lines[i]); i++; } i++;
      out.push('<pre><code>'+b.join('\n')+'</code></pre>'); continue; }
    if (/\|/.test(line) && i+1<lines.length && /-/.test(lines[i+1]) && /^[\s|:-]+$/.test(lines[i+1])){
      var head=cells(line); i+=2; var rows=[];
      while(i<lines.length && /\|/.test(lines[i]) && lines[i].trim()!==''){ rows.push(cells(lines[i])); i++; }
      out.push('<table class="md-table"><thead><tr>'+head.map(function(h){return '<th>'+inl(h)+'</th>';}).join('')+
        '</tr></thead><tbody>'+rows.map(function(r){return '<tr>'+r.map(function(c){return '<td>'+inl(c)+'</td>';}).join('')+'</tr>';}).join('')+
        '</tbody></table>'); continue; }
    var h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h){ out.push('<h'+h[1].length+'>'+inl(h[2])+'</h'+h[1].length+'>'); i++; continue; }
    if (/^&gt;\s?/.test(line)){ var q=[]; while(i<lines.length && /^&gt;\s?/.test(lines[i])){ q.push(lines[i].replace(/^&gt;\s?/,'')); i++; }
      out.push('<blockquote>'+inl(q.join(' '))+'</blockquote>'); continue; }
    if (/^\s*[-*+]\s+/.test(line)){ var u=[]; while(i<lines.length && /^\s*[-*+]\s+/.test(lines[i])){ u.push(lines[i].replace(/^\s*[-*+]\s+/,'')); i++; }
      out.push('<ul>'+u.map(function(it){return '<li>'+inl(it)+'</li>';}).join('')+'</ul>'); continue; }
    if (/^\s*\d+\.\s+/.test(line)){ var o=[]; while(i<lines.length && /^\s*\d+\.\s+/.test(lines[i])){ o.push(lines[i].replace(/^\s*\d+\.\s+/,'')); i++; }
      out.push('<ol>'+o.map(function(it){return '<li>'+inl(it)+'</li>';}).join('')+'</ol>'); continue; }
    if (/^\s*$/.test(line)){ i++; continue; }
    var p=[line]; i++;
    while(i<lines.length && !/^\s*$/.test(lines[i]) && !/^(#{1,6}\s|&gt;|\s*[-*+]\s|\s*\d+\.\s|```)/.test(lines[i]) && !/\|/.test(lines[i])){ p.push(lines[i]); i++; }
    out.push('<p>'+inl(p.join(' '))+'</p>');
  }
  return out.join('');
}
```
NOTE: blockquote regex matches `&gt;` (because the whole input is escaped first, a leading `>` becomes `&gt;`). This is intentional — keep it.

---

### Task 1: Dashboard — renderMarkdown + apply + CSS

**Files:** `ema_poc/dashboard/render.py` (the inline JS string `_JS`/the renderers + the `_CSS`), `tests/dashboard/test_dashboard_render.py`.

- Add the reference `renderMarkdown` to the dashboard's inline JS (near `esc`).
- In `renderResponses` detail panel: render `response_text` and the scoring `rationale` via `'<div class="md">' + renderMarkdown(value) + '</div>'` (innerHTML) instead of the current escaped/`pre-wrap` text. (Keep question text + other fields as-is.)
- In `renderMedical` queue detail: render the full **response** via `renderMarkdown` inside `.md`. Leave flagged-claim `claim`/`conflicts_with` as plain `esc()` (short).
- Add `.md` CSS to `_CSS` (scope everything under `.md`): readable `h1..h6` (smaller than page headings, tight margins), `p` (line-height ~1.55), `ul/ol` (proper indentation), `code` (mono, tinted bg, small padding), `pre` (tinted block, overflow-x auto), `.md-table` (compact, bordered, header tint), `blockquote` (accent left border), `a` (brand accent). Keep it cohesive with the AbbVie/readable theme.
- Tests (`tests/dashboard/test_dashboard_render.py`):
  - the rendered page source contains `function renderMarkdown` and at least one `renderMarkdown(` call in the response/medical render path.
  - structural XSS guard: assert the source escapes-first — e.g. assert the function body calls `mdEsc(src)` before any markdown regex (a simple `assert "mdEsc(src)" in html` plus `assert "renderMarkdown" in html`). 
  - existing self-contained + section-marker + embedded-JSON tests still pass.
- Regenerate against the demo DB and eyeball it builds + self-contained:
  `source .venv/bin/activate && python -c "from ema_poc.db import connect, init_schema; from ema_poc.dashboard.build import build_dashboard; c=connect('ema_demo.sqlite'); init_schema(c); build_dashboard(c,'/tmp/md.html', abbvie_brands=['Skyrizi'], competitor_brands=['Stelara'])"` then `grep -c '<script src\|<link ' /tmp/md.html` == 0.

Commit:
```bash
git add ema_poc/dashboard/render.py tests/dashboard/test_dashboard_render.py
git commit -m "feat: render response markdown (safe) in dashboard responses + MA review"
```

### Task 2: Playground — renderMarkdown + apply + CSS

**Files:** `ema_poc/web/static/index.html`, `tests/web/test_app.py`.

- Add the SAME reference `renderMarkdown` to the playground inline JS (near `esc`/`safeUrl`).
- In the `answer` event handler, change the answer fill from
  `card.querySelector(".answer").textContent = ev.answer_text || ...`
  to set `.innerHTML = '<div class="md">' + renderMarkdown(ev.answer_text || ("(no answer — " + esc(ev.status) + ")")) + '</div>';`
  (note: when answer_text is empty, the fallback string is developer-controlled; renderMarkdown still escapes it. Keep the citations block + score chip logic unchanged.)
- Add `.md` CSS to the playground `<style>` (same scope/rules as Task 1, fitted to the card width — readable headings, lists, compact tables with horizontal scroll, code, links in accent).
- Tests (`tests/web/test_app.py`): the served index contains `function renderMarkdown`, the `.answer` path calls `renderMarkdown(`, and `esc`/`safeUrl` still present. Self-contained markers unchanged.
- Manual: `ema serve` still starts; the page is self-contained (no external resources).

Commit:
```bash
git add ema_poc/web/static/index.html tests/web/test_app.py
git commit -m "feat: render answer markdown (safe) in playground cards"
```

---

## Self-Review Notes (author)
- escape-first then format → untrusted LLM/web text can't inject HTML; links http/https only; no `<img>` from input.
- Same `renderMarkdown` verbatim in both files (self-contained; no shared module possible across a static file + a python-string).
- `.md`-scoped CSS so markdown styling doesn't leak into the rest of the UI.
- All ids/JS/data-contract/self-contained preserved; existing XSS + self-contained tests stay green.
