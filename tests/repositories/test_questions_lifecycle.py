from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import (
    active_approved,
    add_question,
    approve_question,
    deactivate_question,
    get_current,
    history,
    list_questions,
    soft_delete_question,
)

NOW = "2026-06-13T00:00:00+00:00"
LATER = "2026-06-14T00:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def test_soft_delete_marks_tombstone_and_hides_from_list(tmp_path):
    conn = _conn(tmp_path)
    add_question(conn, question_id="Q1", question_text="t", persona="Provider",
                 domain="General", now=NOW)
    soft_delete_question(conn, "Q1", reason="duplicate", now=LATER)
    cur = get_current(conn, "Q1")
    assert cur.deleted_at is not None
    assert cur.delete_reason == "duplicate"
    assert cur.active is False
    assert list_questions(conn) == []
    assert [q.question_id for q in list_questions(conn, include_deleted=True)] == ["Q1"]
    conn.close()


def test_history_returns_all_versions(tmp_path):
    conn = _conn(tmp_path)
    add_question(conn, question_id="Q1", question_text="v1", persona="Provider",
                 domain="General", now=NOW)
    approve_question(conn, "Q1", approver_name="R", now=LATER)
    versions = history(conn, "Q1")
    assert [h.version for h in versions] == [1, 2]
    assert versions[0].question_text == "v1"
    conn.close()


def test_active_approved_view(tmp_path):
    conn = _conn(tmp_path)
    add_question(conn, question_id="Q1", question_text="a", persona="Provider",
                 domain="General", now=NOW)
    approve_question(conn, "Q1", approver_name="R", now=LATER)
    add_question(conn, question_id="Q2", question_text="b", persona="Provider",
                 domain="General", now=NOW)
    approve_question(conn, "Q2", approver_name="R", now=LATER)
    deactivate_question(conn, "Q2", now=LATER)
    add_question(conn, question_id="Q3", question_text="c", persona="Provider",
                 domain="General", now=NOW)
    add_question(conn, question_id="Q4", question_text="d", persona="Provider",
                 domain="General", now=NOW)
    approve_question(conn, "Q4", approver_name="R", now=LATER)
    soft_delete_question(conn, "Q4", reason="x", now=LATER)

    assert [q.question_id for q in active_approved(conn)] == ["Q1"]
    conn.close()
