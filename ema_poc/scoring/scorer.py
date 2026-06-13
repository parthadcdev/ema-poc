"""Brand sentiment + competitive positioning scoring via Claude (FR-401–404).

Uses claude-opus-4-8 with adaptive thinking and structured output
(client.messages.parse with a Pydantic schema). NO temperature (Opus 4.8
rejects it). The Anthropic client is injected so tests use a fake."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

_SYSTEM = (
    "You are a pharmaceutical brand-monitoring analyst for AbbVie. You assess "
    "how an LLM's response represents AbbVie therapies relative to competitors. "
    "Be objective and base every score strictly on the response text provided."
)


class ScoreResult(BaseModel):
    """Structured scoring output (FR-404)."""

    sentiment_score: float = Field(ge=-1.0, le=1.0)
    competitive_position: Literal[
        "FIRST_LINE_RECOMMENDED",
        "AMONG_OPTIONS",
        "SECOND_LINE",
        "NOT_RECOMMENDED",
        "NOT_MENTIONED",
    ]
    brand_mentions: list[str]
    key_claims: list[str]
    scoring_rationale: str


def _build_prompt(
    *, response_text: str, brand_focus, abbvie_brands, competitor_brands
) -> str:
    return (
        "Analyze the following LLM response about pharmaceutical therapies.\n\n"
        f"AbbVie therapy in focus: {brand_focus or 'the AbbVie therapy'}\n"
        f"Known AbbVie brands: {', '.join(abbvie_brands) or 'none provided'}\n"
        f"Known competitor brands: {', '.join(competitor_brands) or 'none provided'}\n\n"
        f'Response to analyze:\n"""\n{response_text}\n"""\n\n'
        "Score brand sentiment toward the AbbVie therapy from -1.0 (strongly "
        "negative) to +1.0 (strongly positive). Classify the AbbVie therapy's "
        "competitive positioning. List the brand names mentioned, up to 5 key "
        "claims about the therapy, and a brief scoring rationale."
    )


def score_response(
    client,
    *,
    response_text: str,
    brand_focus,
    abbvie_brands,
    competitor_brands,
    model: str = "claude-opus-4-8",
) -> ScoreResult:
    """Score one response. `client` is an Anthropic client (or a fake exposing
    `messages.parse`)."""
    parsed = client.messages.parse(
        model=model,
        max_tokens=1024,
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": _build_prompt(
                    response_text=response_text,
                    brand_focus=brand_focus,
                    abbvie_brands=abbvie_brands,
                    competitor_brands=competitor_brands,
                ),
            }
        ],
        output_format=ScoreResult,
    )
    return parsed.parsed_output
