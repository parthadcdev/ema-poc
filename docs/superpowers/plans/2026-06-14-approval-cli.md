# Question Approval CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** `ema list-questions` / `ema approve <id>` / `ema reject <id>` — local CLI for Medical Affairs to triage PENDING questions (incl. generated proposals).

**Branch:** `feature/approval-cli`. **Spec:** `docs/superpowers/specs/2026-06-14-approval-cli-design.md`.

---

### Task 1: `ema list-questions`

**Files:** `ema_poc/cli.py`, `tests/test_cli.py`.

- READ cli.py (Deps, default_deps, _open_db, _parse_args, main) and `ema_poc/repositories/questions.py` (`list_questions(conn, *, persona=, domain=, approval_status=, ...) -> list[Question]`; Question has `.question_id, .approval_status (enum), .source, .persona (enum), .domain (enum), .brand_focus, .question_text`).
- `Deps`: add `list_questions: Callable | None = None`; wire in `default_deps()` (`from ema_poc.repositories.questions import list_questions`).
- `_parse_args`: 
```python
    p_lq = sub.add_parser("list-questions", help="List questions for triage")
    p_lq.add_argument("--pending", action="store_true", help="Only PENDING questions")
    p_lq.add_argument("--source", default=None, help="Filter by source (e.g. generated)")
    p_lq.add_argument("--persona", default=None)
    p_lq.add_argument("--domain", default=None)
```
- `main` branch (NOT credential-gated):
```python
    if args.command == "list-questions":
        conn = _open_db(deps, config)
        qs = deps.list_questions(
            conn,
            approval_status="PENDING" if args.pending else None,
            persona=args.persona, domain=args.domain,
        )
        if args.source is not None:
            qs = [q for q in qs if q.source == args.source]
        deps.out(f"{len(qs)} question(s):")
        for q in qs:
            deps.out(
                f"  {q.question_id} | {q.approval_status.value} | {q.source} | "
                f"{q.persona.value}/{q.domain.value}/{q.brand_focus} | {q.question_text[:70]}"
            )
        return 0
```
(Match the actual `_open_db(deps, config)` usage. `approval_status`/`persona`/`domain` accept plain strings per list_questions.)
- Tests (tests/test_cli.py): use a fake Deps whose `list_questions` returns a small list of SimpleNamespace questions (with `.approval_status.value`, `.source`, `.persona.value`, `.domain.value`, `.brand_focus`, `.question_text`, `.question_id`) and an `out` recorder. `main(["list-questions","--pending","--source","generated"], deps=...)` → returns 0; `list_questions` received `approval_status="PENDING"`; output filtered to only `source=='generated'` rows; count header printed. No credential validation. (Alternatively seed a real tmp DB with add_question + a generated one + approve one, and use default_deps-style real list_questions — but the fake-Deps approach matches the existing cli tests.)

### Task 2: `ema approve` / `ema reject`

**Files:** `ema_poc/cli.py`, `tests/test_cli.py`.

- READ `approve_question(conn, question_id, approver_name, *, now=None)`, `reject_question(conn, question_id, approver_name, *, now=None)`, `get_current(conn, question_id)` in the questions repo, and how the CLI raises errors (ConfigError from ema_poc.config, already imported at module top from the backfill work).
- `Deps`: add `approve_question`, `reject_question`, `get_current` (callables); wire in `default_deps()` from the questions repo.
- `_parse_args`: 
```python
    p_ap = sub.add_parser("approve", help="Approve a question (Medical Affairs)")
    p_ap.add_argument("question_id")
    p_ap.add_argument("--approver", default="Medical Affairs")
    p_rj = sub.add_parser("reject", help="Reject a question (Medical Affairs)")
    p_rj.add_argument("question_id")
    p_rj.add_argument("--approver", default="Medical Affairs")
```
- `main` branches (NOT credential-gated):
```python
    if args.command in ("approve", "reject"):
        conn = _open_db(deps, config)
        if deps.get_current(conn, args.question_id) is None:
            raise ConfigError(f"No such question: {args.question_id!r}")
        if args.command == "approve":
            deps.approve_question(conn, args.question_id, args.approver)
            deps.out(f"Approved {args.question_id} (approver: {args.approver}).")
        else:
            deps.reject_question(conn, args.question_id, args.approver)
            deps.out(f"Rejected {args.question_id} (approver: {args.approver}).")
        return 0
```
- Tests:
  - Real-repo integration: seed a tmp DB (connect+init_schema), `add_question(... )` a PENDING question, then `main(["approve","Q1"], deps=default-like deps with real repo fns + that conn)` → the question's `get_current(...).approval_status` is APPROVED and `approver_name == "Medical Affairs"`. Easiest: build a Deps with the real `approve_question`/`reject_question`/`get_current`/`list_questions` and a `connect`/`init_schema`/`_open_db` that returns the seeded conn (mirror how other cli tests that touch the DB are structured — check test_cli_dashboard.py / test_cli_integration.py for the pattern of injecting a real conn via deps.connect).
  - `main(["approve","NOPE"], deps=...)` where get_current returns None → raises ConfigError, and approve_question NOT called.
  - `--approver "Dr X"` overrides the default (assert approver_name set to "Dr X").
  - reject sets approval_status REJECTED.

Run FULL suite until green after each task. Commit per task:
```bash
git add ema_poc/cli.py tests/test_cli.py
git commit -m "feat: ema list-questions (triage queue)"        # task 1
git commit -m "feat: ema approve / ema reject commands"         # task 2
```

---

## Self-Review Notes (author)
- Pure CLI wrappers over existing repo functions; no schema/model change.
- approve/reject validate existence first → clear ConfigError on missing id (no silent no-op).
- None credential-gated (local ops).
- Reuses versioned approve/reject (new version per change) — append-only-friendly, audit preserved.
- Type consistency: Deps gains list_questions/approve_question/reject_question/get_current; approver default "Medical Affairs".
