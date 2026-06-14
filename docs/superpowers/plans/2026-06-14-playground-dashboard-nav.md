# Playground ↔ Dashboard Navigation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Serve the dashboard from the playground server at `/dashboard` and add cross-links so the two views are one connected app.

**Branch:** `feature/playground-dashboard-nav`. **Spec:** `docs/superpowers/specs/2026-06-14-playground-dashboard-nav-design.md`.

---

### Task 1: `/dashboard` route + back-link param + playground header link

**Files:** `ema_poc/dashboard/render.py`, `ema_poc/web/app.py`, `ema_poc/web/static/index.html`, tests `tests/dashboard/test_dashboard_render.py`, `tests/web/test_app.py`.

- **render.py** — change `render_dashboard_html(dataset: dict)` to `render_dashboard_html(dataset: dict, *, playground_url: str | None = None)`. When `playground_url` is not None, render a back-link near the top of the page body (above or in the masthead/header area), e.g. `<a href="{escaped playground_url}" class="backlink">← Playground</a>` (escape the url with the existing `_e`/`esc` helper). When None, render nothing extra (existing output unchanged). Add minimal CSS for `.backlink` (small, unobtrusive) to the inline style.
- **app.py** — add a `GET /dashboard` route to `create_app`:
```python
    from fastapi.responses import HTMLResponse
    from ema_poc.db import connect, init_schema
    from ema_poc.dashboard.dataset import collect_dataset
    from ema_poc.dashboard.render import render_dashboard_html

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard():
        conn = connect(deps.db_path)
        try:
            init_schema(conn)
            dataset = collect_dataset(
                conn,
                abbvie_brands=deps.config.brands.abbvie_brands,
                competitor_brands=deps.config.brands.competitor_brands,
            )
        finally:
            conn.close()
        return HTMLResponse(render_dashboard_html(dataset, playground_url="/"))
```
  (Match the import style already in app.py — it lazily imports inside functions in places; keep these imports at the top of create_app or module top, consistent with the existing SSE route's imports. `deps` is the WebDeps in scope.)
- **index.html** — in the `<header>`, add a Dashboard link next to the title, e.g.:
```html
<header><h1>Evidence Monitoring &mdash; Real-Time Playground</h1>
<a href="/dashboard" class="navlink">Dashboard &rarr;</a></header>
```
  Add a small CSS rule for `.navlink` (e.g. float right or inline, light color on the dark header). Keep the page self-contained (no external resources).
- **Tests:**
  - `tests/web/test_app.py`: with the existing `_deps(tmp_path)` (its db_path points at a tmp sqlite — init it if needed), `TestClient(create_app(deps)).get("/dashboard")` → status 200, `"text/html" in content-type`, body contains `id="view-overview"` (a dashboard section marker) and `← Playground` (the back-link) and `href="/"`. (The tmp DB may be empty — collect_dataset on an empty DB returns an empty dataset and render still produces the page; ensure `_deps`'s db_path is a path where connect+init_schema works. If `_deps` doesn't set a real db_path, set `db_path=str(tmp_path/"w.sqlite")`.)
  - `tests/web/test_app.py`: the index page (`GET /`) contains `href="/dashboard"`.
  - `tests/dashboard/test_dashboard_render.py`: `render_dashboard_html(<dataset>, playground_url="/")` contains `← Playground` and `href="/"`; `render_dashboard_html(<dataset>)` (no playground_url) does NOT contain `← Playground` (standalone build unchanged). Keep all existing dashboard render tests passing (they call `render_dashboard_html(dataset)` with no kwarg — the default None preserves current output, so they must still pass).

Run FULL suite until green (expect ~600). Commit:
```bash
git add ema_poc/dashboard/render.py ema_poc/web/app.py ema_poc/web/static/index.html tests/
git commit -m "feat: serve dashboard at /dashboard from playground + cross-nav links"
```

---

## Self-Review Notes (author)
- Back-link only when playground_url provided → standalone `ema dashboard` output unchanged (existing tests pass).
- /dashboard builds live from deps.db_path + config brands; conn closed in finally.
- Self-contained: links are relative/internal; no external resources.
- index.html stays XSS-safe (static link, no dynamic interpolation).
