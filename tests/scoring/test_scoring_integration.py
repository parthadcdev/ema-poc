"""End-to-end: a run's responses (positive / negative / blocked) flow through
the scoring pass against a fake Claude scorer, producing versioned scores,
denormalized response columns, and alerts; re-scoring adds a new version."""

from ema_poc.config import AppConfig, BrandConfig, Settings
from ema_poc.db import connect, init_schema
from ema_poc.models import Response, Score
from ema_poc.repositories.alerts import list_alerts
from ema_poc.repositories.responses import query_responses, save_response
from ema_poc.repositories.runs import create_run
from ema_poc.repositories.scores import latest_score, next_score_version, save_score
from ema_poc.scoring.pipeline import score_pending
from ema_poc.scoring.scorer import ScoreResult

NOW = "2026-06-13T02:00:00+00:00"


def _config():
    return AppConfig(
        settings=Settings(scoring_model="claude-opus-4-8"),
        brands=BrandConfig(abbvie_brands=["Skyrizi"], competitor_brands=["Humira"]),
        targets=[],
    )


def _ids():
    n = {"i": 0}

    def f():
        n["i"] += 1
        return f"id-{n['i']}"

    return f


def _resp(conn, rid, text, status="SUCCESS"):
    save_response(conn, Response(
        response_id=rid, run_id="r1", timestamp_utc=NOW, llm_name="GPT-4o",
        llm_model_version="m", persona="Provider", question_id="Q1",
        question_text="q", brand_focus="Skyrizi", domain="Safety",
        response_text=text, response_tokens=1, finish_reason="stop",
        status=status, created_at=NOW,
    ))


def test_scoring_pass_end_to_end_with_rescore(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=NOW)
    _resp(conn, "pos", "Skyrizi is first-line and well tolerated.")
    _resp(conn, "neg", "Skyrizi is not recommended.")
    _resp(conn, "blk", "", status="BLOCKED")  # not SUCCESS -> never scored

    scores = {
        "Skyrizi is first-line and well tolerated.": ScoreResult(
            sentiment_score=0.7, competitive_position="FIRST_LINE_RECOMMENDED",
            brand_mentions=["Skyrizi"], key_claims=["tolerated"], scoring_rationale="pos",
        ),
        "Skyrizi is not recommended.": ScoreResult(
            sentiment_score=-0.6, competitive_position="NOT_RECOMMENDED",
            brand_mentions=["Skyrizi"], key_claims=["avoid"], scoring_rationale="neg",
        ),
    }

    def scorer(client, *, response_text, **kw):
        return scores[response_text]

    summary = score_pending(conn, client=object(), config=_config(), scorer=scorer,
                            id_factory=_ids(), now_factory=lambda: NOW)
    assert summary.scored == 2
    assert summary.alerts_raised == 1

    assert {r.response_id for r in query_responses(conn, alert_triggered=True)} == {"neg"}
    positives = [r.response_id for r in query_responses(conn, sentiment_min=0.5)]
    assert positives == ["pos"]
    assert latest_score(conn, "blk") is None

    alerts = list_alerts(conn)
    assert len(alerts) == 1
    assert alerts[0].reason in {"SENTIMENT_BELOW_THRESHOLD", "COMPETITIVE_POSITION_NOT_RECOMMENDED"}

    # re-score "neg": a corrected score -> new version (FR-407), original preserved
    v = next_score_version(conn, "neg")
    save_score(conn, Score(
        score_id="rescore-1", response_id="neg", version=v,
        sentiment_score=0.0, competitive_position="AMONG_OPTIONS",
        brand_mentions=["Skyrizi"], key_claims=["reassessed"],
        scoring_rationale="fix", scoring_model="claude-opus-4-8", created_at=NOW,
    ))
    assert latest_score(conn, "neg").version == v
    assert latest_score(conn, "neg").sentiment_score == 0.0  # newest version wins
    assert v >= 2  # original version 1 preserved

    conn.close()
