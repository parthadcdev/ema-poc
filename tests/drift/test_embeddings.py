import sqlite3
import pytest

from ema_poc.db import connect, init_schema
from ema_poc.drift.embeddings import cosine_similarity, embed_response
from ema_poc.repositories import embeddings as E


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn(tmp_path):
    """Return a fully-initialised in-memory-ish DB with one run + one response."""
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    conn.execute(
        "INSERT INTO runs (run_id, started_at) VALUES ('r1', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        """INSERT INTO responses (response_id, run_id, timestamp_utc, llm_name,
           llm_model_version, persona, question_id, question_text, domain,
           response_text, status, created_at)
           VALUES ('resp1','r1','2026-01-01T00:00:00+00:00','L','m','Provider',
           'Q1','q','General','hello world','SUCCESS','2026-01-01T00:00:00+00:00')"""
    )
    conn.commit()
    return conn


NOW = "2026-01-01T00:00:00+00:00"
MODEL = "text-embedding-3-small"


class FakeEmb:
    def embed(self, t: str) -> list[float]:
        return [float(len(t)), 1.0, 2.0]


# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------

def test_cosine_identical_vectors():
    v = [1.0, 2.0, 3.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_zero_vector():
    assert cosine_similarity([0.0, 0.0, 0.0], [1.0, 2.0, 3.0]) == pytest.approx(0.0)


def test_cosine_unequal_lengths_raises():
    with pytest.raises(ValueError, match="equal length"):
        cosine_similarity([1.0, 2.0], [1.0])


# ---------------------------------------------------------------------------
# repository: save_embedding / get_embedding / has_embedding
# ---------------------------------------------------------------------------

def test_save_and_get_embedding_roundtrip(tmp_path):
    conn = _conn(tmp_path)
    vector = [0.1, 0.2, 0.3]
    E.save_embedding(conn, response_id="resp1", model=MODEL, vector=vector, now=NOW)
    result = E.get_embedding(conn, "resp1")
    assert result == pytest.approx(vector)


def test_has_embedding_true_after_save(tmp_path):
    conn = _conn(tmp_path)
    E.save_embedding(conn, response_id="resp1", model=MODEL, vector=[1.0, 2.0], now=NOW)
    assert E.has_embedding(conn, "resp1") is True


def test_has_embedding_false_before_save(tmp_path):
    conn = _conn(tmp_path)
    assert E.has_embedding(conn, "resp1") is False


def test_get_embedding_returns_none_for_unknown(tmp_path):
    conn = _conn(tmp_path)
    assert E.get_embedding(conn, "unknown") is None


def test_fk_rejects_unknown_response_id(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        E.save_embedding(conn, response_id="nope", model=MODEL, vector=[1.0], now=NOW)


# ---------------------------------------------------------------------------
# embed_response (idempotency)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, response_id: str, response_text: str):
        self.response_id = response_id
        self.response_text = response_text


def test_embed_response_first_call_writes_and_returns_true(tmp_path):
    conn = _conn(tmp_path)
    resp = _FakeResponse("resp1", "hello world")
    client = FakeEmb()

    result = embed_response(conn, resp, client=client, model=MODEL, now=NOW)

    assert result is True
    stored = E.get_embedding(conn, "resp1")
    assert stored == pytest.approx([float(len("hello world")), 1.0, 2.0])


def test_embed_response_second_call_is_idempotent(tmp_path):
    conn = _conn(tmp_path)
    resp = _FakeResponse("resp1", "hello world")
    client = FakeEmb()

    embed_response(conn, resp, client=client, model=MODEL, now=NOW)
    first_vector = E.get_embedding(conn, "resp1")

    result = embed_response(conn, resp, client=client, model=MODEL, now=NOW)

    assert result is False
    assert E.get_embedding(conn, "resp1") == pytest.approx(first_vector)
