"""Append-only storage for hallucination checks + flagged claims."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from uuid import uuid4


@dataclass
class CheckRow:
    response_id: str
    risk_level: str
    rationale: str | None
    model: str
    created_at: str


@dataclass
class FlagRow:
    flag_id: str
    response_id: str
    claim: str
    conflicts_with: str | None
    severity: str
    created_at: str


def save_check(conn, *, response_id, risk_level, rationale, model, now, commit=True) -> None:
    conn.execute(
        """INSERT INTO hallucination_checks (response_id, risk_level, rationale, model, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (response_id, risk_level, rationale, model, now),
    )
    if commit:
        conn.commit()


def save_flags(conn, *, response_id, flags, now, id_factory=lambda: uuid4().hex, commit=True) -> None:
    """flags: iterable of objects with .claim, .conflicts_with, .severity (or dicts).
    No-op on empty."""
    items = list(flags)
    if not items:
        return
    for f in items:
        claim = getattr(f, "claim", None) if not isinstance(f, dict) else f["claim"]
        conflicts = getattr(f, "conflicts_with", None) if not isinstance(f, dict) else f.get("conflicts_with")
        severity = getattr(f, "severity", None) if not isinstance(f, dict) else f["severity"]
        conn.execute(
            """INSERT INTO hallucination_flags
               (flag_id, response_id, claim, conflicts_with, severity, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (id_factory(), response_id, claim, conflicts, severity, now),
        )
    if commit:
        conn.commit()


def has_check(conn, response_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM hallucination_checks WHERE response_id = ?", (response_id,)
    ).fetchone() is not None


def get_check(conn, response_id) -> CheckRow | None:
    row = conn.execute(
        "SELECT response_id, risk_level, rationale, model, created_at "
        "FROM hallucination_checks WHERE response_id = ?", (response_id,)
    ).fetchone()
    return CheckRow(**dict(row)) if row else None


def list_flags(conn, response_id) -> list[FlagRow]:
    rows = conn.execute(
        "SELECT flag_id, response_id, claim, conflicts_with, severity, created_at "
        "FROM hallucination_flags WHERE response_id = ? ORDER BY created_at, flag_id",
        (response_id,),
    ).fetchall()
    return [FlagRow(**dict(r)) for r in rows]
