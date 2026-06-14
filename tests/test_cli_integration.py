"""Drive the CLI end-to-end against a real temp DB with fake adapters/scorer:
import questions -> run -> score, asserting persisted responses, scores, and
that the run command reports a summary."""

from ema_poc.adapters.base import LLMResponse
from ema_poc.agent.runner import run as _runner_run
from ema_poc.cli import Deps, main
from ema_poc.config import AppConfig, BrandConfig, Settings
from ema_poc.connectivity import check_targets
from ema_poc.db import connect, init_schema
from ema_poc.repositories.questions import approve_question, import_questions_csv as _import_csv, list_questions
from ema_poc.repositories.responses import query_responses
from ema_poc.repositories.scores import latest_score
from ema_poc.scoring.pipeline import score_pending
from ema_poc.scoring.scorer import ScoreResult


class _Adapter:
    model_version = "m"

    def __init__(self, name):
        self.name = name

    def query(self, system_prompt, question_text):
        return LLMResponse("Skyrizi is first-line.", "stop", "SUCCESS",
                           prompt_tokens=10, completion_tokens=20)


CSV = (
    "question_id,question_text,persona,domain,therapeutic_area,brand_focus\n"
    "Q1,Is Skyrizi first-line?,Provider,Comparative,Immunology,Skyrizi\n"
)


def _config():
    return AppConfig(
        settings=Settings(db_path="unused", system_prompts={"default": "ctx"},
                          scoring_model="claude-opus-4-8"),
        brands=BrandConfig(abbvie_brands=["Skyrizi"], competitor_brands=["Humira"]),
        targets=[],
    )


def _fake_scorer(client, *, response_text, **kw):
    return ScoreResult(
        sentiment_score=0.6, competitive_position="FIRST_LINE_RECOMMENDED",
        brand_mentions=["Skyrizi"], key_claims=["effective"], scoring_rationale="r",
        confidence_level="ASSERTIVE", citation_quality="NONE",
    )


def test_cli_import_run_score_end_to_end(tmp_path):
    db_path = str(tmp_path / "ema.sqlite")
    conn = connect(db_path)
    init_schema(conn)
    out = []

    config = _config()

    def _score(c, *, client, config):
        return score_pending(c, client=client, config=config, scorer=_fake_scorer)

    deps = Deps(
        load_config=lambda d: config,
        connect=lambda p: conn,           # reuse the one temp connection
        init_schema=lambda c: None,        # already initialized
        validate_credentials=lambda config, env: None,
        build_adapters=lambda config, env: [_Adapter("GPT-4o")],
        make_scoring_client=lambda env: object(),
        run=_runner_run,
        score_pending=_score,
        check_targets=check_targets,
        import_csv=_import_csv,
        import_excel=lambda conn, path: 0,
        env={"ANTHROPIC_API_KEY": "k"},
        out=out.append,
    )

    # 1. import a question
    csv_path = tmp_path / "q.csv"
    csv_path.write_text(CSV)
    assert main(["import-questions", str(csv_path)], deps=deps) == 0
    assert [q.question_id for q in list_questions(conn)] == ["Q1"]

    # approve it so the runner will dispatch it
    approve_question(conn, "Q1", approver_name="Dr. A",
                     now="2026-06-13T00:00:00+00:00")

    # 2. run + score in one command
    assert main(["run", "--score"], deps=deps) == 0
    assert any("Run " in line for line in out)

    # response persisted and scored
    responses = query_responses(conn)
    assert len(responses) == 1
    assert latest_score(conn, responses[0].response_id).sentiment_score == 0.6

    conn.close()
