from types import SimpleNamespace

from ema_poc.adapters.claude_adapter import ClaudeTargetAdapter


class _Block:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class _Usage:
    def __init__(self, i, o):
        self.input_tokens = i
        self.output_tokens = o


class _Message:
    def __init__(self, content, stop_reason, i=12, o=8):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _Usage(i, o)


class _FakeAnthropic:
    """Mimics client.messages.create(...)."""

    def __init__(self, message):
        self._message = message
        self.kwargs = None
        self.messages = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self._message


def _adapter(message, fake=None):
    client = fake or _FakeAnthropic(message)
    return ClaudeTargetAdapter(
        name="Claude-Opus-4.8",
        model_version="claude-opus-4-8",
        params={"max_tokens": 1024},
        client=client,
    )


def test_success_joins_text_blocks_and_maps_tokens():
    msg = _Message(
        [_Block("thinking", "..."), _Block("text", "First-line "), _Block("text", "use.")],
        "end_turn",
    )
    r = _adapter(msg).query("You are a patient.", "Is drug X first-line?")
    assert r.status == "SUCCESS"
    assert r.finish_reason == "stop"
    assert r.text == "First-line use."  # only text blocks, thinking excluded
    assert r.prompt_tokens == 12
    assert r.completion_tokens == 8


def test_request_uses_adaptive_thinking_and_no_temperature():
    fake = _FakeAnthropic(_Message([_Block("text", "ok")], "end_turn"))
    _adapter(None, fake=fake).query("SYS", "Q")
    assert fake.kwargs["model"] == "claude-opus-4-8"
    assert fake.kwargs["max_tokens"] == 1024
    assert fake.kwargs["thinking"] == {"type": "adaptive"}
    assert fake.kwargs["system"] == "SYS"
    assert fake.kwargs["messages"] == [{"role": "user", "content": "Q"}]
    assert "temperature" not in fake.kwargs  # Opus 4.8 rejects temperature
    assert "top_p" not in fake.kwargs
    assert "budget_tokens" not in fake.kwargs


def test_max_tokens_stop_reason_is_truncated():
    r = _adapter(_Message([_Block("text", "partial")], "max_tokens")).query("s", "q")
    assert r.status == "TRUNCATED"
    assert r.finish_reason == "length"


def test_refusal_stop_reason_is_blocked():
    r = _adapter(_Message([], "refusal")).query("s", "q")
    assert r.status == "BLOCKED"
    assert r.finish_reason == "blocked"
    assert r.text == ""


def _grounded_claude_resp():
    cite = SimpleNamespace(url="https://src/c", title="Claude Source", cited_text="snippet text")
    text_block = SimpleNamespace(type="text", text="Grounded claude answer.", citations=[cite])
    return SimpleNamespace(
        content=[text_block],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=12, output_tokens=6),
    )


def test_claude_grounded_declares_web_search_tool_and_parses_citations():
    captured = {}

    class _Msgs:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _grounded_claude_resp()

    class _Client:
        messages = _Msgs()

    adapter = ClaudeTargetAdapter(
        name="Claude-Opus-4.8-Grounded", model_version="claude-opus-4-8",
        params={"max_tokens": 4096}, client=_Client(), grounded=True,
    )
    out = adapter.query("sys", "q?")
    tools = captured.get("tools") or []
    assert len(tools) == 1
    assert tools[0]["type"] == "web_search_20250305"
    assert tools[0]["name"] == "web_search"
    assert tools[0]["max_uses"] == 5
    assert out.status == "SUCCESS"
    assert out.text == "Grounded claude answer."
    assert [(c.title, c.url, c.snippet) for c in out.citations] == [
        ("Claude Source", "https://src/c", "snippet text")
    ]


def test_ungrounded_adapter_returns_empty_citations():
    msg = _Message([_Block("text", "plain answer")], "end_turn")
    out = _adapter(msg).query("You are a patient.", "Is drug X first-line?")
    assert out.status == "SUCCESS"
    assert out.citations == []
