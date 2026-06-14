"""The run loop (FR-2, FR-204, FR-501/503/504, NF-003/005).

For each active+approved question, fan out to all configured adapters
concurrently (network I/O in a thread pool), then persist every result
serially in this (main) thread — sqlite3 connections are not shared across
threads. Each (question_id, llm_name) already captured (status != FAILED) is
skipped so a run resumes without re-submitting completed work. Responses are
append-only: a retried FAILED pair gets a NEW response row (the prior FAILED
row is preserved for audit) — never deleted or overwritten."""

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
from ema_poc.repositories.citations import save_citations
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
    backfill_for: str | None = None
    budget_exceeded: bool = False
    token_budget: int | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(
    conn,
    adapters: list[LLMAdapter],
    config: AppConfig,
    *,
    persona=None,
    therapeutic_area: str | None = None,
    brand_focus: str | None = None,
    domain=None,
    run_id: str | None = None,
    id_factory=lambda: uuid4().hex,
    now_factory=_now_iso,
    rate_limiters: dict | None = None,
    sleep=time.sleep,
    max_workers: int | None = None,
    backfill_for: str | None = None,
) -> RunSummary:
    started = now_factory()
    if run_id is None:
        run_id = id_factory()
        create_run(conn, run_id, started_at=started, backfill_for=backfill_for)
    elif get_run(conn, run_id) is None:
        create_run(conn, run_id, started_at=started, backfill_for=backfill_for)

    if rate_limiters is None:
        rate_limiters = {
            t.name: RateLimiter(t.rate_limit.requests_per_minute) for t in config.targets
        }
    pricing = {t.name: t.pricing for t in config.targets}

    questions = active_approved(conn)

    def _ev(x):
        return x.value if hasattr(x, "value") else x

    if persona is not None:
        questions = [q for q in questions if q.persona.value == _ev(persona)]
    if therapeutic_area is not None:
        questions = [q for q in questions if q.therapeutic_area == therapeutic_area]
    if brand_focus is not None:
        questions = [q for q in questions if q.brand_focus == brand_focus]
    if domain is not None:
        questions = [q for q in questions if q.domain.value == _ev(domain)]

    done = completed_keys(conn, run_id)
    samples = max(1, config.settings.samples_per_question)

    cap = config.settings.max_tokens_per_run
    budget_exceeded = False

    by_status = {s: 0 for s in _STATUSES}
    questions_attempted = 0
    responses_captured = 0
    failure_count = 0
    total_tokens = 0
    est_cost = 0.0

    pool = ThreadPoolExecutor(max_workers=max_workers or max(1, len(adapters)))
    run_status = "COMPLETED"
    try:
        for question in questions:
            if cap is not None and total_tokens >= cap:
                budget_exceeded = True
                run_status = "BUDGET_EXCEEDED"
                break
            system_prompt = resolve_system_prompt(question.persona, config.settings)
            futures = {}
            for adapter in adapters:
                for sample_index in range(samples):
                    if (question.question_id, adapter.name, sample_index) in done:
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
                    ] = (adapter, sample_index)

            if not futures:
                continue
            questions_attempted += 1

            for fut in as_completed(futures):
                adapter, sample_index = futures[fut]
                llm_resp = fut.result()
                now = now_factory()
                response = build_response(
                    run_id=run_id,
                    question=question,
                    adapter=adapter,
                    llm_response=llm_resp,
                    now=now,
                    response_id=id_factory(),
                    system_prompt=system_prompt,
                    sample_index=sample_index,
                )
                save_response(conn, response)
                if llm_resp.citations:
                    save_citations(
                        conn,
                        response_id=response.response_id,
                        citations=llm_resp.citations,
                        now=now,
                        id_factory=id_factory,
                    )
                record_event(
                    conn,
                    event_type="LLM_RESPONSE",
                    role="TARGET",
                    question_id=question.question_id,
                    llm_target=adapter.name,
                    detail=llm_resp.status,
                )
                if llm_resp.actual_model and llm_resp.actual_model != adapter.model_version:
                    record_event(
                        conn,
                        event_type="MODEL_DRIFT",
                        role="TARGET",
                        llm_target=adapter.name,
                        detail=f"configured={adapter.model_version} actual={llm_resp.actual_model}",
                    )
                responses_captured += 1
                by_status[llm_resp.status] += 1
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
    except Exception:
        run_status = "FAILED"
        raise
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
            status=run_status,
        )
    return RunSummary(
        run_id=run_id,
        questions_attempted=questions_attempted,
        responses_captured=responses_captured,
        by_status=by_status,
        failure_count=failure_count,
        total_tokens=total_tokens,
        est_cost=est_cost,
        backfill_for=get_run(conn, run_id).backfill_for,
        budget_exceeded=budget_exceeded,
        token_budget=cap,
    )
