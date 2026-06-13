from ema_poc.dashboard.data import DashboardData
from ema_poc.dashboard.render import render_dashboard_html


def _data():
    return DashboardData(
        rows=[
            {
                "response_id": "a", "llm_name": "GPT-4o", "persona": "Provider",
                "therapeutic_area": "Immunology", "brand_focus": "Skyrizi",
                "domain": "Safety", "timestamp_utc": "2026-06-13T01:00:00+00:00",
                "status": "SUCCESS", "sentiment_score": 0.8,
                "competitive_position": "FIRST_LINE_RECOMMENDED", "alert_triggered": 0,
                "response_text": "Skyrizi is <b>first-line</b>.",
                "scoring_rationale": "positive & clear",
            },
        ],
        sentiment_by_llm={"GPT-4o": 0.8}, sentiment_by_therapy={"Skyrizi": 0.8},
        position_by_llm={"GPT-4o": {"FIRST_LINE_RECOMMENDED": 1}},
        volume_by_date={"2026-06-13": 1},
        alerts=[{"response_id": "b", "llm_name": "Gemini",
                 "reason": "SENTIMENT_BELOW_THRESHOLD", "rationale": "neg"}],
        total_responses=1, total_alerts=1,
    )


def test_render_produces_self_contained_html():
    html = render_dashboard_html(_data())
    assert html.startswith("<!DOCTYPE html>")
    assert "<script src" not in html
    assert "<link" not in html
    assert "http://" not in html
    assert "https://" not in html.replace("2026-06-13T01:00:00+00:00", "")


def test_render_includes_sections_and_data():
    html = render_dashboard_html(_data())
    assert "Evidence Monitoring Dashboard" in html
    assert "Sentiment by LLM" in html
    assert "Competitive positioning by LLM" in html
    assert "Response volume over time" in html
    assert "GPT-4o" in html
    assert "FIRST_LINE_RECOMMENDED" in html
    assert "SENTIMENT_BELOW_THRESHOLD" in html
    assert "id='f-persona'" in html or 'id="f-persona"' in html
    assert "id='f-llm'" in html or 'id="f-llm"' in html


def test_render_escapes_response_content():
    html = render_dashboard_html(_data())
    assert "&lt;b&gt;first-line&lt;/b&gt;" in html
    assert "positive &amp; clear" in html
