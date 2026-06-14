"""Tests for the Claude question generator (offline, fake client)."""

from __future__ import annotations

import pytest

from ema_poc.suggest.gaps import Cell, GapReport
from ema_poc.suggest.generator import (
    GenerationResult,
    ProposedQuestion,
    _build_prompt,
    suggest_questions,
)


# ---------------------------------------------------------------------------
# Fake Anthropic client (mirrors detector/scorer pattern)
# ---------------------------------------------------------------------------


class _FakeParsed:
    def __init__(self, out: GenerationResult) -> None:
        self.parsed_output = out


class _FakeMessages:
    def __init__(self, out: GenerationResult) -> None:
        self.out = out
        self.kwargs: dict | None = None

    def parse(self, **kwargs) -> _FakeParsed:
        self.kwargs = kwargs
        return _FakeParsed(self.out)


class _FakeClient:
    def __init__(self, out: GenerationResult) -> None:
        self.messages = _FakeMessages(out)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gap_report() -> GapReport:
    return GapReport(
        under_covered=[Cell(brand="Skyrizi", persona="Patient", domain="Access", count=0)],
        low_value=[
            {
                "question_id": "q-001",
                "brand_focus": "Skyrizi",
                "question_text": "What treats psoriasis?",
                "not_mentioned_rate": 0.75,
            }
        ],
    )


@pytest.fixture()
def existing_texts() -> list[str]:
    return ["What treats psoriasis?"]


@pytest.fixture()
def sample_proposals() -> list[ProposedQuestion]:
    return [
        ProposedQuestion(
            question_text="Does Skyrizi have a patient assistance program?",
            persona="Patient",
            domain="Access",
            therapeutic_area="Dermatology",
            brand_focus="Skyrizi",
            rationale="Targets the uncovered Patient/Access cell for Skyrizi.",
        )
    ]


@pytest.fixture()
def generation_result(sample_proposals) -> GenerationResult:
    return GenerationResult(proposals=sample_proposals)


# ---------------------------------------------------------------------------
# suggest_questions: return value
# ---------------------------------------------------------------------------


class TestSuggestQuestionsReturn:
    def test_returns_generation_result(self, gap_report, existing_texts, generation_result) -> None:
        client = _FakeClient(generation_result)
        result = suggest_questions(
            client,
            gap_report=gap_report,
            abbvie_brands=["Skyrizi"],
            competitor_brands=["Dupixent"],
            existing_texts=existing_texts,
            count=1,
        )
        assert result is generation_result

    def test_returns_instance_of_generation_result(
        self, gap_report, existing_texts, generation_result
    ) -> None:
        client = _FakeClient(generation_result)
        result = suggest_questions(
            client,
            gap_report=gap_report,
            abbvie_brands=["Skyrizi"],
            competitor_brands=[],
            existing_texts=existing_texts,
            count=1,
        )
        assert isinstance(result, GenerationResult)

    def test_proposals_are_accessible(
        self, gap_report, existing_texts, generation_result, sample_proposals
    ) -> None:
        client = _FakeClient(generation_result)
        result = suggest_questions(
            client,
            gap_report=gap_report,
            abbvie_brands=["Skyrizi"],
            competitor_brands=[],
            existing_texts=existing_texts,
            count=1,
        )
        assert result.proposals == sample_proposals


# ---------------------------------------------------------------------------
# suggest_questions: parse call kwargs
# ---------------------------------------------------------------------------


