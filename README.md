# Evidence Monitoring Agent — POC

Automated monitoring of how multiple LLMs respond to persona-tagged questions
about AbbVie therapies: collect responses, score brand sentiment and
competitive positioning with Claude, alert on thresholds, and report via a
self-contained HTML dashboard.

See `docs/superpowers/specs/2026-06-13-evidence-monitoring-agent-poc-design.md`
for the full design.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in API keys
```

Required environment variables (see `.env.example`): `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `GOOGLE_API_KEY`.

## Configuration

- `config/settings.yaml` — global settings + AbbVie/competitor brand lists.
- `config/llm_targets.yaml` — monitored LLM targets, model pins, params,
  pricing, and per-target rate limits. Add a target by adding an entry here and
  a matching adapter module (no core code change).

## Running tests

```bash
. .venv/bin/activate && pytest
```

## Status

Foundations phase complete (config, storage, models, logging, audit).
Subsequent phases: question repository, LLM adapters + runner, response
repository, scoring + alerts, scheduling, dashboard.
