# Playground ↔ Dashboard Navigation — Design

**Date:** 2026-06-14
**Status:** Approved
**Addresses:** The playground (`ema serve`) and the dashboard were unconnected —
no way to navigate between them. Serve the dashboard from the playground server
and add cross-links.

## Decision

- Add **`GET /dashboard`** to the FastAPI playground app — builds the dashboard
  live from the current DB (`collect_dataset` + `render_dashboard_html`) and
  returns it as HTML. Always fresh while the server runs.
- Add a **"Dashboard"** link in the playground header (→ `/dashboard`).
- Add a **"← Playground"** back-link in the dashboard, but only when it is served
  by the route (a relative `/` link works there). The standalone `ema dashboard`
  file keeps no link (a `file://` page can't assume a running server).

## Components

### `render_dashboard_html(dataset, *, playground_url: str | None = None)`
Optional param; when set, the page renders a back-link `← Playground` pointing at
`playground_url`. When `None` (the standalone `ema dashboard` build), no link.

### `GET /dashboard` (ema_poc/web/app.py)
```
conn = connect(deps.db_path); init_schema(conn)
dataset = collect_dataset(conn, abbvie_brands=deps.config.brands.abbvie_brands,
                          competitor_brands=deps.config.brands.competitor_brands)
html = render_dashboard_html(dataset, playground_url="/")
return HTMLResponse(html)   # close the conn in a finally
```

### Playground header (ema_poc/web/static/index.html)
Add an `<a href="/dashboard">Dashboard</a>` link in the header next to the title.

## Testing (offline)
- FastAPI `TestClient`: `GET /dashboard` → 200, `text/html`, contains the dashboard
  section markers (`id="view-overview"`, etc.) and the `← Playground` link to `/`.
- `render_dashboard_html(dataset, playground_url="/")` includes the back-link;
  `render_dashboard_html(dataset)` (default) does NOT (standalone `ema dashboard`
  output unchanged — existing dashboard tests still pass).
- The served index page contains the `href="/dashboard"` link.

## Out of scope (deferrable)
- Caching the built dashboard (rebuilds per request — fine at POC scale).
- A shared top-nav component / SPA routing.