class TestParseCallKwargs:
    def _call(self, gap_report, existing_texts, generation_result) -> _FakeMessages:
        client = _FakeClient(generation_result)
        suggest_questions(
            client,
            gap_report=gap_report,
            abbvie_brands=["Skyrizi"],
            competitor_brands=["Dupixent"],
            existing_texts=existing_texts,
            count=5,
        )
        return client.messages

    def test_max_tokens_is_4096(
        self, gap_report, existing_texts, generation_result
    ) -> None:
        msgs = self._call(gap_report, existing_texts, generation_result)
        assert msgs.kwargs["max_tokens"] == 4096

    def test_output_format_is_generation_result_class(
        self, gap_report, existing_texts, generation_result
    ) -> None:
        msgs = self._call(gap_report, existing_texts, generation_result)
        assert msgs.kwargs["output_format"] is GenerationResult

    def test_no_temperature_in_kwargs(
        self, gap_report, existing_texts, generation_result
    ) -> None:
        msgs = self._call(gap_report, existing_texts, generation_result)
        assert "temperature" not in msgs.kwargs

    def test_no_top_p_in_kwargs(
        self, gap_report, existing_texts, generation_result
    ) -> None:
        msgs = self._call(gap_report, existing_texts, generation_result)
        assert "top_p" not in msgs.kwargs

    def test_no_budget_tokens_in_kwargs(
        self, gap_report, existing_texts, generation_result
    ) -> None:
        msgs = self._call(gap_report, existing_texts, generation_result)
        assert "budget_tokens" not in msgs.kwargs

    def test_adaptive_thinking_set(
        self, gap_report, existing_texts, generation_result
    ) -> None:
        msgs = self._call(gap_report, existing_texts, generation_result)
        assert msgs.kwargs.get("thinking") == {"type": "adaptive"}

    def test_system_prompt_present(
        self, gap_report, existing_texts, generation_result
    ) -> None:
        msgs = self._call(gap_report, existing_texts, generation_result)
        assert "system" in msgs.kwargs
        assert len(msgs.kwargs["system"]) > 0

    def test_messages_list_has_one_user_message(
        self, gap_report, existing_texts, generation_result
    ) -> None:
        msgs = self._call(gap_report, existing_texts, generation_result)
        messages = msgs.kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_default_model_is_opus(
        self, gap_report, existing_texts, generation_result
    ) -> None:
        msgs = self._call(gap_report, existing_texts, generation_result)
        assert msgs.kwargs["model"] == "claude-opus-4-8"

    def test_custom_model_override(
        self, gap_report, existing_texts, generation_result
    ) -> None:
        client = _FakeClient(generation_result)
        suggest_questions(
            client,
            gap_report=gap_report,
            abbvie_brands=["Skyrizi"],
            competitor_brands=[],
            existing_texts=existing_texts,
            count=1,
            model="claude-sonnet-4-6",
        )
        assert client.messages.kwargs["model"] == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# _build_prompt: content checks
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    @pytest.fixture(autouse=True)
    def _prompt(self, gap_report, existing_texts) -> None:
        self.prompt = _build_prompt(
            gap_report=gap_report,
            abbvie_brands=["Skyrizi"],
            competitor_brands=["Dupixent"],
            existing_texts=existing_texts,
            count=3,
        )

    def test_contains_under_covered_cell_brand(self) -> None:
        assert "Skyrizi" in self.prompt

    def test_contains_under_covered_cell_persona(self) -> None:
        assert "Patient" in self.prompt

    def test_contains_under_covered_cell_domain(self) -> None:
        assert "Access" in self.prompt

    def test_contains_low_value_question_text(self) -> None:
        assert "What treats psoriasis?" in self.prompt

    def test_contains_existing_question_in_avoid_section(self) -> None:
        assert "What treats psoriasis?" in self.prompt

    def test_contains_count(self) -> None:
        assert "3" in self.prompt

    def test_contains_abbvie_brands(self) -> None:
        assert "Skyrizi" in self.prompt

    def test_contains_competitor_brands(self) -> None:
        assert "Dupixent" in self.prompt

    def test_contains_not_mentioned_rate(self) -> None:
        # 0.75 -> "75%"
        assert "75%" in self.prompt

    def test_contains_under_covered_header(self) -> None:
        assert "UNDER-COVERED" in self.prompt

    def test_contains_low_value_header(self) -> None:
        assert "LOW-VALUE" in self.prompt

    def test_contains_existing_avoid_header(self) -> None:
        assert "AVOID duplicating" in self.prompt

    def test_contains_pii_phi_requirement(self) -> None:
        assert "PII" in self.prompt
        assert "PHI" in self.prompt

    def test_contains_persona_options(self) -> None:
        assert "Prospect/Provider/Patient" in self.prompt

    def test_contains_domain_options(self) -> None:
        assert "Efficacy/Safety/Comparative/Access/General" in self.prompt


class TestBuildPromptEdgeCases:
    def test_empty_gap_report_shows_none_placeholder(self) -> None:
        empty_report = GapReport()
        prompt = _build_prompt(
            gap_report=empty_report,
            abbvie_brands=["Skyrizi"],
            competitor_brands=[],
            existing_texts=[],
            count=5,
        )
        # Both under_covered and low_value empty → "(none)" placeholders
        assert "(none)" in prompt

    def test_empty_existing_texts_shows_none_placeholder(self) -> None:
        report = GapReport(
            under_covered=[Cell(brand="Skyrizi", persona="Patient", domain="Access", count=0)]
        )
        prompt = _build_prompt(
            gap_report=report,
            abbvie_brands=["Skyrizi"],
            competitor_brands=[],
            existing_texts=[],
            count=1,
        )
        assert "(none)" in prompt

    def test_truncates_under_covered_to_60(self) -> None:
        # Build 70 cells; only first 60 should appear in the cells section.
        # Use a fixed abbvie_brands list that doesn't contain any Brand{i}
        # names so that "Brand60" can only appear if the truncation is wrong.
        cells = [
            Cell(brand=f"Brand{i}", persona="Patient", domain="Efficacy", count=0)
            for i in range(70)
        ]
        report = GapReport(under_covered=cells)
        prompt = _build_prompt(
            gap_report=report,
            abbvie_brands=["Skyrizi"],
            competitor_brands=[],
            existing_texts=[],
            count=5,
        )
        assert "Brand59" in prompt
        assert "Brand60" not in prompt

    def test_truncates_low_value_to_30(self) -> None:
        low_value_qs = [
            {
                "question_id": f"q-{i:03d}",
                "brand_focus": "Skyrizi",
                "question_text": f"Question {i}",
                "not_mentioned_rate": 0.8,
            }
            for i in range(35)
        ]
        report = GapReport(low_value=low_value_qs)
        prompt = _build_prompt(
            gap_report=report,
            abbvie_brands=["Skyrizi"],
            competitor_brands=[],
            existing_texts=[],
            count=5,
        )
        assert "Question 29" in prompt
        assert "Question 30" not in prompt

    def test_multiple_under_covered_cells_rendered(self) -> None:
        cells = [
            Cell(brand="Skyrizi", persona="Patient", domain="Access", count=0),
            Cell(brand="Rinvoq", persona="Provider", domain="Safety", count=0),
        ]
        report = GapReport(under_covered=cells)
        prompt = _build_prompt(
            gap_report=report,
            abbvie_brands=["Skyrizi", "Rinvoq"],
            competitor_brands=[],
            existing_texts=[],
            count=2,
        )
        assert "Skyrizi" in prompt
        assert "Rinvoq" in prompt
        assert "Provider" in prompt
        assert "Safety" in prompt


