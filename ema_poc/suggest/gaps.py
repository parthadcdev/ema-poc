"""Coverage + effectiveness gap analysis for question generation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ema_poc.coverage import question_effectiveness
from ema_poc.repositories.questions import active_approved

PERSONAS = ["Prospect", "Provider", "Patient"]
DOMAINS = ["Efficacy", "Safety", "Comparative", "Access", "General"]


@dataclass
class Cell:
    brand: str
    persona: str
    domain: str
    count: int


@dataclass
class GapReport:
    under_covered: list = field(default_factory=list)   # list[Cell] with count == 0
    low_value: list = field(default_factory=list)        # list[dict]


def analyze_gaps(conn, *, abbvie_brands) -> GapReport:
    questions = active_approved(conn)
    counts = Counter(
        (q.brand_focus, q.persona.value, q.domain.value) for q in questions
    )
    under = []
    for brand in abbvie_brands:
        for persona in PERSONAS:
            for domain in DOMAINS:
                c = counts.get((brand, persona, domain), 0)
                if c == 0:
                    under.append(Cell(brand=brand, persona=persona, domain=domain, count=0))
    low_value = [
        {
            "question_id": q.question_id,
            "brand_focus": q.brand_focus,
            "question_text": q.question_text,
            "not_mentioned_rate": q.not_mentioned_rate,
        }
        for q in question_effectiveness(conn)
        if q.low_value
    ]
    return GapReport(under_covered=under, low_value=low_value)
