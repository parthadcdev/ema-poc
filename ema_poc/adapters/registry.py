"""Build the enabled LLM adapters from config (NF-010).

Vendor SDKs are imported lazily inside the default factory functions, so
importing this module (and the unit tests, which inject fake factories) never
requires the SDKs to be installed."""

from __future__ import annotations

from collections.abc import Mapping

from ema_poc.adapters.base import LLMAdapter
from ema_poc.adapters.claude_adapter import ClaudeTargetAdapter
from ema_poc.adapters.gemini_adapter import GeminiAdapter
from ema_poc.adapters.openai_adapter import OpenAIAdapter
from ema_poc.config import AppConfig


def _default_openai_client(api_key: str):
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def _default_gemini_model(api_key: str, model_version: str, system_instruction=None):
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_version, system_instruction=system_instruction)


def _default_anthropic_client(api_key: str):
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


def build_adapters(
    config: AppConfig,
    env: Mapping[str, str],
    *,
    openai_client_factory=_default_openai_client,
    gemini_model_factory=_default_gemini_model,
    anthropic_client_factory=_default_anthropic_client,
) -> list[LLMAdapter]:
    adapters: list[LLMAdapter] = []
    for target in config.targets:
        if not target.enabled:
            continue
        api_key = env[target.api_key_env]
        if target.adapter == "openai":
            adapters.append(
                OpenAIAdapter(
                    name=target.name,
                    model_version=target.model_version,
                    params=target.params,
                    client=openai_client_factory(api_key),
                )
            )
        elif target.adapter == "gemini":
            adapters.append(
                GeminiAdapter(
                    name=target.name,
                    model_version=target.model_version,
                    params=target.params,
                    model_factory=lambda system_prompt, _k=api_key, _m=target.model_version: (
                        gemini_model_factory(_k, _m, system_prompt)
                    ),
                )
            )
        elif target.adapter == "claude":
            adapters.append(
                ClaudeTargetAdapter(
                    name=target.name,
                    model_version=target.model_version,
                    params=target.params,
                    client=anthropic_client_factory(api_key),
                )
            )
        else:
            raise ValueError(f"Unknown adapter type: {target.adapter!r}")
    return adapters
