from ema_poc.db import connect, init_schema
from ema_poc.playground.jobs import JobManager
from ema_poc.repositories import sandbox as S
from ema_poc.config import AppConfig, Settings, BrandConfig
from ema_poc.adapters.base import LLMResponse


class FakeAdapter:
    def __init__(self, name="A", boom=False):
        self.name = name; self.model_version = "v"; self.grounded = False; self._boom = boom
    def query(self, sp, q):
        if self._boom:
            raise RuntimeError("adapter down")
        return LLMResponse(text="ans", finish_reason="stop", status="SUCCESS",
                           completion_tokens=3)


class FakeScore:
    sentiment_score = 0.5; competitive_position = "AMONG_OPTIONS"; scoring_rationale = "r"


def _cfg():
    return AppConfig(
        settings=Settings(system_prompts={"default": "x"}, max_retries=0, backoff_seconds=[0]),
        brands=BrandConfig(), targets=[])


_INLINE = lambda fn, *a: fn(*a)   # run the job synchronously in tests


def _mgr(tmp_path, adapters):
    return JobManager(
        db_path=str(tmp_path / "j.sqlite"),
        build_adapters_for=lambda names: adapters,
        scoring_client=object(), scorer=lambda *a, **k: FakeScore(), config=_cfg(),
        id_factory=lambda: __import__("uuid").uuid4().hex,
        now_factory=lambda: "t", max_concurrent=2, submit_fn=_INLINE)


def test_submit_runs_to_done_and_persists(tmp_path):
    mgr = _mgr(tmp_path, [FakeAdapter("A")])
    qid = mgr.submit(question="q", persona=None, brand_focus=None, selected_targets=None)
    c = connect(str(tmp_path / "j.sqlite")); init_schema(c)
    assert S.get_query(c, qid).status == "DONE"
    assert S.get_query(c, qid).target_count == 1
    assert len(S.list_query_responses(c, qid)) == 1
    c.close()


def test_adapter_error_still_completes_job(tmp_path):
    # A per-target adapter failure surfaces as an error event inside run_playground,
    # not a crash — the job still completes DONE.
    mgr = _mgr(tmp_path, [FakeAdapter("A", boom=True)])
    qid = mgr.submit(question="q", persona=None, brand_focus=None, selected_targets=None)
    c = connect(str(tmp_path / "j.sqlite")); init_schema(c)
    assert S.get_query(c, qid).status == "DONE"
    c.close()


def test_job_marked_failed_when_runner_raises(tmp_path, monkeypatch):
    # A whole-job failure (run_playground itself raises) marks the query FAILED.
    import ema_poc.playground.jobs as jobs
    def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(jobs, "run_playground", boom)
    mgr = _mgr(tmp_path, [FakeAdapter("A")])
    qid = mgr.submit(question="q", persona=None, brand_focus=None, selected_targets=None)
    c = connect(str(tmp_path / "j.sqlite")); init_schema(c)
    q = S.get_query(c, qid)
    assert q.status == "FAILED" and "kaboom" in (q.error_text or "")
    c.close()
