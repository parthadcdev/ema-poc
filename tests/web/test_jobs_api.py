from fastapi.testclient import TestClient

from ema_poc.web.app import create_app, WebDeps
from ema_poc.config import AppConfig, Settings, BrandConfig, LLMTargetConfig
from ema_poc.adapters.base import LLMResponse


class FakeAdapter:
    def __init__(self, name="GPT-4o"):
        self.name = name; self.model_version = name + "-v"; self.grounded = False
    def query(self, sp, q):
        return LLMResponse(text=f"{self.name} ans", finish_reason="stop",
                           status="SUCCESS", completion_tokens=5)


class FakeScore:
    sentiment_score = 0.5; competitive_position = "AMONG_OPTIONS"; scoring_rationale = "r"
    brand_mentions = None


def _deps(tmp_path, env=None):
    cfg = AppConfig(settings=Settings(system_prompts={"default": "x"}),
                    brands=BrandConfig(),
                    targets=[LLMTargetConfig(
                        name="GPT-4o", adapter="openai", model_version="gpt-4o",
                        api_key_env="OPENAI_API_KEY",
                        pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
                        rate_limit={"requests_per_minute": 1, "tokens_per_minute": 1})])
    d = WebDeps(config=cfg, build_adapters_for=lambda names: [FakeAdapter()],
                scoring_client=object(), scorer=lambda *a, **k: FakeScore(),
                db_path=str(tmp_path / "w.sqlite"), env=env)
    d.job_submit_fn = lambda fn, *a: fn(*a)   # run inline for deterministic tests
    return d


def test_ask_submit_then_list_then_detail(tmp_path):
    client = TestClient(create_app(_deps(tmp_path)))
    r = client.post("/api/ask", json={"question": "What treats psoriasis?",
                                       "persona": "Provider", "brand_focus": "Skyrizi"})
    assert r.status_code == 202
    qid = r.json()["query_id"]

    lst = client.get("/api/queries").json()["queries"]
    assert any(q["query_id"] == qid and q["status"] == "DONE" for q in lst)

    detail = client.get(f"/api/queries/{qid}").json()
    assert detail["query"]["status"] == "DONE"
    assert len(detail["responses"]) == 1
    assert detail["responses"][0]["llm_name"] == "GPT-4o"
    assert detail["responses"][0]["sentiment_score"] == 0.5


def test_ask_requires_question(tmp_path):
    client = TestClient(create_app(_deps(tmp_path)))
    assert client.post("/api/ask", json={"question": "  "}).status_code == 400


def test_unknown_query_is_404(tmp_path):
    client = TestClient(create_app(_deps(tmp_path)))
    assert client.get("/api/queries/nope").status_code == 404


def test_ask_rate_limited(tmp_path):
    client = TestClient(create_app(_deps(tmp_path, env={"PLAYGROUND_MAX_QUERIES_PER_HOUR": "1"})))
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 202
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 429


def test_startup_sweeps_stale_running(tmp_path):
    # Pre-seed a RUNNING row, then build the app — startup sweep marks it FAILED.
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories import sandbox as S
    p = str(tmp_path / "w.sqlite")
    c = connect(p); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None, now="t0",
                         status="RUNNING", target_count=1, started_at="t0"); c.close()
    d = _deps(tmp_path); d.db_path = p
    create_app(d)
    c2 = connect(p); init_schema(c2)
    assert S.get_query(c2, qid).status == "FAILED"


def test_auth_enforced_on_jobs_routes(tmp_path):
    d = _deps(tmp_path, env={"APP_PASSWORD": "pw", "APP_USER": "abbvie"})
    client = TestClient(create_app(d))
    assert client.get("/api/queries").status_code == 401
    assert client.get("/api/queries", auth=("abbvie", "pw")).status_code == 200


# ---------------------------------------------------------------------------
# Cache-control: dynamic, auth-gated pages must not be cached by the browser
# (a stale/partial cached /dashboard renders empty dropdowns + analytics).
# ---------------------------------------------------------------------------

def test_dashboard_response_is_no_store(tmp_path):
    client = TestClient(create_app(_deps(tmp_path)))
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


def test_index_response_is_no_store(tmp_path):
    client = TestClient(create_app(_deps(tmp_path)))
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


def test_api_queries_response_is_no_store(tmp_path):
    client = TestClient(create_app(_deps(tmp_path)))
    r = client.get("/api/queries")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


def test_query_detail_includes_scoring_error(tmp_path):
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories import sandbox as S
    d = _deps(tmp_path)
    c = connect(d.db_path); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None, now="t0",
                         status="DONE", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="a", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1")
    S.set_response_scoring_error(c, sandbox_response_id=rid, error="credit balance too low")
    c.close()
    client = TestClient(create_app(d))
    detail = client.get(f"/api/queries/{qid}").json()
    assert detail["responses"][0]["scoring_error"] == "credit balance too low"


def test_rescore_endpoint_scores_response(tmp_path):
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories import sandbox as S
    d = _deps(tmp_path)
    c = connect(d.db_path); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None, now="t0",
                         status="DONE", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="ans", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1")
    S.set_response_scoring_error(c, sandbox_response_id=rid, error="old"); c.close()
    client = TestClient(create_app(d))
    r = client.post(f"/api/responses/{rid}/rescore")
    assert r.status_code == 200
    body = r.json()
    assert body["sentiment_score"] == 0.5 and body["scoring_error"] is None
    c2 = connect(d.db_path); init_schema(c2)
    assert S.get_sandbox_response(c2, rid).sentiment_score == 0.5


def test_rescore_endpoint_reports_scoring_error(tmp_path):
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories import sandbox as S
    d = _deps(tmp_path)
    d.scorer = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("credit balance too low"))
    c = connect(d.db_path); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None, now="t0",
                         status="DONE", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="ans", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1"); c.close()
    client = TestClient(create_app(d))
    r = client.post(f"/api/responses/{rid}/rescore")
    assert r.status_code == 200
    assert "credit balance too low" in r.json()["scoring_error"]


def test_rescore_endpoint_unknown_id_404(tmp_path):
    client = TestClient(create_app(_deps(tmp_path)))
    assert client.post("/api/responses/nope/rescore").status_code == 404


def test_rescore_endpoint_rate_limited(tmp_path):
    from ema_poc.db import connect, init_schema
    from ema_poc.repositories import sandbox as S
    d = _deps(tmp_path, env={"PLAYGROUND_MAX_QUERIES_PER_HOUR": "1"})
    c = connect(d.db_path); init_schema(c)
    qid = S.create_query(c, question_text="q", persona=None, brand_focus=None, now="t0",
                         status="DONE", target_count=1, started_at="t0")
    rid = S.save_response(c, query_id=qid, llm_name="A", llm_model_version="v",
                          grounded=False, answer_text="ans", response_tokens=1,
                          finish_reason="stop", status="SUCCESS", now="t1"); c.close()
    client = TestClient(create_app(d))
    assert client.post(f"/api/responses/{rid}/rescore").status_code == 200
    assert client.post(f"/api/responses/{rid}/rescore").status_code == 429
