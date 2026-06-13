"""Append-only citation storage for grounded responses (FR-304 safe).

Citations are child rows of an immutable response; insert-only, never updated."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from uuid import uuid4

from ema_poc.adapters.base import Citation


@dataclass
class CitationRow:
    citation_id: str
    response_id: str
    title: str
    url: str
    snippet: str | None
    created_at: str


def save_citations(
    conn: sqlite3.Connection,
    *,
    response_id: str,
    citations: list[Citation],
    now: str,
    id_factory=lambda: uuid4().hex,
    commit: bool = True,
) -> None:
    """Insert one row per citation. No-op for an empty list."""
    if not citations:
        return
    for c in citations:
        conn.execute(
            """INSERT INTO response_citations
               (citation_id, response_id, title, url, snippet, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (id_factory(), response_id, c.title, c.url, c.snippet, now),
        )
    if commit:
        conn.commit()


def list_citations(conn: sqlite3.Connection, response_id: str) -> list[CitationRow]:
    rows = conn.execute(
        """SELECT citation_id, response_id, title, url, snippet, created_at
           FROM response_citations WHERE response_id = ? ORDER BY created_at, citation_id""",
        (response_id,),
    ).fetchall()
    return [CitationRow(**dict(r)) for r in rows]