# ---------------------------------------------------------------------------
# ProposedQuestion model validation
# ---------------------------------------------------------------------------


class TestProposedQuestionModel:
    def test_valid_question_accepted(self) -> None:
        q = ProposedQuestion(
            question_text="Does Skyrizi have a copay card?",
            persona="Patient",
            domain="Access",
            therapeutic_area="Dermatology",
            brand_focus="Skyrizi",
            rationale="Fills uncovered Patient/Access cell.",
        )
        assert q.question_text == "Does Skyrizi have a copay card?"

    def test_valid_provider_persona(self) -> None:
        q = ProposedQuestion(
            question_text="What is the MOA of Skyrizi?",
            persona="Provider",
            domain="Efficacy",
            therapeutic_area="Dermatology",
            brand_focus="Skyrizi",
            rationale="Clinical precision for providers.",
        )
        assert q.persona == "Provider"

    def test_valid_prospect_persona(self) -> None:
        q = ProposedQuestion(
            question_text="Is Skyrizi covered by insurance?",
            persona="Prospect",
            domain="Access",
            therapeutic_area="Dermatology",
            brand_focus="Skyrizi",
            rationale="Access question for prospects.",
        )
        assert q.persona == "Prospect"

    def test_invalid_persona_raises(self) -> None:
        with pytest.raises(Exception):
            ProposedQuestion(
                question_text="x",
                persona="Researcher",  # type: ignore[arg-type]
                domain="Efficacy",
                therapeutic_area="Derm",
                brand_focus="Skyrizi",
                rationale="x",
            )

    def test_invalid_domain_raises(self) -> None:
        with pytest.raises(Exception):
            ProposedQuestion(
                question_text="x",
                persona="Patient",
                domain="Marketing",  # type: ignore[arg-type]
                therapeutic_area="Derm",
                brand_focus="Skyrizi",
                rationale="x",
            )

    def test_all_domain_literals_accepted(self) -> None:
        for domain in ["Efficacy", "Safety", "Comparative", "Access", "General"]:
            q = ProposedQuestion(
                question_text="x",
                persona="Patient",
                domain=domain,  # type: ignore[arg-type]
                therapeutic_area="Derm",
                brand_focus="Skyrizi",
                rationale="x",
            )
            assert q.domain == domain

    def test_all_persona_literals_accepted(self) -> None:
        for persona in ["Prospect", "Provider", "Patient"]:
            q = ProposedQuestion(
                question_text="x",
                persona=persona,  # type: ignore[arg-type]
                domain="General",
                therapeutic_area="Derm",
                brand_focus="Skyrizi",
                rationale="x",
            )
            assert q.persona == persona

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(Exception):
            ProposedQuestion(  # type: ignore[call-arg]
                question_text="x",
                persona="Patient",
                domain="Access",
                # therapeutic_area missing
                brand_focus="Skyrizi",
                rationale="x",
            )


# ---------------------------------------------------------------------------
# GenerationResult model validation
# ---------------------------------------------------------------------------


class TestGenerationResultModel:
    def test_proposals_defaults_to_empty_list(self) -> None:
        result = GenerationResult()
        assert result.proposals == []

    def test_proposals_accepts_list_of_questions(self, sample_proposals) -> None:
        result = GenerationResult(proposals=sample_proposals)
        assert len(result.proposals) == 1

    def test_proposals_contains_proposed_question_instances(self, sample_proposals) -> None:
        result = GenerationResult(proposals=sample_proposals)
        assert isinstance(result.proposals[0], ProposedQuestion)

    def test_empty_proposals_list_accepted(self) -> None:
        result = GenerationResult(proposals=[])
        assert result.proposals == []

    def test_multiple_proposals_accepted(self) -> None:
        proposals = [
            ProposedQuestion(
                question_text=f"Question {i}",
                persona="Patient",
                domain="Access",
                therapeutic_area="Derm",
                brand_focus="Skyrizi",
                rationale="x",
            )
            for i in range(5)
        ]
        result = GenerationResult(proposals=proposals)
        assert len(result.proposals) == 5
