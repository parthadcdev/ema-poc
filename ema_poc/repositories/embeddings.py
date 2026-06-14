"""Append-only storage of response embedding vectors (one per response)."""

from __future__ import annotations

import json
import sqlite3


def save_embedding(conn: sqlite3.Connection, *, response_id: str, model: str,
                   vector: list[float], now: str, commit: bool = True) -> None:
    conn.execute(
        """INSERT INTO response_embeddings (response_id, model, vector, created_at)
           VALUES (?, ?, ?, ?)""",
        (response_id, model, json.dumps(vector), now),
    )
    if commit:
        conn.commit()


def get_embedding(conn: sqlite3.Connection, response_id: str) -> list[float] | None:
    row = conn.execute(
        "SELECT vector FROM response_embeddings WHERE response_id = ?", (response_id,)
    ).fetchone()
    return json.loads(row["vector"]) if row else None


def has_embedding(conn: sqlite3.Connection, response_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM response_embeddings WHERE response_id = ?", (response_id,)
    ).fetchone() is not None
