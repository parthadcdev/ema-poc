# Cost-Overrun (Budget) Enforcement — Design

**Date:** 2026-06-14
**Status:** Approved
**Addresses:** NF-015 / stakeholder #8 — the `max_tokens_per_run` budget cap is
defined in config but not enforced; define what happens to the partial run.

## Decision (from brainstorming)

Soft cap: when a run's accumulated tokens reach `max_tokens_per_run`, stop
dispatching further questions; **retain** the already-captured (append-only)
responses; finalize the run with status `BUDGET_EXCEEDED`. `null` cap = unlimited
(unchanged behavior).

## Components

### Runner (`ema_poc/agent/runner.py`)
- Read `cap = config.settings.max_tokens_per_run` (may be `None`).
- In the per-question dispatch loop, **before submitting the next question's
  batch**, if `cap is not None and total_tokens >= cap`: set
  `run_status = "BUDGET_EXCEEDED"`, set a `budget_exceeded = True` flag, and
  `break`. The first question always runs (total_tokens starts at 0); the batch
  that crosses the cap completes (soft cap — may slightly overshoot).
- The existing `finally` block calls `finish_run(..., status=run_status)`, so the
  run is finalized `BUDGET_EXCEEDED`. Partial responses are already persisted
  (append-only) — nothing is discarded.
- `RunSummary` gains `budget_exceeded: bool = False`, set True when the cap stopped
  the run; returned in the summary.

### Reporting (`ema_poc/reporting.py`)
- `format_run_report` appends a line when `summary.budget_exceeded` is True, e.g.
  `f"  budget exceeded:     stopped at {summary.total_tokens} / {cap} tokens"`.
  The report needs the cap value — pass it via the summary (add `token_budget:
  int | None = None` to RunSummary, set from `config.settings.max_tokens_per_run`)
  OR format using just the flag + total_tokens. Simplest: include the budget line
  using `summary.total_tokens` and a stored `token_budget` on the summary.

### Config
No change — `max_tokens_per_run` already exists (default `null`).

## Data flow
`ema run` (cap set) → runner dispatches questions, accumulating tokens → at a
question boundary tokens ≥ cap → stop, `run_status=BUDGET_EXCEEDED`,
`budget_exceeded=True` → `finish_run` finalizes → report shows the budget line.
Partial responses remain queryable / scoreable like any run.

## Testing (offline)
- Low `max_tokens_per_run` + a fake adapter returning a fixed token count +
  several approved questions: the run stops before all questions are dispatched;
  `summary.budget_exceeded is True`; `get_run(...).status == "BUDGET_EXCEEDED"`;
  at least one but fewer-than-all questions' responses are persisted (partial data
  retained).
- `max_tokens_per_run = None` (default): all questions dispatched; status
  `COMPLETED`; `summary.budget_exceeded is False` (existing behavior unchanged).
- `format_run_report` shows the budget line when `budget_exceeded` True, omits it
  otherwise.

## Out of scope (deferrable)
- Per-target budgets.
- Hard cancellation of in-flight requests (soft cap only).
- A distinct BUDGET_EXCEEDED alert / notification.
