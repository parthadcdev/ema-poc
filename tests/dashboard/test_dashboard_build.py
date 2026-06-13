from ema_poc.dashboard.build import build_dashboard
from ema_poc.db import connect, init_schema
from ema_poc.models import Response
from ema_poc.repositories.responses import save_response
from ema_poc.repositories.runs import create_run

NOW = "2026-06-13T02:00:00+00:00"


def test_build_dashboard_writes_html_file(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=NOW)
    save_response(conn, Response(
        response_id="a", run_id="r1", timestamp_utc=NOW, llm_name="GPT-4o",
        llm_model_version="m", persona="Provider", question_id="Q1",
        question_text="q", brand_focus="Skyrizi", domain="Safety",
        response_text="ans", response_tokens=1, finish_reason="stop",
        status="SUCCESS", created_at=NOW,
    ))
    out = tmp_path / "dash.html"
    returned = build_dashboard(conn, str(out))
    assert returned == str(out)
    html = out.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "GPT-4o" in html
    conn.close()
