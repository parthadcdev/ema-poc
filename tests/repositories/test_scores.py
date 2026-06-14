from ema_poc.db import connect, init_schema
from ema_poc.models import CompetitivePosition, Response, Score
from ema_poc.repositories.responses import save_response, update_response_scoring
from ema_poc.repositories.runs import create_run
from ema_poc.repositories.scores import (
    latest_score,
    next_score_version,
    save_score,
    unscored_success_responses,
)

NOW = "2026-06-13T02:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    create_run(conn, "r1", started_at=NOW)
    return conn


def _resp(conn, rid, *, status="SUCCESS"):
    save_response(conn, Response(
        response_id=rid, run_id="r1", timestamp_utc=NOW, llm_name="GPT-4o",
        llm_model_version="m", persona="Provider", question_id="Q1",
        question_text="q", domain="Safety", response_text="ans", response_tokens=1,
        finish_reason="stop", status=status, created_at=NOW,
    ))


def _score(rid, version=1, sentiment=0.2):
    return Score(
        score_id=f"{rid}-s{version}", response_id=rid, version=version,
        sentiment_score=sentiment, competitive_position="AMONG_OPTIONS",
        brand_mentions=["Skyrizi", "Humira"], key_claims=["c1", "c2"],
        scoring_rationale="rationale", scoring_model="claude-opus-4-8",
        created_at=NOW,
    )


def test_save_and_latest_score_roundtrips_json_fields(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "resp-1")
    save_score(conn, _score("resp-1", sentiment=-0.5))
    got = latest_score(conn, "resp-1")
    assert got.sentiment_score == -0.5
    assert got.competitive_position is CompetitivePosition.AMONG_OPTIONS
    assert got.brand_mentions == ["Skyrizi", "Humira"]  # JSON round-trip
    assert got.key_claims == ["c1", "c2"]
    assert latest_score(conn, "missing") is None
    conn.close()


def test_versioning_and_next_version(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "resp-1")
    assert next_score_version(conn, "resp-1") == 1
    save_score(conn, _score("resp-1", version=1))
    assert next_score_version(conn, "resp-1") == 2
    save_score(conn, _score("resp-1", version=2, sentiment=0.9))
    assert latest_score(conn, "resp-1").version == 2
    assert latest_score(conn, "resp-1").sentiment_score == 0.9  # latest wins
    conn.close()


def test_unscored_success_responses_excludes_scored_and_non_success(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "a", status="SUCCESS")
    _resp(conn, "b", status="SUCCESS")
    _resp(conn, "c", status="FAILED")  # non-success excluded
    save_score(conn, _score("a"))       # already scored excluded
    ids = [r.response_id for r in unscored_success_responses(conn)]
    assert ids == ["b"]
    conn.close()


def test_update_response_scoring_sets_derived_columns_only(tmp_path):
    conn = _conn(tmp_path)
    _resp(conn, "resp-1")
    update_response_scoring(conn, "resp-1", sentiment_score=-0.7,
                            competitive_position="NOT_RECOMMENDED", alert_triggered=True)
    row = conn.execute(
        "SELECT sentiment_score, competitive_position, alert_triggered, response_text "
        "FROM responses WHERE response_id='resp-1'"
    ).fetchone()
    assert row["sentiment_score"] == -0.7
    assert row["competitive_position"] == "NOT_RECOMMENDED"
    assert row["alert_triggered"] == 1
    assert row["response_text"] == "ans"  # content untouched
    conn.close()


def test_save_and_latest_score_roundtrips_new_dimensions(tmp_path):
    """confidence_level and citation_quality must survive a save/read roundtrip."""
    conn = _conn(tmp_path)
    _resp(conn, "resp-x")
    score = Score(
        score_id="resp-x-s1", response_id="resp-x", version=1,
        sentiment_score=0.7, competitive_position="FIRST_LINE_RECOMMENDED",
        brand_mentions=["Skyrizi"], key_claims=["effective"],
        scoring_rationale="good", scoring_model="claude-opus-4-8",
        confidence_level="ASSERTIVE", citation_quality="HIGH",
        created_at=NOW,
    )
    save_score(conn, score)
    got = latest_score(conn, "resp-x")
    assert got.confidence_level == "ASSERTIVE"
    assert got.citation_quality == "HIGH"
    conn.close()


def test_save_score_with_null_new_dimensions(tmp_path):
    """Scores without confidence/citation (old rows) must read back as None."""
    conn = _conn(tmp_path)
    _resp(conn, "resp-y")
    score = _score("resp-y")  # uses existing helper which omits new fields
    save_score(conn, score)
    got = latest_score(conn, "resp-y")
    assert got.confidence_level is None
    assert got.citation_quality is None
    conn.close()
