"""Build the self-contained HTML dashboard from the repository (FR-601/603)."""

from __future__ import annotations

import sqlite3

from ema_poc.dashboard.dataset import collect_dataset
from ema_poc.dashboard.render import render_dashboard_html


def build_dashboard(conn: sqlite3.Connection, out_path: str) -> str:
    """Render the dashboard for all data in `conn` and write it to `out_path`.

    Uses `collect_dataset` with empty brand lists (Task 5 wires real brands from
    config).  Returns the path written.
    """
    dataset = collect_dataset(conn, abbvie_brands=[], competitor_brands=[])
    html = render_dashboard_html(dataset)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out_path
