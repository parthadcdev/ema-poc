"""Framework-agnostic playground fan-out. Yields JSON-serializable events as
each target completes; persists to the sandbox. Injected adapters + scorer keep
it testable with no network."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict

from ema_poc.agent.executor import execute
from ema_poc.repositories import sandbox as S


def _system_prompt_for(system_prompts, persona) -> str:
    if persona and persona in system_prompts:
        return system_prompts[persona]
    return system_prompts.get("default", "You are a helpful assistant.")


def run_playground(
    conn, *, adapters, scoring_client, scorer, abbvie_brands, competitor_brands,
    system_prompts, question_text, persona, brand_focus, model,
    id_factory, now, max_retries, backoff,
):
    if not adapters:
        yield {"event": "error", "message": "No targets selected."}
        return

    query_id = S.create_query(
        conn, question_text=question_text, persona=persona, brand_focus=brand_focus,
        now=now, id_factory=id_factory,
    )
    yield {"event": "query", "query_id": query_id}

    system_prompt = _system_prompt_for(system_prompts, persona)

    with ThreadPoolExecutor(max_workers=max(1, len(adapters))) as pool:
        futures = {
            pool.submit(
                execute, a, system_prompt, question_text,
                max_retries=max_retries, backoff=backoff,
            ): a
            for a in adapters
        }
        for fut in as_completed(futures):
            adapter = futures[fut]
            try:
                llm_response = fut.result()
            except Exception as exc:
                yield {"event": "error", "llm_name": adapter.name, "message": str(exc)}
                continue

            rid = S.save_response(
                conn, query_id=query_id, llm_name=adapter.name,
                llm_model_version=adapter.model_version,
                grounded=getattr(adapter, "grounded", False),
                answer_text=llm_response.text, response_tokens=llm_response.completion_tokens,
                finish_reason=llm_response.finish_reason, status=llm_response.status,
                now=now, id_factory=id_factory,
            )
            citations = list(llm_response.citations)
            if citations:
                S.save_response_citations(
                    conn, sandbox_response_id=rid, citations=citations,
                    now=now, id_factory=id_factory,
                )

            yield {
                "event": "answer",
                "llm_name": adapter.name,
                "grounded": getattr(adapter, "grounded", False),
                "status": llm_response.status,
                "finish_reason": llm_response.finish_reason,
                "answer_text": llm_response.text,
                "tokens": llm_response.completion_tokens,
                "citations": [asdict(c) for c in citations],
            }

            if llm_response.status == "SUCCESS" and llm_response.text.strip():
                try:
                    result = scorer(
                        scoring_client, response_text=llm_response.text,
                        brand_focus=brand_focus, abbvie_brands=abbvie_brands,
                        competitor_brands=competitor_brands, model=model,
                    )
                    S.set_response_score(
                        conn, sandbox_response_id=rid,
                        sentiment_score=result.sentiment_score,
                        competitive_position=result.competitive_position,
                        scoring_rationale=result.scoring_rationale,
                    )
                    yield {
                        "event": "score",
                        "llm_name": adapter.name,
                        "sentiment_score": result.sentiment_score,
                        "competitive_position": result.competitive_position,
                        "scoring_rationale": result.scoring_rationale,
                    }
                except Exception as exc:
                    yield {"event": "score_error", "llm_name": adapter.name, "message": str(exc)}

    yield {"event": "done"}
