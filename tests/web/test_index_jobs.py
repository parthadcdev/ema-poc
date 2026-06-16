from pathlib import Path

HTML = Path("ema_poc/web/static/index.html").read_text()


def test_index_uses_submit_and_poll_not_sse():
    assert "EventSource" not in HTML            # SSE removed
    assert "/api/ask" in HTML                   # POST submit
    assert "/api/queries" in HTML               # poll + history list


def test_index_has_recent_questions_panel():
    assert 'id="recent-list"' in HTML           # history container


def test_index_keeps_markdown_and_xss_helpers():
    assert "function renderMarkdown" in HTML
    assert "function esc" in HTML and "function safeUrl" in HTML


def test_index_is_self_contained():
    # no external resource references (allow the SVG xmlns only)
    for marker in ["http://", "https://"]:
        for line in HTML.splitlines():
            if marker in line:
                assert "www.w3.org/2000/svg" in line, f"external resource: {line.strip()}"


def test_index_renders_scoring_error():
    from pathlib import Path
    html = Path("ema_poc/web/static/index.html").read_text()
    assert "scoring_error" in html
    assert "Scoring failed" in html
