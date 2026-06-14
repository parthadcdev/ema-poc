# Question-Generation Assist — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** `ema suggest-questions` analyzes coverage + effectiveness gaps, asks Claude for new questions, and stores them as PENDING (source='generated') for Medical Affairs approval.

**Branch:** `feature/question-generation`. **Spec:** `docs/superpowers/specs/2026-06-14-question-generation-design.md`.

---

### Task 1: `source` column on questions

**Files:** `ema_poc/db.py`, `ema_poc/models.py`, `ema_poc/repositories/questions.py`, tests.

- `db.py`: add `source TEXT NOT NULL DEFAULT 'manual'` to the `questions` CREATE TABLE; add `("questions", "source", "TEXT NOT NULL DEFAULT 'manual'")` to `_ADDITIVE_COLUMNS`.
- `models.py`: add `source: str = "manual"` to the `Question` model.
- `questions.py`:
  - `_insert_version` — add `source` to the INSERT column list + bind `q.source`.
  - `_question_from_row` — ensure `source` flows into the reconstructed Question (READ it: if it does `Question(**dict(row))` it's automatic; if it constructs fields explicitly, add `source=row["source"]`).
  - `add_question(..., source: str = "manual")` — pass `source=source` into the `Question(...)` it builds.
- Tests: `add_question(..., source="generated")` → `get_current(...).source == "generated"`; default is "manual"; migration test (tests/test_db.py) adds `source` to an old questions table.

### Task 2: Gap analysis — `analyze_gaps`

**Files:** `ema_poc/suggest/__init__.py` (empty), `ema_poc/suggest/gaps.py`, `tests/suggest/__init__.py` (empty), `tests/suggest/test_gaps.py`.

- READ `ema_poc/repositories/questions.py` (`active_approved`, `list_questions`), `ema_poc/models.py` (Persona, Domain enums — values Prospect/Provider/Patient and Efficacy/Safety/Comparative/Access/General), `ema_poc/coverage.py` (`question_effectiveness` → list of QuestionEffectiveness with `.low_value`, `.question_id`, `.brand_focus`, `.question_text`, `.not_mentioned_rate`).
- `gaps.py`:
```python
from dataclasses import dataclass, field

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
    under_covered: list  # list[Cell] with count == 0
    low_value: list = field(default_factory=list)  # list[dict]

def analyze_gaps(conn, *, abbvie_brands) -> GapReport: ...
```
  - Count active+approved questions per (brand_focus, persona.value, domain.value). For each abbvie brand × PERSONAS × DOMAINS, a `Cell` with the count; collect those with count == 0 into `under_covered`.
  - `low_value`: from `question_effectiveness(conn)`, the entries with `.low_value is True`, mapped to `{"question_id","brand_focus","question_text","not_mentioned_rate"}`. Empty when there's no scored data.
- Tests: seed a few approved questions for a couple of (brand,persona,domain) cells; assert `under_covered` includes a known empty cell and EXCLUDES a covered one; with a seeded chronically-NOT_MENTIONED question + responses, `low_value` includes it; with no scored data, `low_value == []`.

### Task 3: Generator — Claude structured output

**Files:** `ema_poc/suggest/generator.py`, `tests/suggest/test_generator.py`.

- READ `ema_poc/scoring/scorer.py` and `ema_poc/hallucination/detector.py` for the messages.parse pattern (adaptive thinking, no temperature, _SYSTEM, _build_prompt).
- Pydantic:
```python
from typing import Literal
class ProposedQuestion(BaseModel):
    question_text: str
    persona: Literal["Prospect", "Provider", "Patient"]
    domain: Literal["Efficacy", "Safety", "Comparative", "Access", "General"]
    therapeutic_area: str
    brand_focus: str
    rationale: str
class GenerationResult(BaseModel):
    proposals: list[ProposedQuestion] = Field(default_factory=list)
```
- `_SYSTEM`: a Medical Affairs content strategist proposing brand-monitoring questions; questions must be realistic, distinct, and contain NO PII/PHI.
- `_build_prompt(*, gap_report, abbvie_brands, competitor_brands, existing_texts, count)`: include (a) the under-covered cells (brand/persona/domain), (b) the low-value questions to improve on, (c) the AbbVie + competitor brand lists, (d) the existing question texts to AVOID duplicating, and ask for `count` new questions targeting the gaps, each tagged persona/domain/therapeutic_area/brand_focus with a one-line rationale. (Truncate existing_texts if very long — include up to ~150 to bound prompt size.)
- `suggest_questions(client, *, gap_report, abbvie_brands, competitor_brands, existing_texts, count, model="claude-opus-4-8") -> GenerationResult` via `client.messages.parse(model=, max_tokens=4096, thinking={"type":"adaptive"}, system=_SYSTEM, messages=[...], output_format=GenerationResult)`.
- Tests (fake client capturing kwargs, returning a GenerationResult): returns it; `_build_prompt` contains an under-covered cell's brand+persona+domain, a low-value question text, and an existing-text-to-avoid marker; max_tokens 4096, no temperature.

### Task 4: Pipeline — generate_and_store

**Files:** `ema_poc/suggest/pipeline.py`, `tests/suggest/test_pipeline.py`.

- `SuggestSummary(proposed: int, stored: int, skipped: int)`.
- `_norm(text)` = lowercased, stripped, collapsed whitespace (for dedup).
- `generate_and_store(conn, *, client, config, count, model=None, generator=suggest_questions, now_factory=_now_iso, id_factory=lambda: uuid4().hex) -> tuple[SuggestSummary, list[ProposedQuestion]]`:
  - `model = model or config.settings.scoring_model`.
  - `gap_report = analyze_gaps(conn, abbvie_brands=config.brands.abbvie_brands)`.
  - existing = current questions (READ questions repo — `list_questions(conn)` or iterate; get each current version's question_text); `existing_norm = {_norm(t)}`; `existing_texts = [those texts]`.
  - `result = generator(client, gap_report=gap_report, abbvie_brands=config.brands.abbvie_brands, competitor_brands=config.brands.competitor_brands, existing_texts=existing_texts, count=count, model=model)`.
  - For each proposal: if `_norm(p.question_text) in existing_norm` → skipped += 1; else `add_question(conn, question_id=f"GEN-{id_factory()[:8]}", question_text=p.question_text, persona=p.persona, domain=p.domain, therapeutic_area=p.therapeutic_area, brand_focus=p.brand_focus, source="generated", now=now_factory())`; add its norm to existing_norm (avoid intra-batch dups); stored += 1.
  - proposed = len(result.proposals). Return (SuggestSummary(...), result.proposals).
- Tests (fake generator returning 3 proposals, one duplicating an existing question): stores 2 as PENDING + inactive + source='generated' (assert via questions repo: approval_status PENDING, active False, source generated), skips the dup; summary proposed=3 stored=2 skipped=1; the GEN- ids exist.

### Task 5: CLI `ema suggest-questions`

**Files:** `ema_poc/cli.py`, tests `tests/test_cli.py`.

- READ cli.py (Deps, default_deps, _parse_args, _open_db, main, credential-validation tuple).
- `Deps`: add `generate_questions: Callable | None = None`. Wire in `default_deps()` (lazy `from ema_poc.suggest.pipeline import generate_and_store`).
- `_parse_args`: `p_sug = sub.add_parser("suggest-questions", help="Propose new questions for coverage gaps (PENDING, for MA approval)")`; `p_sug.add_argument("--count", type=int, default=10)`.
- Add `"suggest-questions"` to the credential-validation tuple (uses Claude).
- `main` branch: open DB, `client = deps.make_scoring_client(deps.env)`, `summary, proposals = deps.generate_questions(conn, client=client, config=config, count=args.count)`, print a header summary line (`Proposed {summary.proposed}, stored {summary.stored} PENDING, skipped {summary.skipped} duplicate(s).`) then each stored proposal (persona/domain/brand + text + rationale). (proposals returned are ALL proposals; print them; that's fine.)
- Tests (fake Deps): `main(["suggest-questions","--count","5"], deps=...)` returns 0, builds client, calls generate_questions with count=5, prints the summary; credentials validated.

---

## Self-Review Notes (author)
- Spec coverage: source column (T1), gap analysis coverage+effectiveness (T2), Claude generator (T3), pipeline store-PENDING+dedup (T4), CLI (T5), offline tests each task.
- SE-002: the BINDING gate is `approval_status=PENDING`. `active_approved` requires `active=True AND approval_status='APPROVED'`, so a PENDING question NEVER runs regardless of its `active` flag. `add_question` already creates questions PENDING by default (Question model default), so generated questions are kept out of runs with no extra work. The pipeline test asserts `approval_status == PENDING` (the gate); do NOT add an `active=False` param or change add_question — it's unnecessary.
- Type consistency: `analyze_gaps(conn,*,abbvie_brands)->GapReport(under_covered,low_value)`; `suggest_questions(client,*,gap_report,abbvie_brands,competitor_brands,existing_texts,count,model)->GenerationResult(proposals)`; `generate_and_store(...)->(SuggestSummary(proposed,stored,skipped), list[ProposedQuestion])`; `add_question(...,source='manual')`.
