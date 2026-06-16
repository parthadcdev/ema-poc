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
# Nav entries and section containers for marketing / medical
# ---------------------------------------------------------------------------

def test_marketing_section_present(html):
    assert "data-section='marketing'" in html or 'data-section="marketing"' in html
    assert "id='view-marketing'" in html or 'id="view-marketing"' in html


def test_medical_section_present(html):
    assert "data-section='medical'" in html or 'data-section="medical"' in html
    assert "id='view-medical'" in html or 'id="view-medical"' in html


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


# ---------------------------------------------------------------------------
# Medical Affairs — JS source markers and embedded-data assertions
# ---------------------------------------------------------------------------

def _medical_dataset():
    """Dataset with a HIGH-hallucination record (with flags) and a DRIFT alert."""
    return {
        "generated_at": "2026-06-13T00:00:00Z",
        "abbvie_brands": ["Skyrizi"],
        "competitor_brands": ["Humira"],
        "records": [
            {
                "response_id": "med1",
                "timestamp_utc": "2026-06-13T10:00:00+00:00",
                "date": "2026-06-13",
                "llm_name": "GPT-4o",
                "grounded": False,
                "persona": "Provider",
                "question_id": "Q-MED-001",
                "question_text": "Does Skyrizi cure psoriasis permanently?",
                "therapeutic_area": "Immunology",
                "brand_focus": "Skyrizi",
                "domain": "Efficacy",
                "status": "SUCCESS",
                "response_text": "Skyrizi permanently eliminates psoriasis in 95% of patients.",
                "sentiment_score": 0.9,
                "competitive_position": "FIRST_LINE_RECOMMENDED",
                "confidence_level": "ASSERTIVE",
                "citation_quality": "NONE",
                "brand_mentions": ["Skyrizi"],
                "scoring_rationale": "Overstated efficacy claim without citation.",
                "hallucination_risk": "HIGH",
                "hallucination_flags": [
                    {
                        "claim": "permanently eliminates psoriasis in 95% of patients",
                        "conflicts_with": "clinical trial data showing remission, not cure",
                        "severity": "HIGH",
                    }
                ],
                "alert_reasons": ["HALLUCINATION:unsupported_claim"],
                "alert_triggered": True,
            },
            {
                "response_id": "med2",
                "timestamp_utc": "2026-06-13T11:00:00+00:00",
                "date": "2026-06-13",
                "llm_name": "Gemini-Pro",
                "grounded": False,
                "persona": "Patient",
                "question_id": "Q-MED-002",
                "question_text": "Is Skyrizi still recommended for plaque psoriasis?",
                "therapeutic_area": "Immunology",
                "brand_focus": "Skyrizi",
                "domain": "Efficacy",
                "status": "SUCCESS",
                "response_text": "Skyrizi is recommended for moderate to severe plaque psoriasis.",
                "sentiment_score": 0.5,
                "competitive_position": "FIRST_LINE_RECOMMENDED",
                "confidence_level": "HEDGED",
                "citation_quality": "MODERATE",
                "brand_mentions": ["Skyrizi"],
                "scoring_rationale": "Guideline-aligned response.",
                "hallucination_risk": "NONE",
                "hallucination_flags": [],
                "alert_reasons": ["DRIFT:sentiment_shift"],
                "alert_triggered": True,
            },
            {
                "response_id": "med3",
                "timestamp_utc": "2026-06-13T12:00:00+00:00",
                "date": "2026-06-13",
                "llm_name": "Claude-3",
                "grounded": False,
                "persona": "Prospect",
                "question_id": "Q-MED-003",
                "question_text": "What is Skyrizi dosing?",
                "therapeutic_area": "Immunology",
                "brand_focus": "Skyrizi",
                "domain": "Dosing",
                "status": "SUCCESS",
                "response_text": "Skyrizi is dosed 150mg every 12 weeks after induction.",
                "sentiment_score": 0.2,
                "competitive_position": None,
                "confidence_level": "ASSERTIVE",
                "citation_quality": "HIGH",
                "brand_mentions": ["Skyrizi"],
                "scoring_rationale": "Accurate dosing information.",
                "hallucination_risk": "NONE",
                "hallucination_flags": [],
                "alert_reasons": [],
                "alert_triggered": False,
            },
        ],
    }


@pytest.fixture()
def medical_html():
    return render_dashboard_html(_medical_dataset())


def test_medical_render_function_present(medical_html):
    """The JS source must define renderMedical."""
    assert "function renderMedical" in medical_html


def test_medical_hallucination_flags_reference(medical_html):
    """The JS source must reference hallucination_flags."""
    assert "hallucination_flags" in medical_html


def test_medical_hallucination_risk_reference(medical_html):
    """The JS source must reference hallucination_risk."""
    assert "hallucination_risk" in medical_html


def test_medical_conflicts_with_reference(medical_html):
    """The JS source must reference conflicts_with for flagged claims."""
    assert "conflicts_with" in medical_html


def test_medical_review_queue_marker(medical_html):
    """The JS source must include a 'review' queue marker."""
    assert "review" in medical_html.lower()


def test_medical_drift_badge_logic(medical_html):
    """The JS source must include DRIFT badge logic."""
    assert "DRIFT" in medical_html


def test_medical_high_hallucination_in_embedded_json(medical_html):
    """The HIGH-hallucination record appears in the embedded JSON."""
    parsed = _extract_embedded_json(medical_html)
    high_risk = [r for r in parsed["records"] if r.get("hallucination_risk") == "HIGH"]
    assert len(high_risk) == 1
    assert high_risk[0]["question_id"] == "Q-MED-001"


