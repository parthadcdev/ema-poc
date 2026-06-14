"""Tests for the reference corpus loader (hallucination detection)."""

from pathlib import Path

import pytest

from ema_poc.hallucination.corpus import (
    BrandReference,
    ReferenceCorpus,
    load_reference_corpus,
)


@pytest.fixture(scope="module")
def corpus() -> ReferenceCorpus:
    return load_reference_corpus("config")


class TestRealCorpus:
    def test_rinvoq_boxed_warnings_non_empty(self, corpus: ReferenceCorpus) -> None:
        rinvoq = corpus.get("Rinvoq")
        assert rinvoq is not None
        assert len(rinvoq.boxed_warnings) > 0

    def test_rinvoq_boxed_warnings_contains_thrombosis(self, corpus: ReferenceCorpus) -> None:
        rinvoq = corpus.get("Rinvoq")
        assert rinvoq is not None
        warnings_lower = [w.lower() for w in rinvoq.boxed_warnings]
        has_thrombosis_or_mace = any(
            "thrombosis" in w or "cardiovascular" in w or "mace" in w
            for w in warnings_lower
        )
        assert has_thrombosis_or_mace, (
            f"Expected thrombosis/MACE warning in {rinvoq.boxed_warnings}"
        )

    def test_rinvoq_indications_contains_rheumatoid_arthritis(self, corpus: ReferenceCorpus) -> None:
        rinvoq = corpus.get("Rinvoq")
        assert rinvoq is not None
        assert "rheumatoid arthritis" in rinvoq.indications

    def test_skyrizi_no_boxed_warnings(self, corpus: ReferenceCorpus) -> None:
        skyrizi = corpus.get("Skyrizi")
        assert skyrizi is not None
        assert skyrizi.boxed_warnings == []

    def test_vraylar_generic_name(self, corpus: ReferenceCorpus) -> None:
        vraylar = corpus.get("Vraylar")
        assert vraylar is not None
        assert vraylar.generic == "cariprazine"

    def test_all_six_brands_present(self, corpus: ReferenceCorpus) -> None:
        expected = {"Skyrizi", "Rinvoq", "Humira", "Vraylar", "Ubrelvy", "Qulipta"}
        assert expected == set(corpus.brands.keys())

    def test_humira_generic(self, corpus: ReferenceCorpus) -> None:
        humira = corpus.get("Humira")
        assert humira is not None
        assert humira.generic == "adalimumab"

    def test_ubrelvy_has_indications(self, corpus: ReferenceCorpus) -> None:
        ubrelvy = corpus.get("Ubrelvy")
        assert ubrelvy is not None
        assert len(ubrelvy.indications) > 0

    def test_qulipta_generic(self, corpus: ReferenceCorpus) -> None:
        qulipta = corpus.get("Qulipta")
        assert qulipta is not None
        assert qulipta.generic == "atogepant"


class TestAbsentFile:
    def test_missing_file_returns_empty_corpus(self, tmp_path: Path) -> None:
        result = load_reference_corpus(tmp_path)
        assert isinstance(result, ReferenceCorpus)
        assert result.brands == {}

    def test_missing_file_get_returns_none(self, tmp_path: Path) -> None:
        result = load_reference_corpus(tmp_path)
        assert result.get("Rinvoq") is None


class TestGetMethod:
    def test_unknown_brand_returns_none(self, corpus: ReferenceCorpus) -> None:
        assert corpus.get("Unknown") is None

    def test_none_brand_returns_none(self, corpus: ReferenceCorpus) -> None:
        assert corpus.get(None) is None

    def test_empty_string_returns_none(self, corpus: ReferenceCorpus) -> None:
        assert corpus.get("") is None
