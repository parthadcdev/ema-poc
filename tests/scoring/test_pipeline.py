from ema_poc.config import AppConfig, BrandConfig, Settings
from ema_poc.db import connect, init_schema
from ema_poc.models import Response
from ema_poc.repositories.alerts import list_alerts
from ema_poc.repositories.responses import query_responses, save_response
from ema_poc.repositories.runs import create_run
from ema_poc.repositories.scores import latest_score
from ema_poc.scoring.pipeline import score_pending
from ema_poc.scoring.scorer import ScoreResult

NOW = "2026-06-13T02:00:00+00:00"


def _config():
    return AppConfig(
        settings=Settings(scoring_model="claude-opus-4-8"),
        brands=BrandConfig(abbvie_brands=["Skyrizi"], competitor_brands=["Humira"]),
        targets=[],
    )


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=NOW)
    return conn


def _resp(conn, rid, text, *, status="SUCCESS", brand="Skyrizi"):
    save_response(conn, Response(
        response_id=rid, run_id="r1", timestamp_utc=NOW, llm_name="GPT-4o",
        llm_model_version="m", persona="Provider", question_id="Q1",
        question_text="q", brand_focus=brand, domain="Safety", response_text=text,
        response_tokens=1, finish_reason="stop", status=status, created_at=NOW,
    ))


def _ids():
    n = {"i": 0}

    def f():
        n["i"] += 1
        return f"id-{n['i']}"

    return f


def _fake_scorer(scores_by_text):
    def scorer(client, *, response_text, brand_focus, abbvie_brands,
               competitor_brands, model="claude-opus-4-8"):
        return scores_by_text[response_text]

    return scorer


def test_score_pending_scores_persists_alerts_and_denormalizes(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "ok", "X is first-line and excellent.")
    _resp(conn, "bad", "X is not recommended; use Humira.")
    _resp(conn, "skipme", "failed text", status="FAILED")  # non-success: not scored

    scorer = _fake_scorer({
        "X is first-line and excellent.": ScoreResult(
            sentiment_score=0.8, competitive_position="FIRST_LINE_RECOMMENDED",
            brand_mentions=["Skyrizi"], key_claims=["effective"], scoring_rationale="positive",
            confidence_level="ASSERTIVE", citation_quality="NONE",
        ),
        "X is not recommended; use Humira.": ScoreResult(
            sentiment_score=-0.6, competitive_position="NOT_RECOMMENDED",
            brand_mentions=["Skyrizi", "Humira"], key_claims=["avoid"], scoring_rationale="negative",
            confidence_level="HEDGED", citation_quality="LOW",
        ),
    })

    summary = score_pending(
        conn, client=object(), config=_config(), scorer=scorer,
        id_factory=_ids(), now_factory=lambda: NOW,
    )
    assert summary.scored == 2
    assert summary.alerts_raised == 1  # only the negative one

    assert latest_score(conn, "ok").sentiment_score == 0.8
    assert latest_score(conn, "bad").competitive_position.value == "NOT_RECOMMENDED"
    assert latest_score(conn, "skipme") is None  # FAILED not scored

    alerted = [r.response_id for r in query_responses(conn, alert_triggered=True)]
    assert alerted == ["bad"]
    neg = [r.response_id for r in query_responses(conn, sentiment_max=-0.3)]
    assert neg == ["bad"]

    alerts = list_alerts(conn)
    assert len(alerts) == 1
    assert alerts[0].reason == "SENTIMENT_BELOW_THRESHOLD"

    conn.close()


def test_score_pending_is_idempotent_on_second_run(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "ok", "neutral text")
    scorer = _fake_scorer({"neutral text": ScoreResult(
        sentiment_score=0.1, competitive_position="AMONG_OPTIONS",
        brand_mentions=[], key_claims=[], scoring_rationale="r",
        confidence_level="MIXED", citation_quality="NONE",
    )})
    cfg = _config()
    s1 = score_pending(conn, client=object(), config=cfg, scorer=scorer,
                       id_factory=_ids(), now_factory=lambda: NOW)
    s2 = score_pending(conn, client=object(), config=cfg, scorer=scorer,
                       id_factory=_ids(), now_factory=lambda: NOW)
    assert s1.scored == 1
    assert s2.scored == 0  # already scored -> nothing pending
    conn.close()


def test_score_pending_propagates_new_dimensions(tmp_path):
    """pipeline must carry confidence_level + citation_quality from scorer into persisted Score."""
    conn = _conn(tmp_path)
    _resp(conn, "resp-a", "Therapy may help some patients.")

    scorer = _fake_scorer({
        "Therapy may help some patients.": ScoreResult(
            sentiment_score=0.2, competitive_position="AMONG_OPTIONS",
            brand_mentions=["Skyrizi"], key_claims=["may help"],
            scoring_rationale="hedged",
            confidence_level="HEDGED", citation_quality="LOW",
        ),
    })

    score_pending(
        conn, client=object(), config=_config(), scorer=scorer,
        id_factory=_ids(), now_factory=lambda: NOW,
    )

    persisted = latest_score(conn, "resp-a")
    assert persisted.confidence_level == "HEDGED"
    assert persisted.citation_quality == "LOW"
    conn.close()