def test_medical_flagged_claim_text_in_embedded_json(medical_html):
    """The flagged claim text appears in the embedded JSON dataset."""
    parsed = _extract_embedded_json(medical_html)
    high_risk = [r for r in parsed["records"] if r.get("hallucination_risk") == "HIGH"]
    assert len(high_risk) == 1
    flags = high_risk[0].get("hallucination_flags", [])
    assert len(flags) == 1
    assert "permanently eliminates psoriasis in 95% of patients" in flags[0]["claim"]


def test_medical_response_text_in_embedded_json(medical_html):
    """The HIGH-risk record's response_text appears in the embedded JSON."""
    assert "permanently eliminates psoriasis in 95% of patients" in medical_html


def test_medical_drift_alert_record_in_embedded_json(medical_html):
    """The DRIFT alert record appears in the embedded JSON."""
    parsed = _extract_embedded_json(medical_html)
    drift_records = [
        r for r in parsed["records"]
        if any(a.startswith("DRIFT:") for a in (r.get("alert_reasons") or []))
    ]
    assert len(drift_records) == 1
    assert drift_records[0]["question_id"] == "Q-MED-002"


def test_medical_self_contained(medical_html):
    """The medical dataset page must still pass the self-contained rule."""
    assert "<script src" not in medical_html
    assert "<link " not in medical_html
    stripped = _strip_allowed_content(medical_html)
    assert "http://" not in stripped
    assert "https://" not in stripped


# ---------------------------------------------------------------------------
# Shared app-nav bar (Playground / Dashboard tabs)
# ---------------------------------------------------------------------------

def test_render_has_appbar(html):
    """The shared app-nav bar is present on the dashboard."""
    assert 'class="appbar"' in html
    assert "Evidence Monitoring Agent" in html


def test_render_dashboard_tab_active(html):
    """The Dashboard tab is the active view; both tab hrefs are present."""
    assert 'href="/dashboard" class="apptab active">Dashboard' in html
    # Playground tab present and not active
    assert '<a href="/" class="apptab">Playground' in html


def test_render_playground_tab_honors_playground_url():
    """The Playground tab points to playground_url when provided."""
    result = render_dashboard_html(_dataset(), playground_url="/")
    assert '<a href="/" class="apptab">Playground' in result
    # Dashboard tab remains the active view
    assert 'class="apptab active">Dashboard' in result


def test_render_playground_tab_defaults_to_root():
    """Without playground_url, the Playground tab defaults to '/'."""
    result = render_dashboard_html(_dataset())
    assert '<a href="/" class="apptab">Playground' in result


# ---------------------------------------------------------------------------
# Markdown rendering (renderMarkdown) — JS source markers + escape-first guard
# ---------------------------------------------------------------------------

def test_markdown_render_function_present(html):
    """The JS source must define renderMarkdown."""
    assert "function renderMarkdown" in html


def test_markdown_render_function_called(html):
    """renderMarkdown must be invoked at least once when building detail panels."""
    assert "renderMarkdown(" in html


def test_markdown_escape_first_guard(html):
    """Structural guard: renderMarkdown escapes the whole src before parsing."""
    assert "mdEsc(src)" in html


def test_dashboard_has_source_filter(html):
    assert "id='f-source'" in html
    assert ">Monitoring<" in html and ">Realtime<" in html
    assert "r.source" in html                  # filter predicate references source


def test_dashboard_source_badge_in_responses(html):
    # The detail-grid provenance label, not the filter-bar <label>Source<select...
    assert "class='dl'>Source</div>" in html


def test_dashboard_has_search_input(html):
    assert "id='f-search'" in html
    assert "type='search'" in html


def test_dashboard_search_helper_and_predicate(html):
    assert "function _searchable" in html          # concatenates the text fields
    assert "_searchable(" in html                  # used in the filter predicate
    assert "f-search" in html                      # read in applyFilters


def test_dashboard_search_in_reset(html):
    assert "getElementById('f-search').value" in html


def test_dashboard_search_clear_event_wired(html):
    # native search ✕ fires a 'search' event; ensure it's wired to re-render
    assert "addEventListener('search', render)" in html


def test_dashboard_has_result_count(html):
    assert "id='f-count'" in html
    assert "Showing " in html                      # render() sets "Showing N of M"
    assert "DATA.records.length" in html           # the M in N of M


def test_brand_dropdown_includes_configured_brands(html):
    # The Brand filter must list configured brands (e.g. newly-added ones like the
    # Lupron franchises), not only brands that happen to appear in the data.
    assert "function brandOptions" in html
    assert "brandOptions()" in html
    # the union pulls from the embedded configured brand lists
    assert "DATA.abbvie_brands" in html and "DATA.competitor_brands" in html


def test_responses_sorted_newest_first(html):
    # renderResponses must sort rows by timestamp DESCENDING so recent runs (incl.
    # realtime, which collect_dataset appends last) surface at the top of the table
    # instead of being buried at the bottom.
    import re
    m = re.search(r"function renderResponses\(rows\)\{(.*?)\n\}", html, re.S)
    assert m, "renderResponses not found"
    body = m.group(1)
    assert ".sort(" in body, "renderResponses does not sort its rows"
    # descending: compares b before a on the timestamp
    assert "b.timestamp_utc" in body and "a.timestamp_utc" in body


def test_responses_detail_shows_scoring_error(html):
    assert "scoring_error" in html
    assert "Scoring failed" in html
