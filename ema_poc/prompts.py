"""Resolve the persona-specific system prompt for a question (FR-205).

Prompt text lives in config (settings.yaml) so Medical Affairs can review/edit
it without touching code (SE-007). Keyed by persona value, with a `default`
fallback and a hardcoded last resort."""

from __future__ import annotations

from ema_poc.config import Settings

_FALLBACK = (
    "You are responding to a user's health-related question. "
    "Answer helpfully and factually."
)


def resolve_system_prompt(persona, settings: Settings) -> str:
    key = persona.value if hasattr(persona, "value") else str(persona)
    prompts = settings.system_prompts or {}
    return prompts.get(key) or prompts.get("default") or _FALLBACK
