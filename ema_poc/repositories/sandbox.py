"""Sandbox storage for the real-time playground. Fully isolated from the
approval-gated monitoring tables (no SE-002 gate); insert-only writes plus a
single score-update per sandbox response."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from uuid import uuid4

from ema_poc.adapters.base import Citation


@dataclass
class SandboxQuery:
    query_id: str
    timestamp_utc: str
    question_text: str
    persona: str | None
    brand_focus: str | None


@dataclass
class SandboxResponse:
    sandbox_response_id: str
    query_id: str
    llm_name: str
    llm_model_version: str
    grounded: bool
    answer_text: str | None
    response_tokens: int | None
    finish_reason: str | None
    status: str
    sentiment_score: float | None
    competitive_position: str | None
    scoring_rationale: str | None
    created_at: str
    citations: list[Citation] = field(default_factory=list)


def create_query(
    conn, *, question_text, persona, brand_focus, now, id_factory=lambda: uuid4().hex,
    commit: bool = True,
) -> str:
    query_id = id_factory()
    conn.execute(
        """INSERT INTO sandbox_queries (query_id, timestamp_utc, question_text, persona, brand_focus)
           VALUES (?, ?, ?, ?, ?)""",
        (query_id, now, question_text, persona, brand_focus),
    )
    if commit:
        conn.commit()
    return query_id


def save_response(
    conn, *, query_id, llm_name, llm_model_version, grounded, answer_text,
    response_tokens, finish_reason, status, now, id_factory=lambda: uuid4().hex,
    commit: bool = True,
) -> str:
    rid = id_factory()
    conn.execute(
        """INSERT INTO sandbox_responses
           (sandbox_response_id, query_id, llm_name, llm_model_version, grounded,
            answer_text, response_tokens, finish_reason, status,
            sentiment_score, competitive_position, scoring_rationale, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)""",
        (rid, query_id, llm_name, llm_model_version, int(grounded),
         answer_text, response_tokens, finish_reason, status, now),
    )
    if commit:
        conn.commit()
    return rid


def save_response_citations(
    conn, *, sandbox_response_id, citations, now, id_factory=lambda: uuid4().hex,
    commit: bool = True,
) -> None:
    if not citations:
        return
    for c in citations:
        conn.execute(
            """INSERT INTO sandbox_citations
               (citation_id, sandbox_response_id, title, url, snippet, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (id_factory(), sandbox_response_id, c.title, c.url, c.snippet, now),
        )
    if commit:
        conn.commit()


def set_response_score(
    conn, *, sandbox_response_id, sentiment_score, competitive_position,
    scoring_rationale, commit: bool = True,
) -> None:
    cur = conn.execute(
        """UPDATE sandbox_responses
           SET sentiment_score = ?, competitive_position = ?, scoring_rationale = ?
           WHERE sandbox_response_id = ?""",
        (sentiment_score, competitive_position, scoring_rationale, sandbox_response_id),
    )
    if cur.rowcount == 0:
        raise ValueError(f"No sandbox_response with id={sandbox_response_id!r}")
    if commit:
        conn.commit()


def _citations_for(conn, sandbox_response_id) -> list[Citation]:
    rows = conn.execute(
        """SELECT title, url, snippet FROM sandbox_citations
           WHERE sandbox_response_id = ? ORDER BY created_at, citation_id""",
        (sandbox_response_id,),
    ).fetchall()
    return [Citation(title=r["title"], url=r["url"], snippet=r["snippet"]) for r in rows]


def list_query_responses(conn, query_id) -> list[SandboxResponse]:
    rows = conn.execute(
        """SELECT * FROM sandbox_responses WHERE query_id = ? ORDER BY created_at, sandbox_response_id""",
        (query_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        out.append(SandboxResponse(
            sandbox_response_id=d["sandbox_response_id"], query_id=d["query_id"],
            llm_name=d["llm_name"], llm_model_version=d["llm_model_version"],
            grounded=bool(d["grounded"]), answer_text=d["answer_text"],
            response_tokens=d["response_tokens"], finish_reason=d["finish_reason"],
            status=d["status"], sentiment_score=d["sentiment_score"],
            competitive_position=d["competitive_position"],
            scoring_rationale=d["scoring_rationale"], created_at=d["created_at"],
            citations=_citations_for(conn, d["sandbox_response_id"]),
        ))
    return out


def list_recent_queries(conn, limit: int = 25) -> list[SandboxQuery]:
    rows = conn.execute(
        """SELECT query_id, timestamp_utc, question_text, persona, brand_focus
           FROM sandbox_queries ORDER BY timestamp_utc DESC, query_id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [SandboxQuery(**dict(r)) for r in rows]
