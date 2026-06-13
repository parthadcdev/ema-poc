"""Full question lifecycle: import -> approve -> filter -> edit -> deactivate,
verifying the active_approved view and version history end to end."""

from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import (
    active_approved,
    approve_question,
    deactivate_question,
    history,
    import_questions_csv,
    list_questions,
    update_question,
)

NOW = "2026-06-13T00:00:00+00:00"
T2 = "2026-06-14T00:00:00+00:00"
T3 = "2026-06-15T00:00:00+00:00"

CSV_TEXT = (
    "question_id,question_text,persona,domain,therapeutic_area,brand_focus\n"
    "Q1,first,Provider,Comparative,Immunology,Skyrizi\n"
    "Q2,second,Patient,Safety,Immunology,Rinvoq\n"
    "Q3,third,Provider,Efficacy,Oncology,Venclexta\n"
)


def test_question_lifecycle_end_to_end(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    path = tmp_path / "q.csv"
    path.write_text(CSV_TEXT)

    # 1. Import a 3-question bank
    assert import_questions_csv(conn, str(path), now=NOW) == 3
    assert len(list_questions(conn)) == 3
    assert active_approved(conn) == []  # nothing approved yet

    # 2. Medical Affairs approves Q1 and Q2 (SE-002 / BR-009)
    approve_question(conn, "Q1", approver_name="Dr. A", now=T2)
    approve_question(conn, "Q2", approver_name="Dr. A", now=T2)
    assert [q.question_id for q in active_approved(conn)] == ["Q1", "Q2"]

    # 3. Filter the bank by persona
    providers = [q.question_id for q in list_questions(conn, persona="Provider")]
    assert providers == ["Q1", "Q3"]

    # 4. Edit Q1 text (new version) and confirm history + still approved/active
    update_question(conn, "Q1", question_text="first (revised)", now=T3)
    assert [h.version for h in history(conn, "Q1")] == [1, 2, 3]
    assert [q.question_id for q in active_approved(conn)] == ["Q1", "Q2"]

    # 5. Deactivate Q2 -> drops out of the runner's view
    deactivate_question(conn, "Q2", now=T3)
    assert [q.question_id for q in active_approved(conn)] == ["Q1"]

    conn.close()
