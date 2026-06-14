"""Reference corpus of authoritative brand facts for hallucination detection.

PROTOTYPE data lives in config/reference_corpus.yaml (public-label facts pending
Medical Affairs validation). The loader degrades safely to an empty corpus when
the file is absent."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class BrandReference(BaseModel):
    generic: str = ""
    indications: list[str] = Field(default_factory=list)
    key_dosing: str = ""
    boxed_warnings: list[str] = Field(default_factory=list)


class ReferenceCorpus(BaseModel):
    brands: dict[str, BrandReference] = Field(default_factory=dict)

    def get(self, brand: str | None) -> BrandReference | None:
        if not brand:
            return None
        return self.brands.get(brand)


def load_reference_corpus(config_dir: Path | str) -> ReferenceCorpus:
    path = Path(config_dir) / "reference_corpus.yaml"
    if not path.exists():
        return ReferenceCorpus()
    raw = yaml.safe_load(path.read_text()) or {}
    return ReferenceCorpus(brands={
        name: BrandReference(**(facts or {}))
        for name, facts in (raw.get("brands", {}) or {}).items()
    })
