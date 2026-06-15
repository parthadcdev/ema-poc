"""Background runner for playground questions. submit() creates the RUNNING query
row and schedules run_playground on a thread pool; the DB is the source of truth.
The executor is injectable (submit_fn) so tests run inline and deterministically."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from ema_poc.db import connect, init_schema
from ema_poc.playground.service import run_playground
from ema_poc.repositories import sandbox as S


class JobManager:
    def __init__(self, *, db_path, build_adapters_for, scoring_client, scorer, config,
                 id_factory=lambda: uuid4().hex, now_factory, max_concurrent=2,
                 submit_fn=None):
        self.db_path = db_path
        self.build_adapters_for = build_adapters_for
        self.scoring_client = scoring_client
        self.scorer = scorer
        self.config = config
        self.id_factory = id_factory
        self.now_factory = now_factory
        if submit_fn is not None:
            self._submit = submit_fn
        else:
            self._pool = ThreadPoolExecutor(max_workers=max(1, max_concurrent))
            self._submit = lambda fn, *a: self._pool.submit(fn, *a)

    def submit(self, *, question, persona, brand_focus, selected_targets) -> str:
        adapters = self.build_adapters_for(selected_targets)
        now = self.now_factory()
        conn = connect(self.db_path)
        try:
            init_schema(conn)
            query_id = S.create_query(
                conn, question_text=question, persona=persona, brand_focus=brand_focus,
                now=now, id_factory=self.id_factory, status="RUNNING",
                target_count=len(adapters), started_at=now)
        finally:
            conn.close()
        self._submit(self._run, query_id, adapters, question, persona, brand_focus)
        return query_id

    def _run(self, query_id, adapters, question, persona, brand_focus):
        cfg = self.config
        conn = connect(self.db_path)
        try:
            init_schema(conn)
            gen = run_playground(
                conn, query_id=query_id, adapters=adapters,
                scoring_client=self.scoring_client, scorer=self.scorer,
                abbvie_brands=cfg.brands.abbvie_brands,
                competitor_brands=cfg.brands.competitor_brands,
                system_prompts=cfg.settings.system_prompts, question_text=question,
                persona=persona, brand_focus=brand_focus, model=cfg.settings.scoring_model,
                id_factory=self.id_factory, now=self.now_factory(),
                max_retries=cfg.settings.max_retries, backoff=cfg.settings.backoff_seconds)
            for _ in gen:
                pass
            S.mark_query_done(conn, query_id, finished_at=self.now_factory())
        except Exception as exc:  # whole-job failure
            S.mark_query_failed(conn, query_id, finished_at=self.now_factory(),
                                error_text=str(exc))
        finally:
            conn.close()
