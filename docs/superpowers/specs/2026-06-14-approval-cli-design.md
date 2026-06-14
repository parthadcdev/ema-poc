# Question Approval CLI — Design

**Date:** 2026-06-14
**Status:** Approved
**Addresses:** Closing the loop on question-generation — Medical Affairs needs a
CLI way to triage PENDING questions (including `source='generated'` proposals)
instead of the raw repository API. Supports SE-002 (MA approval before active).

## Decisions

Three local, no-credential CLI commands wrapping existing repo functions
(`approve_question`, `reject_question`, `list_questions`):

- **`ema list-questions [--pending] [--source S] [--persona P] [--domain D]`** —
  print the current version of matching questions for triage.
- **`ema approve <question_id> [--approver NAME]`** — approve a question.
- **`ema reject <question_id> [--approver NAME]`** — reject a question.

`--approver` defaults to `"Medical Affairs"`. None of these need credentials
(local DB ops) — not added to the credential-validation set.

## Behaviour

### list-questions
- `list_questions(conn, approval_status="PENDING" if --pending else None,
  persona=..., domain=...)`; the `--source` filter is applied in the CLI in
  Python (list_questions has no source filter) — keep only questions whose
  `.source == args.source` when set.
- Print one line per question: `question_id · approval_status · source ·
  persona/domain/brand_focus · question_text` (truncated). Print a count header.

### approve / reject
- Validate the question exists first (`get_current(conn, question_id)`); if not,
  raise a clear `ConfigError(f"No such question: {question_id!r}")` (surfaced like
  other CLI errors) — do nothing.
- Else call `approve_question`/`reject_question(conn, question_id, approver_name)`;
  print a confirmation: `Approved <id> (approver: <name>).` /
  `Rejected <id> (approver: <name>).`

## Storage / model
No schema changes. Reuses the existing versioned approve/reject (each creates a
new question version with the new `approval_status` + `approver_name`).

## CLI wiring
Add to `Deps`: `approve_question`, `reject_question`, `list_questions`,
`get_current` (callables; wired in `default_deps()` from the questions repo).
Subcommands parsed in `_parse_args`; handled in `main`; NOT in the
credential-validation set.

## Testing (offline, injected fakes / real repo on a tmp DB)
- `approve`/`reject` change a PENDING question's `approval_status` (to APPROVED/
  REJECTED) and set the approver — verified via the repo on a seeded tmp DB.
- approving/rejecting a missing id → clear error, no change.
- `list-questions --pending --source generated` prints only PENDING generated
  questions (seed a mix; assert a non-generated/approved one is excluded).
- default approver is "Medical Affairs"; `--approver` overrides it.

## Out of scope (deferrable)
- Dashboard write-back approval (stays CLI/repo).
- Bulk approve-all / interactive review.
