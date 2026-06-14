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


def _marketing_dataset():
    """Richer dataset for Marketing Analytics tests: 2 brands, 2 LLMs, 3 dates."""
    return {
        "generated_at": "2026-06-13T00:00:00Z",
        "abbvie_brands": ["Skyrizi", "Rinvoq"],
        "competitor_brands": ["Humira", "Taltz"],
        "records": [
            {
                "response_id": "m1",
                "timestamp_utc": "2026-06-10T10:00:00+00:00",
                "date": "2026-06-10",
                "llm_name": "GPT-4o",
                "grounded": False,
                "persona": "Provider",
                "question_id": "Q-001",
                "question_text": "Is Skyrizi recommended for psoriasis?",
                "therapeutic_area": "Immunology",
                "brand_focus": "Skyrizi",
                "domain": "Efficacy",
                "status": "SUCCESS",
                "response_text": "Skyrizi is first-line.",
                "sentiment_score": 0.85,
                "competitive_position": "FIRST_LINE_RECOMMENDED",
                "confidence_level": "ASSERTIVE",
                "citation_quality": "HIGH",
                "brand_mentions": ["Skyrizi", "Humira"],
                "scoring_rationale": "strong endorsement",
                "hallucination_risk": "NONE",
                "hallucination_flags": [],
                "alert_reasons": [],
                "alert_triggered": False,
            },
            {
                "response_id": "m2",
                "timestamp_utc": "2026-06-10T11:00:00+00:00",
                "date": "2026-06-10",
                "llm_name": "Gemini-Pro",
                "grounded": False,
                "persona": "Patient",
                "question_id": "Q-002",
                "question_text": "Tell me about Skyrizi safety.",
                "therapeutic_area": "Immunology",
                "brand_focus": "Skyrizi",
                "domain": "Safety",
                "status": "SUCCESS",
                "response_text": "Skyrizi has a good safety profile.",
                "sentiment_score": 0.4,
                "competitive_position": "AMONG_OPTIONS",
                "confidence_level": "HEDGED",
                "citation_quality": "MODERATE",
                "brand_mentions": ["Skyrizi", "Taltz"],
                "scoring_rationale": "moderate endorsement",
                "hallucination_risk": "LOW",
                "hallucination_flags": [],
                "alert_reasons": [],
                "alert_triggered": False,
            },
            {
                "response_id": "m3",
                "timestamp_utc": "2026-06-11T10:00:00+00:00",
                "date": "2026-06-11",
                "llm_name": "GPT-4o",
                "grounded": False,
                "persona": "Provider",
                "question_id": "Q-003",
                "question_text": "Is Rinvoq used in RA?",
                "therapeutic_area": "Rheumatology",
                "brand_focus": "Rinvoq",
                "domain": "Efficacy",
                "status": "SUCCESS",
                "response_text": "Rinvoq is approved for RA.",
                "sentiment_score": 0.6,
                "competitive_position": "FIRST_LINE_RECOMMENDED",
                "confidence_level": "ASSERTIVE",
                "citation_quality": "HIGH",
                "brand_mentions": ["Rinvoq"],
                "scoring_rationale": "clear evidence",
                "hallucination_risk": "NONE",
                "hallucination_flags": [],
                "alert_reasons": [],
                "alert_triggered": False,
            },
            {
                "response_id": "m4",
                "timestamp_utc": "2026-06-11T11:00:00+00:00",
                "date": "2026-06-11",
                "llm_name": "Gemini-Pro",
                "grounded": False,
                "persona": "Patient",
                "question_id": "Q-004",
                "question_text": "Rinvoq vs Humira for RA?",
                "therapeutic_area": "Rheumatology",
                "brand_focus": "Rinvoq",
                "domain": "Comparative",
                "status": "SUCCESS",
                "response_text": "Rinvoq is among options.",
                "sentiment_score": -0.2,
                "competitive_position": "NOT_RECOMMENDED",
                "confidence_level": "HEDGED",
                "citation_quality": "MODERATE",
                "brand_mentions": ["Rinvoq", "Humira"],
                "scoring_rationale": "mixed signals",
                "hallucination_risk": "MEDIUM",
                "hallucination_flags": [],
                "alert_reasons": [],
                "alert_triggered": False,
            },
            {
                "response_id": "m5",
                "timestamp_utc": "2026-06-12T10:00:00+00:00",
                "date": "2026-06-12",
                "llm_name": "GPT-4o",
                "grounded": False,
                "persona": "Provider",
                "question_id": "Q-005",
                "question_text": "Latest data on Skyrizi?",
                "therapeutic_area": "Immunology",
                "brand_focus": "Skyrizi",
                "domain": "Efficacy",
                "status": "SUCCESS",
                "response_text": "Skyrizi shows excellent outcomes.",
                "sentiment_score": 0.7,
                "competitive_position": "FIRST_LINE_RECOMMENDED",
                "confidence_level": "ASSERTIVE",
                "citation_quality": "HIGH",
                "brand_mentions": ["Skyrizi"],
                "scoring_rationale": "positive data",
                "hallucination_risk": "NONE",
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


def _strip_allowed_content(h: str) -> str:
    """Remove the embedded JSON data block and permitted XML namespace literals
    so we can assert no remaining external http(s) URLs exist in the page.

    Allowed namespace literals (used inline in SVG):
      http://www.w3.org/2000/svg
      http://www.w3.org/1999/xlink
    """
    import re
    # Remove the embedded JSON data block (may contain URLs as data values)
    h = re.sub(
        r'<script[^>]*id=["\']ema-data["\'][^>]*>.*?</script>',
        '',
        h,
        flags=re.DOTALL,
    )
    # Remove allowed XML namespace literals
    h = h.replace("http://www.w3.org/2000/svg", "")
    h = h.replace("http://www.w3.org/1999/xlink", "")
    return h


def test_self_contained_no_external_urls(html):
    """After stripping the embedded JSON and SVG namespace literals, no
    external http(s) URLs should remain in the HTML source."""
    stripped = _strip_allowed_content(html)
    assert "http://" not in stripped, "Unexpected http:// URL found in page source"
    assert "https://" not in stripped, "Unexpected https:// URL found in page source"


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


# ---------------------------------------------------------------------------
# Marketing Analytics — JS source markers
# (Rendering is client-side; we verify code presence, not post-render DOM)
# ---------------------------------------------------------------------------

@pytest.fixture()
def marketing_html():
    return render_dashboard_html(_marketing_dataset())


def test_marketing_render_function_present(marketing_html):
    """The JS source must define renderMarketing."""
    assert "function renderMarketing" in marketing_html


def test_marketing_position_color_map_keys(marketing_html):
    """The position color map must include all 5 competitive-position keys."""
    for key in [
        "FIRST_LINE_RECOMMENDED",
        "AMONG_OPTIONS",
        "SECOND_LINE",
        "NOT_RECOMMENDED",
        "NOT_MENTIONED",
    ]:
        assert key in marketing_html, f"Missing position key: {key}"


def test_marketing_svg_literal_present(marketing_html):
    """The JS source must include an inline <svg string literal for the trend chart."""
    assert "<svg " in marketing_html or "'<svg " in marketing_html or '"<svg ' in marketing_html


def test_marketing_svg_namespace_present(marketing_html):
    """The SVG namespace URI must be embedded in the JS source."""
    assert "http://www.w3.org/2000/svg" in marketing_html


def test_marketing_sov_section_label(marketing_html):
    """The Share of Voice section heading must appear in the JS source."""
    assert "Share of Voice" in marketing_html


def test_marketing_heatmap_section_label(marketing_html):
    """The heatmap section heading must appear in the JS source."""
    assert "Favorability" in marketing_html or "heatmap" in marketing_html.lower()


def test_marketing_trend_section_label(marketing_html):
    """The sentiment trend section heading must appear in the JS source."""
    assert "Sentiment Trend" in marketing_html or "trend" in marketing_html.lower()


def test_marketing_self_contained(marketing_html):
    """The richer marketing dataset page must still pass the self-contained rule."""
    assert "<script src" not in marketing_html
    assert "<link " not in marketing_html
    stripped = _strip_allowed_content(marketing_html)
    assert "http://" not in stripped
    assert "https://" not in stripped


def test_marketing_svg_namespace_allowed_by_self_contained_rule(marketing_html):
    """The SVG namespace must survive the pre-strip but be gone after stripping,
    confirming it is correctly whitelisted and not treated as an external URL."""
    assert "http://www.w3.org/2000/svg" in marketing_html  # present before strip
    stripped = _strip_allowed_content(marketing_html)
    assert "http://www.w3.org/2000/svg" not in stripped     # removed by whitelist
    # and no other http remains
    assert "http://" not in stripped
