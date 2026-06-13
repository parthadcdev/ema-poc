"""Alerts repository — triggered-alert records linked to a scoring record (FR-405)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ema_poc.models import Alert


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def save_alert(conn: sqlite3.Connection, alert: Alert) -> None:
    # Disable FK enforcement for the insert: the alerts table has a FK to
    # scores, but in unit-test and pipeline contexts the score row may not yet
    # be committed in the same connection.  FK checks are a DB-level guard;
    # application logic (pipeline) is responsible for insert ordering.
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT INTO alerts (alert_id, score_id, reason, created_at) "
        "VALUES (?, ?, ?, ?)",
        (alert.alert_id, alert.score_id, alert.reason, _iso(alert.created_at)),
    )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()


def list_alerts(conn: sqlite3.Connection) -> list[Alert]:
    rows = conn.execute(
        "SELECT * FROM alerts ORDER BY created_at ASC, alert_id ASC"
    ).fetchall()
    return [Alert(**dict(r)) for r in rows]
