"""Generate questions for coverage gaps and store them as PENDING proposals
(source='generated') for Medical Affairs approval (SE-002)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from ema_poc.repositories.questions import add_question, list_questions
from ema_poc.suggest.gaps import analyze_gaps
from ema_poc.suggest.generator import suggest_questions


@dataclass
class SuggestSummary:
    proposed: int
    stored: int
    skipped: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def generate_and_store(conn, *, client, config, count, model=None,
                       generator=suggest_questions, now_factory=_now_iso,
                       id_factory=lambda: uuid4().hex):
    model = model or config.settings.scoring_model
    gap_report = analyze_gaps(conn, abbvie_brands=config.brands.abbvie_brands)

    current = list_questions(conn)  # returns current version of each question
    existing_texts = [q.question_text for q in current]
    existing_norm = {_norm(t) for t in existing_texts}

    result = generator(
        client, gap_report=gap_report,
        abbvie_brands=config.brands.abbvie_brands,
        competitor_brands=config.brands.competitor_brands,
        existing_texts=existing_texts, count=count, model=model,
    )

    stored = 0
    skipped = 0
    for p in result.proposals:
        if _norm(p.question_text) in existing_norm:
            skipped += 1
            continue
        add_question(
            conn, question_id=f"GEN-{id_factory()[:8]}",
            question_text=p.question_text, persona=p.persona, domain=p.domain,
            therapeutic_area=p.therapeutic_area, brand_focus=p.brand_focus,
            source="generated", now=now_factory(),
        )
        existing_norm.add(_norm(p.question_text))
        stored += 1

    return SuggestSummary(proposed=len(result.proposals), stored=stored, skipped=skipped), result.proposals
