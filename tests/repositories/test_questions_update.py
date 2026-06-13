import pytest

from ema_poc.db import connect, init_schema
from ema_poc.models import ApprovalStatus
from ema_poc.repositories.questions import (
    add_question,
    approve_question,
    deactivate_question,
    get_current,
    get_version,
    reject_question,
    update_question,
)

NOW = "2026-06-13T00:00:00+00:00"
LATER = "2026-06-14T00:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def _seed(conn):
    add_question(conn, question_id="Q1", question_text="original",
                 persona="Provider", domain="Comparative", now=NOW)


def test_update_creates_new_version_and_keeps_history(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    updated = update_question(conn, "Q1", question_text="edited", now=LATER)
    assert updated.version == 2
    assert updated.question_text == "edited"
    assert get_version(conn, "Q1", 1).question_text == "original"
    assert get_version(conn, "Q1", 2).created_at == get_version(conn, "Q1", 1).created_at
    conn.close()


def test_update_missing_raises(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(KeyError):
        update_question(conn, "missing", question_text="x")
    conn.close()


def test_approve_sets_status_and_approver(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    approve_question(conn, "Q1", approver_name="Dr. Reviewer", now=LATER)
    cur = get_current(conn, "Q1")
    assert cur.approval_status is ApprovalStatus.APPROVED
    assert cur.approver_name == "Dr. Reviewer"
    assert cur.version == 2
    conn.close()


def test_reject_sets_status(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    reject_question(conn, "Q1", approver_name="Dr. Reviewer", now=LATER)
    assert get_current(conn, "Q1").approval_status is ApprovalStatus.REJECTED
    conn.close()


def test_deactivate_sets_active_false(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    deactivate_question(conn, "Q1", now=LATER)
    assert get_current(conn, "Q1").active is False
    conn.close()


def test_text_edit_preserves_approval_status(tmp_path):
    conn = _conn(tmp_path)
    add_question(conn, question_id="Q1", question_text="v1", persona="Provider",
                 domain="General", now=NOW)
    approve_question(conn, "Q1", approver_name="R", now=LATER)
    # editing only the text keeps APPROVED (documented carry-forward behavior)
    update_question(conn, "Q1", question_text="v2", now=LATER)
    assert get_current(conn, "Q1").approval_status is ApprovalStatus.APPROVED
    conn.close()
