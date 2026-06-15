from types import SimpleNamespace

from ema_poc.adapters.base import Citation


class _FakeModels:
    def __init__(self, resp):
        self.resp = resp
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        return self.resp


class _FakeClient:
    def __init__(self, resp):
        self.models = _FakeModels(resp)


def _resp(text="answer", finish="STOP", chunks=None, model_version="gemini-2.5-pro",
           prompt_feedback=None):
    cand = SimpleNamespace(
        finish_reason=SimpleNamespace(name=finish),
        grounding_metadata=SimpleNamespace(grounding_chunks=chunks or []),
    )
    return SimpleNamespace(
        text=text,
        candidates=[cand],
        prompt_feedback=prompt_feedback,
        usage_metadata=SimpleNamespace(prompt_token_count=8, candidates_token_count=4),
        model_version=model_version,
    )


def _adapter(client, grounded=False, params=None):
    from ema_poc.adapters.gemini_adapter import GeminiAdapter

    return GeminiAdapter(
        name="Gemini",
        model_version="gemini-2.5-pro",
        params=params or {},
        client=client,
        grounded=grounded,
    )


# ---------------------------------------------------------------------------
# SUCCESS path
# ---------------------------------------------------------------------------

def test_success_status_and_fields():
    client = _FakeClient(_resp())
    out = _adapter(client).query("sys", "q")
    assert out.status == "SUCCESS"
    assert out.text == "answer"
    assert out.finish_reason == "stop"
    assert out.prompt_tokens == 8
    assert out.completion_tokens == 4
    assert out.actual_model == "gemini-2.5-pro"
    assert out.citations == []


def test_ungrounded_config_has_no_tools():
    client = _FakeClient(_resp())
    _adapter(client).query("sys", "q")
    cfg = client.models.kwargs["config"]
    assert not cfg.tools  # None or empty list
    assert client.models.kwargs["model"] == "gemini-2.5-pro"
    assert client.models.kwargs["contents"] == "q"


# ---------------------------------------------------------------------------
# TRUNCATED path
# ---------------------------------------------------------------------------

def test_max_tokens_gives_truncated():
    client = _FakeClient(_resp(finish="MAX_TOKENS"))
    out = _adapter(client).query("s", "q")
    assert out.status == "TRUNCATED"
    assert out.finish_reason == "length"


# ---------------------------------------------------------------------------
# BLOCKED paths
# ---------------------------------------------------------------------------

def test_safety_finish_reason_blocks():
    client = _FakeClient(_resp(text="", finish="SAFETY"))
    out = _adapter(client).query("s", "q")
    assert out.status == "BLOCKED"
    assert out.text == ""
    assert out.finish_reason == "blocked"


def test_prompt_feedback_block_reason_blocks():
    pf = SimpleNamespace(block_reason="SAFETY")
    client = _FakeClient(_resp(text="", prompt_feedback=pf))
    out = _adapter(client).query("s", "q")
    assert out.status == "BLOCKED"


# ---------------------------------------------------------------------------
# Grounded path
# ---------------------------------------------------------------------------

def test_grounded_passes_google_search_tool_and_parses_citations():
    chunk = SimpleNamespace(web=SimpleNamespace(uri="https://src/a", title="Src A"))
    client = _FakeClient(_resp(chunks=[chunk]))
    out = _adapter(client, grounded=True).query("sys", "q?")

    # The config passed to generate_content must carry a google_search tool
    cfg = client.models.kwargs["config"]
    assert cfg.tools  # non-empty

    assert [(c.title, c.url) for c in out.citations] == [("Src A", "https://src/a")]


# ---------------------------------------------------------------------------
# actual_model captured
# ---------------------------------------------------------------------------

def test_actual_model_captured():
    client = _FakeClient(_resp(model_version="gemini-2.5-pro-preview"))
    out = _adapter(client).query("s", "q")
    assert out.actual_model == "gemini-2.5-pro-preview"
