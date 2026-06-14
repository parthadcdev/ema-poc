"""Tests for ema_poc.suggest.pipeline — generate_and_store."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from ema_poc.db import init_schema
from ema_poc.models import ApprovalStatus
from ema_poc.repositories.questions import (
    add_question,
    approve_question,
    get_current,
    list_questions,
)
from ema_poc.suggest.generator import GenerationResult, ProposedQuestion
from ema_poc.suggest.pipeline import SuggestSummary, generate_and_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


def _make_config(scoring_model: str = "test-model"):
    return SimpleNamespace(
        settings=SimpleNamespace(scoring_model=scoring_model),
        brands=SimpleNamespace(
            abbvie_brands=["Skyrizi", "Rinvoq"],
            competitor_brands=["Humira"],
        ),
    )


def _make_proposals(*texts: str) -> list[ProposedQuestion]:
    return [
        ProposedQuestion(
            question_text=text,
            persona="Provider",
            domain="Efficacy",
            therapeutic_area="Dermatology",
            brand_focus="Skyrizi",
            rationale=f"Rationale for: {text}",
        )
        for text in texts
    ]


def _seed_approved_question(conn, *, question_id: str, question_text: str) -> None:
    add_question(
        conn,
        question_id=question_id,
        question_text=question_text,
        persona="Provider",
        domain="Efficacy",
        brand_focus="Skyrizi",
        source="manual",
    )
    approve_question(conn, question_id, "test-approver")


def _deterministic_id_factory(prefix: str = "abcd1234"):
    """Returns a factory that produces unique hex-like IDs per call.
    Each call returns a string where the first 8 chars (used by pipeline as [:8])
    are unique: prefix + zero-padded counter ensures uniqueness.
    The prefix itself must be < 8 chars so the counter digits land within [:8].
    We use a 4-char prefix + 4-digit counter = 8 unique chars per call.
    """
    # Truncate prefix to 4 chars to leave room for 4-digit counter within [:8]
    pfx = (prefix + "0000")[:4]
    counter = [0]

    def factory():
        val = f"{pfx}{counter[0]:04d}ffffffff"  # total > 8 chars; [:8] = pfx+counter
        counter[0] += 1
        return val

    return factory


# ---------------------------------------------------------------------------
# Main scenario: 3 proposals, 1 duplicate, 2 stored
# ---------------------------------------------------------------------------

class TestGenerateAndStore:
    def test_summary_counts_with_one_duplicate(self):
        """3 proposals, 1 duplicates an existing question → proposed=3, stored=2, skipped=1."""
        conn = _make_conn()
        _seed_approved_question(conn, question_id="Q-EXIST", question_text="Existing question text?")

        calls = {}

        def fake_gen(client, *, gap_report, abbvie_brands, competitor_brands,
                     existing_texts, count, model):
            calls["gap_report"] = gap_report
            calls["existing_texts"] = existing_texts
            return GenerationResult(proposals=_make_proposals(
                "Existing question text?",   # duplicate
                "New question about efficacy?",
                "Another new question about safety?",
            ))

        cfg = _make_config()
        summary, proposals = generate_and_store(
            conn,
            client=object(),
            config=cfg,
            count=3,
            generator=fake_gen,
            id_factory=_deterministic_id_factory("aabbccdd"),
        )

        assert summary == SuggestSummary(proposed=3, stored=2, skipped=1)
        assert len(proposals) == 3

    def test_stored_questions_are_pending(self):
        """The 2 stored questions must have approval_status == PENDING."""
        conn = _make_conn()
        _seed_approved_question(conn, question_id="Q-EXIST", question_text="Existing question text?")

        def fake_gen(client, *, gap_report, abbvie_brands, competitor_brands,
                     existing_texts, count, model):
            return GenerationResult(proposals=_make_proposals(
                "Existing question text?",
                "New question about efficacy?",
                "Another new question about safety?",
            ))

        cfg = _make_config()
        generate_and_store(
            conn,
            client=object(),
            config=cfg,
            count=3,
            generator=fake_gen,
            id_factory=_deterministic_id_factory("xxyyzz00"),
        )

        generated = list_questions(conn, approval_status="PENDING")
        # Filter to source='generated'
        gen_questions = [q for q in generated if q.source == "generated"]
        assert len(gen_questions) == 2
        assert all(q.approval_status == ApprovalStatus.PENDING for q in gen_questions)

    def test_stored_questions_have_gen_prefix_ids(self):
        """Stored questions must have IDs starting with 'GEN-'."""
        conn = _make_conn()
        _seed_approved_question(conn, question_id="Q-EXIST", question_text="Existing question text?")

        def fake_gen(client, *, gap_report, abbvie_brands, competitor_brands,
                     existing_texts, count, model):
            return GenerationResult(proposals=_make_proposals(
                "Existing question text?",
                "New question about efficacy?",
                "Another new question about safety?",
            ))

        cfg = _make_config()
        generate_and_store(
            conn,
            client=object(),
            config=cfg,
            count=3,
            generator=fake_gen,
            id_factory=_deterministic_id_factory(),
        )

        all_q = list_questions(conn)
        gen_qs = [q for q in all_q if q.source == "generated"]
        assert len(gen_qs) == 2
        assert all(q.question_id.startswith("GEN-") for q in gen_qs)

    def test_stored_questions_have_generated_source(self):
        """Stored questions must have source == 'generated'."""
        conn = _make_conn()

        def fake_gen(client, *, gap_report, abbvie_brands, competitor_brands,
                     existing_texts, count, model):
            return GenerationResult(proposals=_make_proposals(
                "Brand new question one?",
                "Brand new question two?",
            ))

        cfg = _make_config()
        generate_and_store(
            conn,
            client=object(),
            config=cfg,
            count=2,
            generator=fake_gen,
            id_factory=_deterministic_id_factory("src00000"),
        )

        all_q = list_questions(conn)
        assert all(q.source == "generated" for q in all_q)

    def test_duplicate_was_not_stored(self):
        """The duplicate question text should not appear as a generated question."""
        conn = _make_conn()
        existing_text = "Existing question text?"
        _seed_approved_question(conn, question_id="Q-EXIST", question_text=existing_text)

        def fake_gen(client, *, gap_report, abbvie_brands, competitor_brands,
                     existing_texts, count, model):
            return GenerationResult(proposals=_make_proposals(
                existing_text,
                "New question about efficacy?",
                "Another new question about safety?",
            ))

        cfg = _make_config()
        generate_and_store(
            conn,
            client=object(),
            config=cfg,
            count=3,
            generator=fake_gen,
            id_factory=_deterministic_id_factory("dup00000"),
        )

        all_q = list_questions(conn)
        gen_qs = [q for q in all_q if q.source == "generated"]
        gen_texts = [q.question_text for q in gen_qs]
        assert existing_text not in gen_texts

    def test_generator_called_with_non_none_gap_report(self):
        """The fake generator must receive a non-None gap_report."""
        conn = _make_conn()
        captured = {}

        def fake_gen(client, *, gap_report, abbvie_brands, competitor_brands,
                     existing_texts, count, model):
            captured["gap_report"] = gap_report
            captured["existing_texts"] = existing_texts
            return GenerationResult(proposals=[])

        cfg = _make_config()
        generate_and_store(
            conn,
            client=object(),
            config=cfg,
            count=0,
            generator=fake_gen,
        )

        assert captured["gap_report"] is not None
        assert "existing_texts" in captured


# ---------------------------------------------------------------------------
# Intra-batch duplicate test
# ---------------------------------------------------------------------------

class TestIntraBatchDuplicate:
    def test_intra_batch_duplicate_only_stored_once(self):
        """Two proposals with the same text → only one stored, one skipped."""
        conn = _make_conn()
        repeated_text = "What is the efficacy of Skyrizi for psoriasis?"

        def fake_gen(client, *, gap_report, abbvie_brands, competitor_brands,
                     existing_texts, count, model):
            return GenerationResult(proposals=_make_proposals(
                repeated_text,
                repeated_text,   # intra-batch duplicate
            ))

        cfg = _make_config()
        summary, proposals = generate_and_store(
            conn,
            client=object(),
            config=cfg,
            count=2,
            generator=fake_gen,
            id_factory=_deterministic_id_factory("intra000"),
        )

        assert summary.proposed == 2
        assert summary.stored == 1
        assert summary.skipped == 1

        all_q = list_questions(conn)
        gen_qs = [q for q in all_q if q.source == "generated"]
        assert len(gen_qs) == 1

    def test_intra_batch_and_existing_duplicate(self):
        """Mix: 1 existing dup + 2 intra-batch dups (same text) + 1 unique → stored=1, skipped=3."""
        conn = _make_conn()
        existing_text = "Already exists question?"
        repeated_text = "Same batch question?"
        _seed_approved_question(conn, question_id="Q-SEED", question_text=existing_text)

        def fake_gen(client, *, gap_report, abbvie_brands, competitor_brands,
                     existing_texts, count, model):
            return GenerationResult(proposals=_make_proposals(
                existing_text,   # dup vs existing
                repeated_text,   # intra-batch first occurrence
                repeated_text,   # intra-batch dup
                "Unique new question?",
            ))

        cfg = _make_config()
        summary, proposals = generate_and_store(
            conn,
            client=object(),
            config=cfg,
            count=4,
            generator=fake_gen,
            id_factory=_deterministic_id_factory("mix00000"),
        )

        assert summary.proposed == 4
        assert summary.stored == 2   # repeated_text + unique
        assert summary.skipped == 2  # existing_text + second repeated_text


# ---------------------------------------------------------------------------
# Zero proposals test
# ---------------------------------------------------------------------------

class TestZeroProposals:
    def test_zero_proposals_returns_all_zero_summary(self):
        """No proposals → SuggestSummary(proposed=0, stored=0, skipped=0)."""
        conn = _make_conn()

        def fake_gen(client, *, gap_report, abbvie_brands, competitor_brands,
                     existing_texts, count, model):
            return GenerationResult(proposals=[])

        cfg = _make_config()
        summary, proposals = generate_and_store(
            conn,
            client=object(),
            config=cfg,
            count=0,
            generator=fake_gen,
        )

        assert summary == SuggestSummary(proposed=0, stored=0, skipped=0)
        assert proposals == []

    def test_zero_proposals_nothing_stored(self):
        """No proposals → no questions stored in DB."""
        conn = _make_conn()

        def fake_gen(client, *, gap_report, abbvie_brands, competitor_brands,
                     existing_texts, count, model):
            return GenerationResult(proposals=[])

        cfg = _make_config()
        generate_and_store(
            conn,
            client=object(),
            config=cfg,
            count=0,
            generator=fake_gen,
        )

        assert list_questions(conn) == []


# ---------------------------------------------------------------------------
# Model fallback test
# ---------------------------------------------------------------------------

class TestModelFallback:
    def test_uses_config_scoring_model_when_model_not_specified(self):
        """When model=None, uses config.settings.scoring_model."""
        conn = _make_conn()
        captured = {}

        def fake_gen(client, *, gap_report, abbvie_brands, competitor_brands,
                     existing_texts, count, model):
            captured["model"] = model
            return GenerationResult(proposals=[])

        cfg = _make_config(scoring_model="my-special-model")
        generate_and_store(
            conn,
            client=object(),
            config=cfg,
            count=0,
            generator=fake_gen,
        )

        assert captured["model"] == "my-special-model"

    def test_explicit_model_overrides_config(self):
        """When model= is explicitly provided, it takes precedence over config."""
        conn = _make_conn()
        captured = {}

        def fake_gen(client, *, gap_report, abbvie_brands, competitor_brands,
                     existing_texts, count, model):
            captured["model"] = model
            return GenerationResult(proposals=[])

        cfg = _make_config(scoring_model="config-model")
        generate_and_store(
            conn,
            client=object(),
            config=cfg,
            count=0,
            model="override-model",
            generator=fake_gen,
        )

        assert captured["model"] == "override-model"


# ---------------------------------------------------------------------------
# Dedup normalisation test
# ---------------------------------------------------------------------------

class TestDedupNormalisation:
    def test_dedup_is_case_and_whitespace_insensitive(self):
        """Duplicates are matched case-insensitively and whitespace-normalised."""
        conn = _make_conn()
        _seed_approved_question(
            conn,
            question_id="Q-NORM",
            question_text="  What Is Skyrizi Good For?  ",
        )

        def fake_gen(client, *, gap_report, abbvie_brands, competitor_brands,
                     existing_texts, count, model):
            return GenerationResult(proposals=_make_proposals(
                "what is skyrizi good for?",   # normalised duplicate
                "A completely different question?",
            ))

        cfg = _make_config()
        summary, _ = generate_and_store(
            conn,
            client=object(),
            config=cfg,
            count=2,
            generator=fake_gen,
            id_factory=_deterministic_id_factory("norm0000"),
        )

        assert summary.stored == 1
        assert summary.skipped == 1
