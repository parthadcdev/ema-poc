"""The run loop (FR-2, FR-204, FR-501/503/504, NF-003/005).

For each active+approved question, fan out to all configured adapters
concurrently (network I/O in a thread pool), then persist every result
serially in this (main) thread — sqlite3 connections are not shared across
threads. Each (question_id, llm_name) already captured (status != FAILED) is
skipped so a run resumes without re-submitting completed work."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from ema_poc.adapters.base import LLMAdapter
from ema_poc.agent.executor import execute
from ema_poc.agent.rate_limiter import RateLimiter
from ema_poc.audit import record_event
from ema_poc.config import AppConfig
from ema_poc.prompts import resolve_system_prompt
from ema_poc.repositories.questions import active_approved
from ema_poc.repositories.responses import build_response, completed_keys, save_response
from ema_poc.repositories.runs import create_run, finish_run, get_run

_STATUSES = ("SUCCESS", "FAILED", "TRUNCATED", "BLOCKED")


@dataclass
class RunSummary:
    run_id: str
    questions_attempted: int
    responses_captured: int
    by_status: dict
    failure_count: int
    total_tokens: int
    est_cost: float


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(
    conn,
    adapters: list[LLMAdapter],
    config: AppConfig,
    *,
    run_id: str | None = None,
    id_factory=lambda: uuid4().hex,
    now_factory=_now_iso,
    rate_limiters: dict | None = None,
    sleep=time.sleep,
    max_workers: int | None = None,
) -> RunSummary:
    started = now_factory()
    if run_id is None:
        run_id = id_factory()
        create_run(conn, run_id, started_at=started)
    elif get_run(conn, run_id) is None:
        create_run(conn, run_id, started_at=started)

    if rate_limiters is None:
        rate_limiters = {
            t.name: RateLimiter(t.rate_limit.requests_per_minute) for t in config.targets
        }
    pricing = {t.name: t.pricing for t in config.targets}

    questions = active_approved(conn)
    done = completed_keys(conn, run_id)

    by_status = {s: 0 for s in _STATUSES}
    questions_attempted = 0
    responses_captured = 0
    failure_count = 0
    total_tokens = 0
    est_cost = 0.0

    pool = ThreadPoolExecutor(max_workers=max_workers or max(1, len(adapters)))
    try:
        for question in questions:
            system_prompt = resolve_system_prompt(question.persona, config.settings)
            futures = {}
            for adapter in adapters:
                if (question.question_id, adapter.name) in done:
                    continue
                futures[
                    pool.submit(
                        execute,
                        adapter,
                        system_prompt,
                        question.question_text,
                        max_retries=config.settings.max_retries,
                        backoff=config.settings.backoff_seconds,
                        rate_limiter=rate_limiters.get(adapter.name),
                        sleep=sleep,
                    )
                ] = adapter

            if not futures:
                continue
            questions_attempted += 1

            for fut in as_completed(futures):
                adapter = futures[fut]
                llm_resp = fut.result()
                # Reuse any existing FAILED row's response_id for this
                # (run, question, adapter) so a resume-retry is an UPDATE
                # rather than a conflicting INSERT. If no prior row exists
                # (first attempt), generate a fresh id.
                existing = conn.execute(
                    "SELECT response_id FROM responses WHERE run_id = ?"
                    " AND question_id = ? AND llm_name = ? AND status = 'FAILED'",
                    (run_id, question.question_id, adapter.name),
                ).fetchone()
                if existing:
                    reuse_id = existing["response_id"]
                    conn.execute(
                        "DELETE FROM responses WHERE response_id = ?",
                        (reuse_id,),
                    )
                    response_id = reuse_id
                else:
                    response_id = id_factory()
                response = build_response(
                    run_id=run_id,
                    question=question,
                    adapter=adapter,
                    llm_response=llm_resp,
                    now=now_factory(),
                    response_id=response_id,
                )
                save_response(conn, response)
                record_event(
                    conn,
                    event_type="LLM_RESPONSE",
                    role="TARGET",
                    question_id=question.question_id,
                    llm_target=adapter.name,
                    detail=llm_resp.status,
                )
                responses_captured += 1
                by_status[llm_resp.status] = by_status.get(llm_resp.status, 0) + 1
                if llm_resp.status == "FAILED":
                    failure_count += 1
                ptok = llm_resp.prompt_tokens or 0
                ctok = llm_resp.completion_tokens or 0
                total_tokens += ptok + ctok
                price = pricing.get(adapter.name)
                if price is not None:
                    est_cost += (
                        ptok / 1000 * price.input_per_1k
                        + ctok / 1000 * price.output_per_1k
                    )
    finally:
        pool.shutdown(wait=True)

    finish_run(
        conn,
        run_id,
        ended_at=now_factory(),
        questions_attempted=questions_attempted,
        responses_captured=responses_captured,
        failure_count=failure_count,
        total_tokens=total_tokens,
        est_cost=est_cost,
    )
    return RunSummary(
        run_id=run_id,
        questions_attempted=questions_attempted,
        responses_captured=responses_captured,
        by_status=by_status,
        failure_count=failure_count,
        total_tokens=total_tokens,
        est_cost=est_cost,
    )
