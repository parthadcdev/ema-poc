"""Tests for render_dashboard_html(dataset: dict) — the new client-side dashboard."""

from __future__ import annotations

import json

import pytest

from ema_poc.dashboard.render import render_dashboard_html


# ---------------------------------------------------------------------------
# Minimal test dataset (2-3 records, one scored with an alert)
# ---------------------------------------------------------------------------

def _dataset():
    return {
        "generated_at": "2026-06-13T00:00:00Z",
        "abbvie_brands": ["Skyrizi", "Rinvoq"],
        "competitor_brands": ["Humira"],
        "records": [
            {
                "response_id": "r1",
                "timestamp_utc": "2026-06-13T10:00:00+00:00",
                "date": "2026-06-13",
                "llm_name": "GPT-4o",
                "grounded": False,
                "persona": "Provider",
                "question_id": "Q-001",
                "question_text": "Is Skyrizi first-line for plaque psoriasis?",
                "therapeutic_area": "Immunology",
                "brand_focus": "Skyrizi",
                "domain": "Efficacy",
                "status": "SUCCESS",
                "response_text": "Skyrizi is <b>first-line</b>.",
                "sentiment_score": 0.8,
                "competitive_position": "FIRST_LINE_RECOMMENDED",
                "confidence_level": "ASSERTIVE",
                "citation_quality": "HIGH",
                "brand_mentions": ["Skyrizi"],
                "scoring_rationale": "positive & clear evidence",
                "hallucination_risk": "NONE",
                "hallucination_flags": [],
                "alert_reasons": ["DRIFT:sentiment_shift"],
                "alert_triggered": True,
            },
            {
                "response_id": "r2",
                "timestamp_utc": "2026-06-14T11:00:00+00:00",
                "date": "2026-06-14",
                "llm_name": "Gemini-Pro",
                "grounded": False,
                "persona": "Patient",
                "question_id": "Q-002",
                "question_text": "What are the side effects of Rinvoq?",
                "therapeutic_area": "Rheumatology",
                "brand_focus": "Rinvoq",
                "domain": "Safety",
                "status": "SUCCESS",
                "response_text": "Rinvoq may cause infections.",
                "sentiment_score": None,
                "competitive_position": None,
                "confidence_level": None,
                "citation_quality": None,
                "brand_mentions": [],
                "scoring_rationale": None,
                "hallucination_risk": None,
                "hallucination_flags": [],
                "alert_reasons": [],
                "alert_triggered": False,
            },
            {
                "response_id": "r3",
                "timestamp_utc": "2026-06-15T12:00:00+00:00",
                "date": "2026-06-15",
                "llm_name": "Claude-3",
                "grounded": False,
                "persona": "Prospect",
                "question_id": "Q-003",
                "question_text": "Compare Skyrizi vs Humira.",
                "therapeutic_area": "Immunology",
                "brand_focus": "Skyrizi",
                "domain": "Comparative",
                "status": "SUCCESS",
                "response_text": "Skyrizi outperforms Humira.",
                "sentiment_score": 0.5,
                "competitive_position": "AMONG_OPTIONS",
                "confidence_level": "HEDGED",
                "citation_quality": "MODERATE",
                "brand_mentions": ["Skyrizi", "Humira"],
                "scoring_rationale": "comparative analysis",
                "hallucination_risk": "HIGH",
                "hallucination_flags": [],
                "alert_reasons": [],
                "alert_triggered": False,
            },
        ],
    }


@pytest.fixture()
def html():
    return render_dashboard_html(_dataset())


# ---------------------------------------------------------------------------
# Self-contained (no external resources)
# ---------------------------------------------------------------------------

def test_starts_with_doctype(html):
    assert html.startswith("<!DOCTYPE html>")


def test_no_external_scripts(html):
    assert "<script src" not in html


def test_no_external_links(html):
    assert "<link " not in html


# ---------------------------------------------------------------------------
# Required section IDs
# ---------------------------------------------------------------------------

def test_has_view_overview(html):
    assert "id='view-overview'" in html or 'id="view-overview"' in html


