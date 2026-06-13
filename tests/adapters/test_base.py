import pytest

from ema_poc.adapters.base import LLMAdapter, LLMResponse


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
