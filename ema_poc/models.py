"""Pydantic domain models and enums (spec §4)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Persona(str, Enum):
    PROSPECT = "Prospect"
    PROVIDER = "Provider"
    PATIENT = "Patient"


class Domain(str, Enum):
    EFFICACY = "Efficacy"
    SAFETY = "Safety"
    ACCESS = "Access"
    COMPARATIVE = "Comparative"
    GENERAL = "General"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ResponseStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TRUNCATED = "TRUNCATED"
    BLOCKED = "BLOCKED"


class CompetitivePosition(str, Enum):
    FIRST_LINE_RECOMMENDED = "FIRST_LINE_RECOMMENDED"
    AMONG_OPTIONS = "AMONG_OPTIONS"
    SECOND_LINE = "SECOND_LINE"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"
    NOT_MENTIONED = "NOT_MENTIONED"


# NOTE: created_at/updated_at are nullable on the in-memory model but NOT NULL
# in the DB schema. The repository layer (Phase 2+) supplies ISO-8601 UTC
# timestamps at insert time. Keeping them optional here allows constructing an
# entity before persistence and injecting timestamps in tests.
class Question(BaseModel):
    question_id: str
    version: int = 1
    question_text: str
    persona: Persona
    therapeutic_area: str | None = None
    brand_focus: str | None = None
    domain: Domain
    active: bool = True
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approver_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
    delete_reason: str | None = None


class Run(BaseModel):
    run_id: str
    started_at: datetime
    ended_at: datetime | None = None
    questions_attempted: int = 0
    responses_captured: int = 0
    failure_count: int = 0
    total_tokens: int = 0
    est_cost: float = 0.0
    status: str = "RUNNING"


class Response(BaseModel):
    response_id: str
    run_id: str
    timestamp_utc: datetime
    llm_name: str
    llm_model_version: str
    persona: Persona
    question_id: str
    question_text: str
    therapeutic_area: str | None = None
    brand_focus: str | None = None
    domain: Domain
    response_text: str
    response_tokens: int | None = None
    finish_reason: str | None = None
    sample_index: int = 0
    status: ResponseStatus
    sentiment_score: float | None = None
    competitive_position: CompetitivePosition | None = None
    alert_triggered: bool = False
    created_at: datetime | None = None
    provenance: str | None = None


class Score(BaseModel):
    score_id: str
    response_id: str
    version: int = 1
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    competitive_position: CompetitivePosition
    brand_mentions: list[str] = Field(default_factory=list)
    key_claims: list[str] = Field(default_factory=list)
    scoring_rationale: str | None = None
    confidence_level: str | None = None
    citation_quality: str | None = None
    scoring_model: str
    human_override: bool = False
    override_rationale: str | None = None
    created_at: datetime | None = None


class Alert(BaseModel):
    alert_id: str
    score_id: str
    reason: str
    created_at: datetime | None = None
