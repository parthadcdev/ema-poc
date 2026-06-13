"""End-to-end read surface: store a mixed set of responses across two runs,
query by filters + pagination, export to CSV/JSON, and detect a change."""

import csv
import json

from ema_poc.db import connect, init_schema
from ema_poc.export import export_csv, export_json
from ema_poc.models import Response
from ema_poc.repositories.responses import (
    count_responses,
    detect_change,
    query_responses,
    save_response,
)
from ema_poc.repositories.runs import create_run

T1 = "2026-06-13T01:00:00+00:00"
T2 = "2026-06-13T02:00:00+00:00"


def _save(conn, rid, *, run_id, llm, ts, text, sentiment=None, alert=False,
          persona="Provider", question_id="Q1"):
    save_response(conn, Response(
        response_id=rid, run_id=run_id, timestamp_utc=ts, llm_name=llm,
        llm_model_version="m", persona=persona, question_id=question_id,
        question_text="q", therapeutic_area="Immunology", brand_focus="Skyrizi",
        domain="Safety", response_text=text, response_tokens=10,
        finish_reason="stop", status="SUCCESS", sentiment_score=sentiment,
        alert_triggered=alert, created_at=ts,
    ))


def test_read_surface_end_to_end(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "run-1", started_at=T1)
    create_run(conn, "run-2", started_at=T2)

    # run-1: GPT-4o positive, Gemini negative+alert
    _save(conn, "a", run_id="run-1", llm="GPT-4o", ts=T1, text="X is first-line.", sentiment=0.6)
    _save(conn, "b", run_id="run-1", llm="Gemini", ts=T1, text="X not recommended.", sentiment=-0.5, alert=True)
    # run-2: GPT-4o changed its answer
    _save(conn, "c", run_id="run-2", llm="GPT-4o", ts=T2, text="X is second-line.", sentiment=0.1)

    # query: all, then filtered
    assert count_responses(conn) == 3
    assert [r.response_id for r in query_responses(conn, llm="GPT-4o")] == ["a", "c"]
    assert [r.response_id for r in query_responses(conn, alert_triggered=True)] == ["b"]
    assert [r.response_id for r in query_responses(conn, sentiment_max=-0.3)] == ["b"]
    # pagination
    page = query_responses(conn, limit=2, offset=0)
    assert [r.response_id for r in page] == ["a", "b"]

    # export the GPT-4o responses
    gpt = query_responses(conn, llm="GPT-4o")
    csv_path = tmp_path / "gpt.csv"
    json_path = tmp_path / "gpt.json"
    assert export_csv(gpt, str(csv_path)) == 2
    assert export_json(gpt, str(json_path)) == 2
    with open(csv_path, newline="", encoding="utf-8") as fh:
        assert [row["response_id"] for row in csv.DictReader(fh)] == ["a", "c"]
    assert [o["response_id"] for o in json.loads(json_path.read_text())] == ["a", "c"]

    # change detection: GPT-4o changed between run-1 and run-2
    change = detect_change(conn, "Q1", "GPT-4o")
    assert change.changed is True
    assert change.previous_text == "X is first-line."
    assert change.current_text == "X is second-line."
    assert "second-line" in change.diff

    conn.close()
