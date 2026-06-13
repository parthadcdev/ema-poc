from ema_poc.adapters.openai_adapter import OpenAIAdapter


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content, finish_reason):
        self.message = _Msg(content)
        self.finish_reason = finish_reason


class _Usage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c


class _Completion:
    def __init__(self, content, finish_reason, p=10, c=20):
        self.choices = [_Choice(content, finish_reason)]
        self.usage = _Usage(p, c)


class _FakeOpenAI:
    """Mimics client.chat.completions.create(...)."""

    def __init__(self, completion):
        self._completion = completion
        self.kwargs = None
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self._completion


def _adapter(completion):
    return OpenAIAdapter(
        name="GPT-4o",
        model_version="gpt-4o-2024-11-20",
        params={"temperature": 0.3, "max_tokens": 1024},
        client=_FakeOpenAI(completion),
    )


def test_success_response():
    adapter = _adapter(_Completion("Drug X is first-line.", "stop"))
    r = adapter.query("You are a clinician.", "Is drug X first-line?")
    assert r.status == "SUCCESS"
    assert r.finish_reason == "stop"
    assert r.text == "Drug X is first-line."
    assert r.prompt_tokens == 10
    assert r.completion_tokens == 20


def test_request_shape_includes_system_and_user_and_params():
    fake = _FakeOpenAI(_Completion("ok", "stop"))
    adapter = OpenAIAdapter(
        name="GPT-4o",
        model_version="gpt-4o-2024-11-20",
        params={"temperature": 0.3, "max_tokens": 1024},
        client=fake,
    )
    adapter.query("SYS", "USER")
    assert fake.kwargs["model"] == "gpt-4o-2024-11-20"
    assert fake.kwargs["temperature"] == 0.3
    assert fake.kwargs["max_tokens"] == 1024
    assert fake.kwargs["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]


def test_truncated_when_finish_reason_length():
    adapter = _adapter(_Completion("cut off mid-", "length"))
    r = adapter.query("s", "q")
    assert r.status == "TRUNCATED"
    assert r.finish_reason == "length"


def test_none_content_becomes_empty_string():
    adapter = _adapter(_Completion(None, "stop"))
    r = adapter.query("s", "q")
    assert r.text == ""


def test_content_filter_is_blocked():
    adapter = _adapter(_Completion("", "content_filter"))
    r = adapter.query("s", "q")
    assert r.status == "BLOCKED"
    assert r.finish_reason == "blocked"


def test_ungrounded_returns_no_citations():
    adapter = _adapter(_Completion("answer", "stop"))
    r = adapter.query("s", "q")
    assert r.citations == []


# ---------------------------------------------------------------------------
# Grounded (Responses API) tests
# ---------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402


class _FakeResponses:
    def __init__(self, resp):
        self._resp = resp
        self.called_with = None

    def create(self, **kwargs):
        self.called_with = kwargs
        return self._resp


class _FakeOpenAIGrounded:
    def __init__(self, resp):
        self.responses = _FakeResponses(resp)


def _grounded_resp():
    annotation = SimpleNamespace(type="url_citation", url="https://src/a", title="Source A")
    content = SimpleNamespace(type="output_text", text="Grounded answer.", annotations=[annotation])
    message = SimpleNamespace(type="message", content=[content])
    return SimpleNamespace(
        output=[message],
        output_text="Grounded answer.",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def test_openai_grounded_enables_web_search_and_parses_citations():
    fake = _FakeOpenAIGrounded(_grounded_resp())
    adapter = OpenAIAdapter(
        name="GPT-4o-Grounded", model_version="gpt-4o", params={}, client=fake, grounded=True
    )
    out = adapter.query("sys", "question?")
    tools = fake.responses.called_with["tools"]
    assert any(t.get("type", "").startswith("web_search") for t in tools)
    assert out.status == "SUCCESS"
    assert out.text == "Grounded answer."
    assert [(c.title, c.url) for c in out.citations] == [("Source A", "https://src/a")]
