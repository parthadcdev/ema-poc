# Hallucination Detection — Design

**Date:** 2026-06-13
**Status:** Approved
**Addresses:** Stakeholder feedback #1a (MUST → Sprint 3) — detect LLM claims that
contradict or overstate a Medical Affairs reference corpus (dosing, indications,
boxed warnings). Prototype with a static reference document.

## Goal

Flag claims in a monitored LLM response that **contradict** or are **unsupported
by** an authoritative reference for the brand in focus — wrong dosing, denied or
omitted boxed warnings, indications beyond the approved label — and raise an alert
on high-risk responses.

## Decisions (from brainstorming)

1. **Reference corpus:** a static, structured YAML (`config/reference_corpus.yaml`)
   authored now for the 6 loaded brands from public labels (marked prototype /
   pending Medical Affairs validation). The real corpus replaces the file using
   the same schema.
2. **Comparison engine:** Claude with structured output (`messages.parse`),
   consistent with the existing scorer; reuses the inert-data / prompt-injection
   framing (response_text is untrusted data, never instructions).
3. **Output:** per-claim flags in a new table + an overall risk level per response
   + an alert on HIGH risk.

## Reference corpus schema

```yaml
# PROTOTYPE facts from public labels — pending Medical Affairs validation; not authoritative.
brands:
  <BrandName>:
    generic: <inn>
    indications: [<approved indication>, ...]
    key_dosing: "<short dosing summary>"
    boxed_warnings: [<warning>, ...]   # [] if none
```

Parsed into `ReferenceCorpus { brands: dict[str, BrandReference] }` where
`BrandReference { generic, indications, key_dosing, boxed_warnings }`. A brand
absent from the corpus is "unknown" — its responses are skipped (no ground truth
to check against).

## Components — `ema_poc/hallucination/`

- **`corpus.py`** — `BrandReference`, `ReferenceCorpus` (Pydantic), and
  `load_reference_corpus(config_dir)` (reads `config/reference_corpus.yaml`;
  returns an empty corpus if the file is absent, so the feature degrades safely).
- **`detector.py`** — structured-output schemas + the per-response check:
  - `FlaggedClaim { claim: str, conflicts_with: str, severity: Literal[LOW,MEDIUM,HIGH] }`
  - `HallucinationResult { risk_level: Literal[NONE,LOW,MEDIUM,HIGH], flagged_claims: list[FlaggedClaim], rationale: str }`
  - `_SYSTEM` + `_build_prompt(response_text, brand_focus, brand_reference)` — supplies
    the brand's reference facts and the response (delimited, framed as untrusted
    inert data), instructing Claude to flag contradictions and unsupported/overstated
    claims and assign an overall risk level.
  - `check_response(client, *, response_text, brand_focus, brand_reference, model) -> HallucinationResult`.
- **`pipeline.py`** — `check_pending(conn, *, client, config, corpus, scorer=check_response, ...) -> CheckSummary(checked, alerts_raised)`:
  for each SUCCESS response whose `brand_focus` is in the corpus and which has no
  `hallucination_checks` row, run the detector, persist the check + flags, and
  raise an alert when `risk_level == HIGH` (or any flag severity HIGH). The alert
  attaches to the response's latest score_id; if unscored, skip the alert but
  still record the check.

## Storage (two new append-only tables; alerts reused)

```sql
CREATE TABLE IF NOT EXISTS hallucination_checks (
    response_id  TEXT PRIMARY KEY,
    risk_level   TEXT NOT NULL,
    rationale    TEXT,
    model        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    FOREIGN KEY (response_id) REFERENCES responses(response_id)
);

CREATE TABLE IF NOT EXISTS hallucination_flags (
    flag_id        TEXT PRIMARY KEY,
    response_id    TEXT NOT NULL,
    claim          TEXT NOT NULL,
    conflicts_with TEXT,
    severity       TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    FOREIGN KEY (response_id) REFERENCES responses(response_id)
);
```

"Needs checking" = SUCCESS responses with an in-corpus brand_focus and no
`hallucination_checks` row — making the pass idempotent/resumable like scoring.
Both tables are brand-new (CREATE TABLE IF NOT EXISTS adds them to existing DBs).
HIGH-risk alerts reuse the `alerts` table with reason
`HALLUCINATION: HIGH risk — N flagged claim(s)`.

## CLI & config

- **`ema check-hallucinations`** — runs `check_pending`; added to the
  credential-validation set (needs ANTHROPIC_API_KEY). Intended after `ema score`.
- Detection model = `config.settings.scoring_model` (claude-opus-4-8).
- The corpus file path is `config/reference_corpus.yaml` (under the config dir).

## Testing

A fake Claude client returns a `HallucinationResult`, keeping the suite offline:
- corpus loads; absent file → empty corpus; brand lookup.
- `_build_prompt` embeds the brand's reference facts + the inert-data framing.
- `check_pending`: persists a check + its flags; raises an alert on HIGH risk;
  skips already-checked responses and out-of-corpus brands; idempotent.
- storage round-trips; FKs enforced.

## Out of scope (deferrable)

- A dedicated dashboard hallucination panel beyond the existing Alerts section.
- PDF / free-text corpus ingestion (the real corpus arrives as structured YAML).
- Versioned re-checks of the same response (one check per response; re-run only
  after the corpus changes — a future enhancement).
