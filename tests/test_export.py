import csv
import json

from ema_poc.export import export_csv, export_json
from ema_poc.models import Response


def _resp(rid, text="ans", sentiment=None):
    return Response(
        response_id=rid, run_id="r1", timestamp_utc="2026-06-13T02:00:00+00:00",
        llm_name="GPT-4o", llm_model_version="m", persona="Provider",
        question_id="Q1", question_text="q", domain="Safety",
        response_text=text, response_tokens=10, finish_reason="stop",
        status="SUCCESS", sentiment_score=sentiment,
        created_at="2026-06-13T02:00:00+00:00",
    )


def test_export_csv_writes_header_and_rows(tmp_path):
    path = tmp_path / "out.csv"
    n = export_csv([_resp("a", text="first"), _resp("b", text="second")], str(path))
    assert n == 2
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["response_id"] for r in rows] == ["a", "b"]
    assert rows[0]["response_text"] == "first"
    assert rows[0]["status"] == "SUCCESS"
    assert "llm_name" in rows[0]


def test_export_json_writes_list_of_objects(tmp_path):
    path = tmp_path / "out.json"
    n = export_json([_resp("a", sentiment=-0.4)], str(path))
    assert n == 1
    data = json.loads(path.read_text())
    assert isinstance(data, list)
    assert data[0]["response_id"] == "a"
    assert data[0]["sentiment_score"] == -0.4
    assert data[0]["status"] == "SUCCESS"  # enum serialized to its value


def test_export_csv_empty_list_writes_header_only(tmp_path):
    path = tmp_path / "empty.csv"
    n = export_csv([], str(path))
    assert n == 0
    lines = path.read_text().splitlines()
    assert len(lines) == 1  # header row only
    assert "response_id" in lines[0]


def test_export_csv_quotes_commas_and_embedded_quotes(tmp_path):
    path = tmp_path / "q.csv"
    tricky = 'He said, "Drug X" is first-line.\nSecond line.'
    export_csv([_resp("a", text=tricky)], str(path))
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["response_text"] == tricky  # comma, quotes, and newline survive
