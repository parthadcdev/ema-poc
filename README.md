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

## CLI

After `pip install -e .`, the `ema` command is available:

- `ema run` — run the full approved question bank against all enabled targets.
- `ema run --persona Provider --domain Safety --score` — subset run, then score.
- `ema dry-run` — validate config + target connectivity without writing.
- `ema score` — score any unscored responses.
- `ema healthcheck` — check connectivity to all configured LLM APIs.
- `ema import-questions path/to/questions.csv` — import a question bank (CSV or .xlsx).

All commands accept `--config-dir` (default `config`). Required API keys come
from the environment (see `.env.example`).

## Scheduling (daily run)

The POC runs unattended via OS cron. Example crontab entry for a daily run at
02:00 UTC that also scores results:

```
0 2 * * *  cd /path/to/ema-poc && . .venv/bin/activate && ema run --score >> logs/cron.log 2>&1
```

Each `ema run` starts a new run with a fresh `run_id`, so daily cron runs are
independent. Responses are append-only and are never overwritten. To **resume a
specific run** that was interrupted mid-execution, pass its id:

    ema run --run-id <RUN_ID>

The runner then re-dispatches only the question/target pairs not yet captured
for that run (FR-504).

## Status

Foundations phase complete (config, storage, models, logging, audit).
Subsequent phases: question repository, LLM adapters + runner, response
repository, scoring + alerts, scheduling, dashboard.
