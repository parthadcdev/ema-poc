import pytest

from ema_poc.db import connect, init_schema
from ema_poc.models import ApprovalStatus, Domain, Persona
from ema_poc.repositories.questions import add_question, get_current, get_version


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def test_add_question_creates_version_1(tmp_path):
    conn = _conn(tmp_path)
    q = add_question(
        conn,
        question_id="Q1",
        question_text="Is drug X first-line?",
        persona="Provider",
        domain="Comparative",
        therapeutic_area="Immunology",
        brand_focus="Skyrizi",
        now="2026-06-13T00:00:00+00:00",
    )
    assert q.version == 1
    assert q.persona is Persona.PROVIDER
    assert q.domain is Domain.COMPARATIVE
    assert q.active is True
    assert q.approval_status is ApprovalStatus.PENDING
    assert q.therapeutic_area == "Immunology"
    conn.close()


def test_get_current_and_get_version(tmp_path):
    conn = _conn(tmp_path)
    add_question(
        conn,
        question_id="Q1",
        question_text="t",
        persona="Patient",
        domain="Safety",
        now="2026-06-13T00:00:00+00:00",
    )
    cur = get_current(conn, "Q1")
    assert cur is not None and cur.version == 1
    assert get_version(conn, "Q1", 1).question_text == "t"
    assert get_version(conn, "Q1", 2) is None
    assert get_current(conn, "Q-missing") is None
    conn.close()


def test_add_duplicate_question_id_raises(tmp_path):
    conn = _conn(tmp_path)
    add_question(
        conn,
        question_id="Q1",
        question_text="t",
        persona="Prospect",
        domain="General",
        now="2026-06-13T00:00:00+00:00",
    )
    with pytest.raises(ValueError):
        add_question(
            conn,
            question_id="Q1",
            question_text="dup",
            persona="Prospect",
            domain="General",
        )
    conn.close()
