"""Claude proposes new monitoring questions to fill coverage/effectiveness gaps.
Structured output; PII/PHI-free; mirrors the scorer's messages.parse pattern."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

_SYSTEM = (
    "You are a Medical Affairs content strategist for AbbVie designing questions "
    "for an AI brand-monitoring system. You propose realistic, distinct questions a "
    "prospect, provider, or patient might ask an AI assistant. Questions must contain "
    "NO personally identifiable information (PII) or protected health information (PHI), "
    "and must not duplicate existing questions."
)


class ProposedQuestion(BaseModel):
    question_text: str
    persona: Literal["Prospect", "Provider", "Patient"]
    domain: Literal["Efficacy", "Safety", "Comparative", "Access", "General"]
    therapeutic_area: str
    brand_focus: str
    rationale: str


class GenerationResult(BaseModel):
    proposals: list[ProposedQuestion] = Field(default_factory=list)


def _build_prompt(*, gap_report, abbvie_brands, competitor_brands, existing_texts, count) -> str:
    cells = "\n".join(
        f"- {c.brand} / {c.persona} / {c.domain}" for c in gap_report.under_covered[:60]
    ) or "(none)"
    low = "\n".join(
        f"- [{q['brand_focus']}] {q['question_text']} (NOT_MENTIONED {q['not_mentioned_rate']:.0%})"
        for q in gap_report.low_value[:30]
    ) or "(none)"
    existing = "\n".join(f"- {t}" for t in list(existing_texts)[:150]) or "(none)"
    return (
        f"Propose {count} new brand-monitoring questions that fill the gaps below.\n\n"
        f"AbbVie brands: {', '.join(abbvie_brands) or 'none'}\n"
        f"Competitor brands: {', '.join(competitor_brands) or 'none'}\n\n"
        "UNDER-COVERED (brand / persona / domain) cells with no questions:\n"
        f"{cells}\n\n"
        "LOW-VALUE existing questions (chronically NOT_MENTIONED — propose sharper "
        "alternatives that would surface the brand):\n"
        f"{low}\n\n"
        "EXISTING questions to AVOID duplicating:\n"
        f"{existing}\n\n"
        f"Return {count} new questions. Each must target an under-covered cell or "
        "improve on a low-value question, be tagged with persona (Prospect/Provider/"
        "Patient), domain (Efficacy/Safety/Comparative/Access/General), therapeutic_area, "
        "and brand_focus (an AbbVie brand), include a one-line rationale, and contain NO "
        "PII/PHI. Make provider questions clinically precise and patient questions plain-language."
    )


def suggest_questions(client, *, gap_report, abbvie_brands, competitor_brands,
                      existing_texts, count, model="claude-opus-4-8") -> GenerationResult:
    parsed = client.messages.parse(
        model=model,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        messages=[{"role": "user", "content": _build_prompt(
            gap_report=gap_report, abbvie_brands=abbvie_brands,
            competitor_brands=competitor_brands, existing_texts=existing_texts,
            count=count)}],
        output_format=GenerationResult,
    )
    return parsed.parsed_output
