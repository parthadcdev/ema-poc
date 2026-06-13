from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import add_question, list_questions

NOW = "2026-06-13T00:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def _seed(conn):
    add_question(conn, question_id="Q1", question_text="a", persona="Provider",
                 domain="Comparative", therapeutic_area="Immunology",
                 brand_focus="Skyrizi", now=NOW)
    add_question(conn, question_id="Q2", question_text="b", persona="Patient",
                 domain="Safety", therapeutic_area="Immunology",
                 brand_focus="Rinvoq", now=NOW)
    add_question(conn, question_id="Q3", question_text="c", persona="Provider",
                 domain="Efficacy", therapeutic_area="Oncology",
                 brand_focus="Venclexta", now=NOW)


def test_list_all(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    ids = [q.question_id for q in list_questions(conn)]
    assert ids == ["Q1", "Q2", "Q3"]  # ordered by question_id
    conn.close()


def test_filter_by_persona_and_domain(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    providers = [q.question_id for q in list_questions(conn, persona="Provider")]
    assert providers == ["Q1", "Q3"]
    safety = [q.question_id for q in list_questions(conn, domain="Safety")]
    assert safety == ["Q2"]
    conn.close()


def test_filter_by_ta_and_brand(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    immuno = [q.question_id for q in list_questions(conn, therapeutic_area="Immunology")]
    assert immuno == ["Q1", "Q2"]
    skyrizi = [q.question_id for q in list_questions(conn, brand_focus="Skyrizi")]
    assert skyrizi == ["Q1"]
    conn.close()


def test_filter_by_active_flag(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    assert len(list_questions(conn, active=True)) == 3
    assert list_questions(conn, active=False) == []
    conn.close()
