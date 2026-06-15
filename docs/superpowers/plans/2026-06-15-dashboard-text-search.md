# Dashboard Text Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a global free-text search box to the dashboard filter bar that matches across all record text fields and is honored by every section, with a "Showing N of M" count.

**Architecture:** Pure client-side change to the self-contained dashboard HTML generator (`ema_poc/dashboard/render.py`). A search `<input>` feeds the existing `applyFilters()` predicate (which all sections already aggregate over). Substring, case-insensitive, whitespace-AND. A count indicator updates in the central `render()`.

**Tech Stack:** Vanilla JS in a self-contained HTML string (no external libs). Tests are structural string assertions (no JS runtime in CI), matching the existing render-test pattern.

**Spec:** `docs/superpowers/specs/2026-06-15-dashboard-text-search-design.md`. **Branch:** `feature/dashboard-search`.

**Run the suite with the venv:** `.venv/bin/python -m pytest`. Baseline is **652 passing**.

---

### Task 1: Global search box + filter predicate

**Files:**
- Modify: `ema_poc/dashboard/render.py` (filter-bar markup ~line 1186; `applyFilters` ~line 503; filter listener ~line 537; reset handler ~line 541; filter-bar CSS ~line 137)
- Test: `tests/dashboard/test_dashboard_render.py` (append, uses the existing `html` fixture)

- [ ] **Step 1: Write the failing test** — append to `tests/dashboard/test_dashboard_render.py` (take `html` as the test arg, like the existing tests):

```python
def test_dashboard_has_search_input(html):
    assert "id='f-search'" in html
    assert "type='search'" in html


def test_dashboard_search_helper_and_predicate(html):
    assert "function _searchable" in html          # concatenates the text fields
    assert "_searchable(" in html                  # used in the filter predicate
    assert "f-search" in html                      # read in applyFilters


def test_dashboard_search_in_reset(html):
    # the reset handler clears the search box too
    assert "getElementById('f-search').value" in html
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/dashboard/test_dashboard_render.py -k search -v`
Expected: FAIL (no `f-search` / `_searchable`).

- [ ] **Step 3: Implement** (in `ema_poc/dashboard/render.py`)

(a) **Filter-bar markup** — add the search input as the FIRST control inside the `"<div class='filter-bar'>"` block (immediately before the Therapeutic Area `<label>` line):
```python
        "<label>Search<input type='search' id='f-search' placeholder='Search all text…'></label>"
```

(b) **CSS** — extend the existing input-style rule so `type=search` matches the other controls. Change the selector at line ~137 from:
```python
".filter-bar select,.filter-bar input[type=date]{"
```
to:
```python
".filter-bar select,.filter-bar input[type=date],.filter-bar input[type=search]{"
```
(Give the search input a touch more width: append a dedicated rule right after that block:)
```python
".filter-bar input[type=search]{min-width:200px}"
```

(c) **`_searchable` helper + search read in `applyFilters`** — replace the `applyFilters` function (lines ~503-519) with:
```javascript
function _searchable(r){
  return [r.question_text, r.response_text, r.scoring_rationale, r.brand_focus,
          r.llm_name, r.persona, r.therapeutic_area, r.domain,
          r.competitive_position, r.status,
          (r.brand_mentions || []).join(' ')].join(' ').toLowerCase();
}
function applyFilters(){
  const ta      = document.getElementById('f-ta').value;
  const brand   = document.getElementById('f-brand').value;
  const llm     = document.getElementById('f-llm').value;
  const persona = document.getElementById('f-persona').value;
  const source  = document.getElementById('f-source').value;
  const from    = document.getElementById('f-from').value;
  const to      = document.getElementById('f-to').value;
  const terms   = document.getElementById('f-search').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return DATA.records.filter(function(r){
    if(ta      && r.therapeutic_area !== ta)    return false;
    if(brand   && r.brand_focus      !== brand) return false;
    if(llm     && r.llm_name         !== llm)   return false;
    if(persona && r.persona          !== persona) return false;
    if(source  && r.source           !== source) return false;
    if(from    && r.date < from)                return false;
    if(to      && r.date > to)                  return false;
    if(terms.length){
      var hay = _searchable(r);
      for(var i=0;i<terms.length;i++){ if(hay.indexOf(terms[i]) < 0) return false; }
    }
    return true;
  });
}
```
> Preserve the EXACT existing predicate lines for ta/brand/llm/persona/source/from/to — only add the `terms` read and the `if(terms.length){...}` block. Read the real current function first and keep its formatting.

