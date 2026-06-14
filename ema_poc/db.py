"""SQLite connection and schema (spec §4)."""

from __future__ import annotations

import sqlite3

# created_at/updated_at are NOT NULL: the repository layer always supplies
# ISO-8601 UTC timestamps at insert time (the models keep them optional for
# pre-persistence construction / test injection).
SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    question_id      TEXT NOT NULL,
    version          INTEGER NOT NULL DEFAULT 1,
    question_text    TEXT NOT NULL,
    persona          TEXT NOT NULL,
    therapeutic_area TEXT,
    brand_focus      TEXT,
    domain           TEXT NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1,
    approval_status  TEXT NOT NULL DEFAULT 'PENDING',
    approver_name    TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT,
    delete_reason    TEXT,
    PRIMARY KEY (question_id, version)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    started_at          TEXT NOT NULL,
    ended_at            TEXT,
    questions_attempted INTEGER NOT NULL DEFAULT 0,
    responses_captured  INTEGER NOT NULL DEFAULT 0,
    failure_count       INTEGER NOT NULL DEFAULT 0,
    total_tokens        INTEGER NOT NULL DEFAULT 0,
    est_cost            REAL NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'RUNNING'
);

CREATE TABLE IF NOT EXISTS responses (
    response_id          TEXT PRIMARY KEY,
    run_id               TEXT NOT NULL,
    timestamp_utc        TEXT NOT NULL,
    llm_name             TEXT NOT NULL,
    llm_model_version    TEXT NOT NULL,
    persona              TEXT NOT NULL,
    question_id          TEXT NOT NULL,
    question_text        TEXT NOT NULL,
    therapeutic_area     TEXT,
    brand_focus          TEXT,
    domain               TEXT NOT NULL,
    response_text        TEXT NOT NULL,
    response_tokens      INTEGER,
    finish_reason        TEXT,
    status               TEXT NOT NULL,
    sentiment_score      REAL,
    competitive_position TEXT,
    alert_triggered      INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL,
    provenance           TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_responses_run ON responses(run_id);
CREATE INDEX IF NOT EXISTS idx_responses_q_llm ON responses(question_id, llm_name);

CREATE TABLE IF NOT EXISTS scores (
    score_id             TEXT PRIMARY KEY,
    response_id          TEXT NOT NULL,
    version              INTEGER NOT NULL DEFAULT 1,
    sentiment_score      REAL NOT NULL,
    competitive_position TEXT NOT NULL,
    brand_mentions       TEXT NOT NULL,
    key_claims           TEXT NOT NULL,
    scoring_rationale    TEXT,
    confidence_level     TEXT,
    citation_quality     TEXT,
    scoring_model        TEXT NOT NULL,
    human_override       INTEGER NOT NULL DEFAULT 0,
    override_rationale   TEXT,
    created_at           TEXT NOT NULL,
    FOREIGN KEY (response_id) REFERENCES responses(response_id)
);
CREATE INDEX IF NOT EXISTS idx_scores_response ON scores(response_id);

CREATE TABLE IF NOT EXISTS response_citations (
    citation_id  TEXT PRIMARY KEY,
    response_id  TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    snippet      TEXT,
    created_at   TEXT NOT NULL,
    FOREIGN KEY (response_id) REFERENCES responses(response_id)
);
CREATE INDEX IF NOT EXISTS idx_citations_response ON response_citations(response_id);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id    TEXT PRIMARY KEY,
    score_id    TEXT NOT NULL,
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (score_id) REFERENCES scores(score_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    role        TEXT,
    question_id TEXT,
    llm_target  TEXT,
    http_status INTEGER,
    detail      TEXT
);

CREATE TABLE IF NOT EXISTS sandbox_queries (
    query_id      TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    question_text TEXT NOT NULL,
    persona       TEXT,
    brand_focus   TEXT
);

CREATE TABLE IF NOT EXISTS sandbox_responses (
    sandbox_response_id  TEXT PRIMARY KEY,
    query_id             TEXT NOT NULL,
    llm_name             TEXT NOT NULL,
    llm_model_version    TEXT NOT NULL,
    grounded             INTEGER NOT NULL DEFAULT 0,
    answer_text          TEXT,
    response_tokens      INTEGER,
    finish_reason        TEXT,
    status               TEXT NOT NULL,
    sentiment_score      REAL,
    competitive_position TEXT,
    scoring_rationale    TEXT,
    created_at           TEXT NOT NULL,
    FOREIGN KEY (query_id) REFERENCES sandbox_queries(query_id)
);
CREATE INDEX IF NOT EXISTS idx_sandbox_resp_query ON sandbox_responses(query_id);

CREATE TABLE IF NOT EXISTS sandbox_citations (
    citation_id          TEXT PRIMARY KEY,
    sandbox_response_id  TEXT NOT NULL,
    title                TEXT NOT NULL,
    url                  TEXT NOT NULL,
    snippet              TEXT,
    created_at           TEXT NOT NULL,
    FOREIGN KEY (sandbox_response_id) REFERENCES sandbox_responses(sandbox_response_id)
);
CREATE INDEX IF NOT EXISTS idx_sandbox_cit_resp ON sandbox_citations(sandbox_response_id);
"""


# (additive, nullable) columns introduced after initial release; ALTER-added
# if a pre-existing DB lacks them. All nullable / no default → safe to add.
_ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    ("responses", "provenance", "TEXT"),
    ("scores", "confidence_level", "TEXT"),
    ("scores", "citation_quality", "TEXT"),
]


def _migrate_additive_columns(conn: sqlite3.Connection) -> None:
    for table, column, coltype in _ADDITIVE_COLUMNS:
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate_additive_columns(conn)
    conn.commit()
