"""Storage for per-(run, question, LLM) consensus across samples."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from uuid import uuid4


@dataclass
class ConsensusRow:
    consensus_id: str
    run_id: str
    question_id: str
    llm_name: str
    canonical_position: str | None
    agreement: float
    sentiment_mean: float | None
    sentiment_stdev: float | None
    sample_count: int
    created_at: str


def save_consensus(conn, *, consensus_id=None, run_id, question_id, llm_name,
                   canonical_position, agreement, sentiment_mean, sentiment_stdev,
                   sample_count, now, commit=True) -> str:
    cid = consensus_id or uuid4().hex
    conn.execute(
        """INSERT INTO consensus (consensus_id, run_id, question_id, llm_name,
           canonical_position, agreement, sentiment_mean, sentiment_stdev,
           sample_count, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cid, run_id, question_id, llm_name, canonical_position, agreement,
         sentiment_mean, sentiment_stdev, sample_count, now),
    )
    if commit:
        conn.commit()
    return cid


def existing_groups(conn) -> set[tuple[str, str, str]]:
    rows = conn.execute(
        "SELECT run_id, question_id, llm_name FROM consensus"
    ).fetchall()
    return {(r["run_id"], r["question_id"], r["llm_name"]) for r in rows}


def list_consensus(conn) -> list[ConsensusRow]:
    rows = conn.execute(
        """SELECT consensus_id, run_id, question_id, llm_name, canonical_position,
           agreement, sentiment_mean, sentiment_stdev, sample_count, created_at
           FROM consensus ORDER BY run_id, question_id, llm_name"""
    ).fetchall()
    return [ConsensusRow(**dict(r)) for r in rows]
