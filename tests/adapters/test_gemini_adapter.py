from types import SimpleNamespace

from ema_poc.adapters.gemini_adapter import GeminiAdapter


class _Enum:
    """Mimics a google enum value with a .name attribute."""

    def __init__(self, name):
        self.name = name


class _Usage:
    def __init__(self, p, c):
        self.prompt_token_count = p
        self.candidates_token_count = c


class _Candidate:
    def __init__(self, finish_reason_name):
        self.finish_reason = _Enum(finish_reason_name)


class _Feedback:
    def __init__(self, block_reason_name):
        self.block_reason = _Enum(block_reason_name) if block_reason_name else None


class _GeminiResp:
    def __init__(self, text, finish_reason_name, block_reason_name=None, p=5, c=7):
        self.text = text
        self.candidates = [_Candidate(finish_reason_name)]
        self.prompt_feedback = _Feedback(block_reason_name)
        self.usage_metadata = _Usage(p, c)


class _FakeModel:
    def __init__(self, resp):
        self._resp = resp
        self.gen_config = None

    def generate_content(self, text, generation_config=None, **_kwargs):
        self.text = text
        self.gen_config = generation_config
        return self._resp


def _adapter(resp, capture=None):
    def factory(system_prompt):
        m = _FakeModel(resp)
        if capture is not None:
            capture["system"] = system_prompt
            capture["model"] = m
        return m

    return GeminiAdapter(
        name="Gemini-1.5-Pro",
        model_version="gemini-1.5-pro",
        params={"temperature": 0.3, "max_output_tokens": 1024},
        model_factory=factory,
    )


def test_success_response_and_tokens():
    adapter = _adapter(_GeminiResp("Drug X is second-line.", "STOP"))
    r = adapter.query("clinical context", "Is drug X first-line?")
    assert r.status == "SUCCESS"
    assert r.finish_reason == "stop"
    assert r.text == "Drug X is second-line."
    assert r.prompt_tokens == 5
    assert r.completion_tokens == 7


def test_factory_receives_system_prompt_and_config():
    capture = {}
    adapter = _adapter(_GeminiResp("ok", "STOP"), capture=capture)
    adapter.query("SYSTEM", "QUESTION")
    assert capture["system"] == "SYSTEM"
    assert capture["model"].text == "QUESTION"
    assert capture["model"].gen_config["temperature"] == 0.3
    assert capture["model"].gen_config["max_output_tokens"] == 1024


def test_safety_block_via_candidate_finish_reason():
    adapter = _adapter(_GeminiResp("", "SAFETY"))
    r = adapter.query("s", "q")
    assert r.status == "BLOCKED"
    assert r.finish_reason == "blocked"


def test_safety_block_via_prompt_feedback():
    adapter = _adapter(_GeminiResp("", "STOP", block_reason_name="SAFETY"))
    r = adapter.query("s", "q")
    assert r.status == "BLOCKED"


def test_truncated_when_max_tokens():
    adapter = _adapter(_GeminiResp("partial", "MAX_TOKENS"))
    r = adapter.query("s", "q")
    assert r.status == "TRUNCATED"
    assert r.finish_reason == "length"


def _grounded_gemini_resp():
    web = SimpleNamespace(uri="https://src/g", title="Gemini Source")
    chunk = SimpleNamespace(web=web)
    gm = SimpleNamespace(grounding_chunks=[chunk])
    cand = SimpleNamespace(finish_reason="STOP", grounding_metadata=gm)
    return SimpleNamespace(
        candidates=[cand],
        text="Grounded gemini answer.",
        prompt_feedback=None,
        usage_metadata=SimpleNamespace(prompt_token_count=8, candidates_token_count=4),
    )


def test_gemini_grounded_passes_search_tool_and_parses_citations():
    captured = {}

    class _Model:
        def generate_content(self, content, **kwargs):
            captured.update(kwargs)
            return _grounded_gemini_resp()

    adapter = GeminiAdapter(
        name="Gemini-2.5-Pro-Grounded", model_version="gemini-2.5-pro",
        params={}, model_factory=lambda sp: _Model(), grounded=True,
    )
    out = adapter.query("sys", "q?")
    assert captured.get("tools") == [{"google_search": {}}]
    assert out.status == "SUCCESS"
    assert [(c.title, c.url) for c in out.citations] == [("Gemini Source", "https://src/g")]
