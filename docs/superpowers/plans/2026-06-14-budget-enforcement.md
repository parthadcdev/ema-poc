# Cost-Overrun (Budget) Enforcement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Enforce `max_tokens_per_run`: stop dispatching when the cap is hit, finalize the run `BUDGET_EXCEEDED`, retain partial append-only data, surface it in the report.

**Branch:** `feature/budget-enforcement`. **Spec:** `docs/superpowers/specs/2026-06-14-budget-enforcement-design.md`.

---

### Task 1: Runner enforces the cap + RunSummary flags

**Files:** `ema_poc/agent/runner.py`, `tests/agent/test_runner.py`.

- READ `runner.py` (the `run(...)` function: the per-question `for question in questions:` loop, the `total_tokens` accumulation in the `as_completed` loop, the `run_status` variable + the `finally` block that calls `finish_run(..., status=run_status)`, and the `RunSummary` dataclass + final return).
- Add `budget_exceeded: bool = False` to the `RunSummary` dataclass; also add `token_budget: int | None = None`.
- In `run(...)`: capture `cap = config.settings.max_tokens_per_run`. Initialize `budget_exceeded = False`.
- At the TOP of the `for question in questions:` loop body, before building/submitting that question's futures, add:
```python
            if cap is not None and total_tokens >= cap:
                budget_exceeded = True
                run_status = "BUDGET_EXCEEDED"
                break
```
  (total_tokens starts at 0 so the first question always runs; the batch that crosses the cap completes — soft cap.)
- IMPORTANT: do not clobber `run_status` on the success path — currently `run_status = "COMPLETED"` is set before the loop and `= "FAILED"` in the except. Setting it to `"BUDGET_EXCEEDED"` on break is correct; the `finally` uses whatever it is. Confirm the except path still overrides to FAILED on a real exception (it should, since the except sets it before re-raising).
- In the final `return RunSummary(...)`, set `budget_exceeded=budget_exceeded` and `token_budget=cap`.
- Tests (use the existing runner-test fixtures; the fake adapter returns an LLMResponse with known prompt/completion tokens; set `samples_per_question=1`):
  - Seed e.g. 3 approved questions; set `max_tokens_per_run` low enough that after 1 question's batch the cap is reached (compute from the fake adapter's token count × adapters). Run → `summary.budget_exceeded is True`; `get_run(conn, summary.run_id).status == "BUDGET_EXCEEDED"`; the number of distinct question_ids with responses is FEWER than 3 (partial); but at least 1 (partial data retained). Assert via the responses table.
  - `max_tokens_per_run=None` (the existing default in test configs): all 3 questions dispatched; `summary.budget_exceeded is False`; `get_run(...).status == "COMPLETED"`. (Existing runner tests already cover the None/COMPLETED path — ensure they still pass; their configs likely have max_tokens_per_run=None by default.)
- Verify existing runner tests still pass (they use configs with max_tokens_per_run None → no enforcement).

### Task 2: Report shows the budget line

**Files:** `ema_poc/reporting.py`, `tests/test_reporting.py`.

- `format_run_report`: when `summary.budget_exceeded` is True, append a line after the cost line, e.g.:
```python
    if getattr(summary, "budget_exceeded", False):
        lines.append(
            f"  budget exceeded:     stopped at {summary.total_tokens} / "
            f"{summary.token_budget} tokens"
        )
```
- Tests: a RunSummary with `budget_exceeded=True, total_tokens=1200, token_budget=1000` → report contains "budget exceeded" and "1200" and "1000"; a normal summary (`budget_exceeded=False`) → report does NOT contain "budget exceeded". (Construct RunSummary directly with all required fields including the two new ones.)

Run FULL suite until green after each task. Commit per task:
```bash
git add ema_poc/agent/runner.py tests/agent/test_runner.py
git commit -m "feat: enforce max_tokens_per_run (soft cap) -> BUDGET_EXCEEDED, retain partial data"   # task 1
git add ema_poc/reporting.py tests/test_reporting.py
git commit -m "feat: run report shows budget-exceeded line"                                            # task 2
```

---

## Self-Review Notes (author)
- Soft cap at question boundary; first question always runs; in-flight batch completes.
- Partial data retained (append-only) — no deletion; run marked BUDGET_EXCEEDED.
- None cap = unchanged behavior (existing tests pass).
- RunSummary gains budget_exceeded + token_budget; report shows the line only when exceeded.
- Don't let BUDGET_EXCEEDED override a real FAILED (except path sets FAILED before re-raise).
