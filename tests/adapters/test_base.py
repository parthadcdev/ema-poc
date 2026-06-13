import pytest

from ema_poc.adapters.base import Citation, LLMAdapter, LLMResponse


def test_llm_response_defaults():
    r = LLMResponse(text="hi", finish_reason="stop", status="SUCCESS")
    assert r.prompt_tokens is None
    assert r.completion_tokens is None
    assert r.raw == {}


def test_llm_adapter_is_abstract():
    with pytest.raises(TypeError):
        LLMAdapter()  # cannot instantiate an ABC with an abstract method


def test_subclass_must_implement_query():
    class Incomplete(LLMAdapter):
        pass

    with pytest.raises(TypeError):
        Incomplete()


def test_llmresponse_defaults_to_no_citations():
    r = LLMResponse(text="hi", finish_reason="stop", status="SUCCESS")
    assert r.citations == []


def test_citation_holds_title_url_snippet():
    c = Citation(title="A Study", url="https://example.com/a", snippet="excerpt")
    assert (c.title, c.url, c.snippet) == ("A Study", "https://example.com/a", "excerpt")


def test_citation_snippet_optional():
    c = Citation(title="t", url="https://x")
    assert c.snippet is None