def test_has_view_marketing(html):
    assert "id='view-marketing'" in html or 'id="view-marketing"' in html


def test_has_view_medical(html):
    assert "id='view-medical'" in html or 'id="view-medical"' in html


def test_has_view_responses(html):
    assert "id='view-responses'" in html or 'id="view-responses"' in html


# ---------------------------------------------------------------------------
# Side-nav data-section attributes
# ---------------------------------------------------------------------------

def test_nav_overview(html):
    assert "data-section='overview'" in html or 'data-section="overview"' in html


def test_nav_marketing(html):
    assert "data-section='marketing'" in html or 'data-section="marketing"' in html


def test_nav_medical(html):
    assert "data-section='medical'" in html or 'data-section="medical"' in html


def test_nav_responses(html):
    assert "data-section='responses'" in html or 'data-section="responses"' in html


# ---------------------------------------------------------------------------
# Filter control IDs
# ---------------------------------------------------------------------------

def test_filter_ta(html):
    assert "id='f-ta'" in html or 'id="f-ta"' in html


def test_filter_brand(html):
    assert "id='f-brand'" in html or 'id="f-brand"' in html


def test_filter_llm(html):
    assert "id='f-llm'" in html or 'id="f-llm"' in html


def test_filter_persona(html):
    assert "id='f-persona'" in html or 'id="f-persona"' in html


def test_filter_from(html):
    assert "id='f-from'" in html or 'id="f-from"' in html


def test_filter_to(html):
    assert "id='f-to'" in html or 'id="f-to"' in html


# ---------------------------------------------------------------------------
# Embedded JSON data
# ---------------------------------------------------------------------------

def test_ema_data_script_tag_present(html):
    assert "id='ema-data'" in html or 'id="ema-data"' in html


def _extract_embedded_json(html: str) -> dict:
    """Extract and parse the dataset embedded in the ema-data script tag."""
    for tag in ("id='ema-data'>", 'id="ema-data">'):
        if tag in html:
            start = html.index(tag) + len(tag)
            end = html.index("</script>", start)
            raw = html[start:end]
            return json.loads(raw.replace(r"<\/", "</"))
    raise AssertionError("ema-data script tag not found")


def test_embedded_json_parses(html):
    parsed = _extract_embedded_json(html)
    assert "records" in parsed
    assert len(parsed["records"]) == 3
    assert parsed["abbvie_brands"] == ["Skyrizi", "Rinvoq"]


def test_embedded_json_has_all_record_ids(html):
    parsed = _extract_embedded_json(html)
    ids = [r["response_id"] for r in parsed["records"]]
    assert "r1" in ids
    assert "r2" in ids
    assert "r3" in ids


def test_embedded_json_question_text_present(html):
    """A record's question_text appears (in the embedded JSON)."""
    assert "Is Skyrizi first-line for plaque psoriasis?" in html


# ---------------------------------------------------------------------------
# Placeholder sections for marketing / medical (static HTML, not JS-rendered)
# ---------------------------------------------------------------------------

def test_marketing_placeholder_present(html):
    assert "Marketing Analytics" in html


def test_medical_placeholder_present(html):
    assert "Medical Affairs" in html


# ---------------------------------------------------------------------------
# Generated-at timestamp
# ---------------------------------------------------------------------------

def test_generated_at_in_html(html):
    assert "2026-06-13T00:00:00Z" in html


# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------

def test_title_present(html):
    assert "Evidence Monitoring" in html


# ---------------------------------------------------------------------------
# Dashboard title heading
# ---------------------------------------------------------------------------

def test_heading_present(html):
    assert "Evidence Monitoring Dashboard" in html


# ---------------------------------------------------------------------------
# Empty dataset edge case
# ---------------------------------------------------------------------------

def test_empty_dataset():
    empty = {
        "generated_at": "",
        "abbvie_brands": [],
        "competitor_brands": [],
        "records": [],
    }
    result = render_dashboard_html(empty)
    assert result.startswith("<!DOCTYPE html>")
    assert "id='view-overview'" in result or 'id="view-overview"' in result
    parsed = _extract_embedded_json(result)
    assert parsed["records"] == []
