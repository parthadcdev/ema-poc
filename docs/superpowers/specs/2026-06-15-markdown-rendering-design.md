# Safe Markdown Rendering of Response Text — Design

**Date:** 2026-06-15
**Status:** Approved
**Addresses:** LLM response text (which is markdown — headings, bold, lists,
tables) currently displays as raw escaped source. Render it formatted, safely.

## Decision

Add a self-contained, **XSS-safe** vanilla-JS `renderMarkdown(text)` to both UIs.
It **escapes all HTML first**, then applies a safe markdown subset on the escaped
text, with links sanitized to http/https only. No external library (stays
self-contained). The response text is untrusted (LLM + web-sourced) — escape-first
guarantees no injected HTML/script can execute.

## `renderMarkdown(src)` (identical in both files)
- `esc()` the whole input first (`& < > " '` → entities).
- Line-based parse on the escaped text:
  - fenced code blocks ```` ``` ```` → `<pre><code>`
  - tables (`| a | b |` + `|---|` separator) → `<table class="md-table">`
  - headings `#`..`######` → `<h1>`..`<h6>`
  - blockquotes `>` → `<blockquote>`
  - unordered `- * +` and ordered `1.` lists → `<ul>`/`<ol>`
  - blank-line-separated paragraphs → `<p>`
- Inline (on already-escaped text): `**bold**`, `*italic*`, `` `code` ``, and
  `[text](url)` → `<a href="safeUrl(url)" target=_blank rel="noopener noreferrer">`
  (`safeUrl` = http/https only, else `#`).
- Because the input is escaped up front, every transform only ever wraps
  entity-safe text in fixed tags — untrusted raw HTML can never reach innerHTML.

## Where applied
- **Dashboard** (`render.py` inline JS): the Responses detail panel
  (`response_text`, and the scoring `rationale`) and the Medical Affairs review
  queue's full **response** render via `renderMarkdown` inside a `.md` wrapper.
  Flagged-claim text stays plain-escaped (short snippets).
- **Playground** (`index.html`): the live answer card `.answer` renders via
  `renderMarkdown(ev.answer_text)` (was `textContent`), inside `.md`.

## Styling (`.md` scope, both files, within the AbbVie/readable design)
Headings (tight, serif-ish), readable paragraphs, list indentation, bordered
compact `.md-table`, monospace `code`/`pre` on a tinted surface, blockquote with
an accent left-border, links in the brand accent. Sized for readability.

## Testing (offline)
- Dashboard render test: the JS source contains `function renderMarkdown`, escapes
  before formatting (the escape map appears and is applied to the whole `src`
  first), and `renderMarkdown(` is invoked for the response/rationale. Self-
  contained assertion still holds (no external resources).
- Playground test: `index.html` contains `function renderMarkdown`, the `.answer`
  uses `renderMarkdown(`, and the existing `esc`/`safeUrl` helpers remain.
- XSS lock: a Python-level structural assertion that `renderMarkdown` escapes the
  whole input first (e.g. the function escapes `src` before any markdown regex) —
  documents the escape-first guarantee; full behavioral proof is via review (no JS
  runtime in CI).

## Out of scope (deferrable)
- Full CommonMark (nested lists, reference links, images — images intentionally
  NOT rendered: untrusted `<img>` is an SSRF/track risk; image markdown renders as
  a plain link or text).
- Syntax highlighting.