(d) **Filter listener** — add `#f-search` to the existing `querySelectorAll` (line ~537), keeping the rest of the selector identical:
```javascript
document.querySelectorAll('#f-ta,#f-brand,#f-llm,#f-persona,#f-source,#f-from,#f-to,#f-search').forEach(function(el){
```
(It already binds both `change` and `input`, so the search filters live as you type.)

(e) **Reset handler** — add, alongside the other resets (before `render();`):
```javascript
  document.getElementById('f-search').value  = '';
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/dashboard/test_dashboard_render.py -v`
Expected: PASS (new + all existing render tests, including `test_self_contained_no_external_urls`).

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest` (expect 652 + 3 new = 655).
```bash
git add ema_poc/dashboard/render.py tests/dashboard/test_dashboard_render.py
git commit -m "feat: global text search across all record fields in the dashboard"
```

---

### Task 2: "Showing N of M" result count

**Files:**
- Modify: `ema_poc/dashboard/render.py` (filter-bar markup; `render()` ~line 1141; CSS)
- Test: `tests/dashboard/test_dashboard_render.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_dashboard_has_result_count(html):
    assert "id='f-count'" in html
    assert "Showing " in html                      # render() sets "Showing N of M"
    assert "DATA.records.length" in html           # the M in N of M
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/dashboard/test_dashboard_render.py -k result_count -v`
Expected: FAIL (no `f-count`).

- [ ] **Step 3: Implement**

(a) **Markup** — add the count span to the filter bar, right after the Reset button line (`"<button id='f-reset'>Reset</button>"`):
```python
        "<span id='f-count' class='filter-count'></span>"
```

(b) **CSS** — add a rule (e.g. right after the `#f-reset` rules):
```python
".filter-count{font-family:var(--sans);font-size:12px;color:var(--ink-faint);align-self:flex-end;padding-bottom:.45rem}"
```

(c) **`render()` update** — in the central `render()` function (line ~1141), after `var rows = applyFilters();`, add:
```javascript
  document.getElementById('f-count').textContent = 'Showing ' + rows.length + ' of ' + DATA.records.length;
```
(Use `textContent` — the values are integers; nothing untrusted reaches the DOM.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/dashboard/test_dashboard_render.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest` (expect 655 + 1 new = 656).
```bash
git add ema_poc/dashboard/render.py tests/dashboard/test_dashboard_render.py
git commit -m "feat: dashboard 'Showing N of M' result count in the filter bar"
```

---

## Self-Review Notes (author)

- **Spec coverage:** search box + all-text-field substring + whitespace-AND + live + reset (T1); result count via render() (T2). Combines with existing filters because the search predicate is added inside the SAME `applyFilters` (AND). All spec sections mapped.
- **Type/name consistency:** `#f-search`, `_searchable(r)`, `terms` (whitespace-split, `.filter(Boolean)` drops empties), `#f-count`, `render()` sets `textContent`. Listener selector keeps all existing ids + `#f-search`.
- **Safety:** substring `indexOf` (no regex injection); search value never reaches innerHTML; count uses `textContent`. Self-contained preserved (no external resources) — guarded by the existing `test_self_contained_no_external_urls`.
- **No behavior change to existing filters:** only an added predicate block and an added listener id; the existing predicate lines are untouched.
