"""Sandbox storage for the real-time playground. Fully isolated from the
approval-gated monitoring tables (no SE-002 gate); insert-only writes plus a
single score-update per sandbox response."""

from __future__ import annotations

import json
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
    status: str = "DONE"            # legacy NULL reads as DONE
    target_count: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error_text: str | None = None


@dataclass
class QuerySummary:
    query_id: str
    timestamp_utc: str
    question_text: str
    persona: str | None
    brand_focus: str | None
    status: str
    done_count: int
    total_count: int


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
    scoring_error: str | None = None
    citations: list[Citation] = field(default_factory=list)


def create_query(
    conn, *, question_text, persona, brand_focus, now, id_factory=lambda: uuid4().hex,
    status: str = "RUNNING", target_count: int | None = None, started_at: str | None = None,
    commit: bool = True,
) -> str:
    query_id = id_factory()
    conn.execute(
        """INSERT INTO sandbox_queries
           (query_id, timestamp_utc, question_text, persona, brand_focus,
            status, target_count, started_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (query_id, now, question_text, persona, brand_focus, status, target_count, started_at),
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
    scoring_rationale, brand_mentions=None, commit: bool = True,
) -> None:
    cur = conn.execute(
        """UPDATE sandbox_responses
           SET sentiment_score = ?, competitive_position = ?, scoring_rationale = ?,
               brand_mentions = ?, scoring_error = NULL
           WHERE sandbox_response_id = ?""",
        (sentiment_score, competitive_position, scoring_rationale,
         json.dumps(brand_mentions) if brand_mentions is not None else None,
         sandbox_response_id),
    )
    if cur.rowcount == 0:
        raise ValueError(f"No sandbox_response with id={sandbox_response_id!r}")
    if commit:
        conn.commit()


def set_response_scoring_error(conn, sandbox_response_id, *, error, commit: bool = True) -> None:
    cur = conn.execute(
        "UPDATE sandbox_responses SET scoring_error = ? WHERE sandbox_response_id = ?",
        (error, sandbox_response_id))
    if cur.rowcount == 0:
        raise ValueError(f"No sandbox_response with id={sandbox_response_id!r}")
    if commit:
        conn.commit()


def list_unscored_sandbox(conn):
    """Rescore candidates: SUCCESS responses with no score yet and non-empty text,
    with their query's brand_focus. Returns sqlite Rows."""
    return conn.execute(
        """SELECT sr.sandbox_response_id, sr.answer_text, q.brand_focus
           FROM sandbox_responses sr JOIN sandbox_queries q ON sr.query_id = q.query_id
           WHERE sr.status = 'SUCCESS' AND sr.sentiment_score IS NULL
             AND TRIM(COALESCE(sr.answer_text, '')) <> ''
           ORDER BY sr.created_at, sr.sandbox_response_id""").fetchall()


def mark_query_done(conn, query_id, *, finished_at, commit: bool = True) -> None:
    cur = conn.execute("UPDATE sandbox_queries SET status='DONE', finished_at=? WHERE query_id=?",
                       (finished_at, query_id))
    if cur.rowcount == 0:
        raise ValueError(f"No sandbox_query with id={query_id!r}")
    if commit:
        conn.commit()


def mark_query_failed(conn, query_id, *, finished_at, error_text, commit: bool = True) -> None:
    cur = conn.execute("UPDATE sandbox_queries SET status='FAILED', finished_at=?, error_text=? "
                       "WHERE query_id=?", (finished_at, error_text, query_id))
    if cur.rowcount == 0:
        raise ValueError(f"No sandbox_query with id={query_id!r}")
    if commit:
        conn.commit()


def sweep_stale_running(conn, *, finished_at, commit: bool = True) -> int:
    cur = conn.execute(
        "UPDATE sandbox_queries SET status='FAILED', finished_at=?, "
        "error_text='interrupted by restart' WHERE status='RUNNING'", (finished_at,))
    if commit:
        conn.commit()
    return cur.rowcount


def get_query(conn, query_id) -> SandboxQuery | None:
    r = conn.execute(
        """SELECT query_id, timestamp_utc, question_text, persona, brand_focus,
                  COALESCE(status,'DONE') AS status, target_count, started_at,
                  finished_at, error_text
           FROM sandbox_queries WHERE query_id = ?""", (query_id,)).fetchone()
    return SandboxQuery(**dict(r)) if r else None


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
            scoring_error=d.get("scoring_error"),
            citations=_citations_for(conn, d["sandbox_response_id"]),
        ))
    return out


def list_recent_queries(conn, limit: int = 25) -> list[QuerySummary]:
    rows = conn.execute(
        """SELECT q.query_id, q.timestamp_utc, q.question_text, q.persona, q.brand_focus,
                  COALESCE(q.status,'DONE') AS status, q.target_count,
                  (SELECT COUNT(*) FROM sandbox_responses r WHERE r.query_id = q.query_id)
                      AS done_count
           FROM sandbox_queries q
           ORDER BY q.timestamp_utc DESC, q.query_id DESC LIMIT ?""", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        total = d["target_count"] if d["target_count"] is not None else d["done_count"]
        out.append(QuerySummary(
            query_id=d["query_id"], timestamp_utc=d["timestamp_utc"],
            question_text=d["question_text"], persona=d["persona"],
            brand_focus=d["brand_focus"], status=d["status"],
            done_count=d["done_count"], total_count=total))
    return out
