from openpyxl import Workbook

from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import (
    get_current,
    import_questions_csv,
    import_questions_excel,
)

NOW = "2026-06-13T00:00:00+00:00"
LATER = "2026-06-14T00:00:00+00:00"

CSV_TEXT = (
    "question_id,question_text,persona,domain,therapeutic_area,brand_focus\n"
    "Q1,Is X first-line?,Provider,Comparative,Immunology,Skyrizi\n"
    "Q2,Is X safe in pregnancy?,Patient,Safety,Immunology,\n"
)


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def test_import_csv_adds_questions(tmp_path):
    conn = _conn(tmp_path)
    path = tmp_path / "q.csv"
    path.write_text(CSV_TEXT)
    count = import_questions_csv(conn, str(path), now=NOW)
    assert count == 2
    q1 = get_current(conn, "Q1")
    assert q1.persona.value == "Provider"
    assert q1.brand_focus == "Skyrizi"
    assert get_current(conn, "Q2").brand_focus is None  # empty cell -> None
    conn.close()


def test_reimport_updates_existing_as_new_version(tmp_path):
    conn = _conn(tmp_path)
    path = tmp_path / "q.csv"
    path.write_text(CSV_TEXT)
    import_questions_csv(conn, str(path), now=NOW)

    changed = (
        "question_id,question_text,persona,domain,therapeutic_area,brand_focus\n"
        "Q1,Is X still first-line?,Provider,Comparative,Immunology,Skyrizi\n"
    )
    path.write_text(changed)
    count = import_questions_csv(conn, str(path), now=LATER)
    assert count == 1
    q1 = get_current(conn, "Q1")
    assert q1.version == 2
    assert q1.question_text == "Is X still first-line?"
    conn.close()


def test_import_excel_adds_questions(tmp_path):
    conn = _conn(tmp_path)
    wb = Workbook()
    ws = wb.active
    ws.append(
        ["question_id", "question_text", "persona", "domain",
         "therapeutic_area", "brand_focus"]
    )
    ws.append(["Q1", "Is X first-line?", "Provider", "Comparative",
               "Immunology", "Skyrizi"])
    xlsx = tmp_path / "q.xlsx"
    wb.save(xlsx)

    count = import_questions_excel(conn, str(xlsx), now=NOW)
    assert count == 1
    assert get_current(conn, "Q1").question_text == "Is X first-line?"
    conn.close()
