"""Build all three adapters from a config via the registry (with fake vendor
clients) and run a query through each, asserting a normalized LLMResponse."""

from ema_poc.adapters.registry import build_adapters
from ema_poc.config import (
    AppConfig,
    BrandConfig,
    LLMTargetConfig,
    PricingConfig,
    RateLimitConfig,
    Settings,
)


# --- Minimal fakes for each vendor client shape ---
class _OAIMsg:
    def __init__(self, content):
        self.content = content


class _OAIChoice:
    def __init__(self, content, finish):
        self.message = _OAIMsg(content)
        self.finish_reason = finish


class _OAIUsage:
    prompt_tokens = 1
    completion_tokens = 2


class _OAICompletion:
    def __init__(self, content, finish):
        self.choices = [_OAIChoice(content, finish)]
        self.usage = _OAIUsage()


class _FakeOpenAI:
    def __init__(self):
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        return _OAICompletion("openai answer", "stop")


class _GEnum:
    def __init__(self, name):
        self.name = name


class _GUsage:
    prompt_token_count = 3
    candidates_token_count = 4


class _GCandidate:
    finish_reason = _GEnum("STOP")


class _GFeedback:
    block_reason = None


class _GResp:
    text = "gemini answer"
    candidates = [_GCandidate()]
    prompt_feedback = _GFeedback()
    usage_metadata = _GUsage()


class _FakeGeminiModels:
    def generate_content(self, **kwargs):
        return _GResp()


class _FakeGeminiClient:
    def __init__(self):
        self.models = _FakeGeminiModels()


class _CBlock:
    def __init__(self, type_, text):
        self.type = type_
        self.text = text


class _CUsage:
    input_tokens = 5
    output_tokens = 6


class _CMessage:
    content = [_CBlock("text", "claude answer")]
    stop_reason = "end_turn"
    usage = _CUsage()


class _FakeAnthropic:
    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        return _CMessage()


def _config():
    def t(name, adapter):
        return LLMTargetConfig(
            name=name, adapter=adapter, model_version="m",
            api_key_env=f"{adapter.upper()}_KEY",
            pricing=PricingConfig(input_per_1k=0.0, output_per_1k=0.0),
            rate_limit=RateLimitConfig(requests_per_minute=60, tokens_per_minute=1000),
        )

    return AppConfig(
        settings=Settings(),
        brands=BrandConfig(),
        targets=[t("GPT-4o", "openai"), t("Gemini", "gemini"), t("Claude", "claude")],
    )


def test_all_adapters_query_and_normalize():
    env = {"OPENAI_KEY": "k", "GEMINI_KEY": "k", "CLAUDE_KEY": "k"}
    adapters = build_adapters(
        _config(),
        env,
        openai_client_factory=lambda key: _FakeOpenAI(),
        gemini_client_factory=lambda key: _FakeGeminiClient(),
        anthropic_client_factory=lambda key: _FakeAnthropic(),
    )
    results = {a.name: a.query("system context", "Is drug X first-line?") for a in adapters}

    assert results["GPT-4o"].status == "SUCCESS"
    assert results["GPT-4o"].text == "openai answer"
    assert results["Gemini"].status == "SUCCESS"
    assert results["Gemini"].text == "gemini answer"
    assert results["Claude"].status == "SUCCESS"
    assert results["Claude"].text == "claude answer"
    for r in results.values():
        assert r.finish_reason in {"stop", "length", "blocked", "error"}
        assert r.prompt_tokens is not None
