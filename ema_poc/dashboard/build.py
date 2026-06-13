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
