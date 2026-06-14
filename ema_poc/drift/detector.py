"""Compare each (question, LLM) pair's latest scored response to its frozen v0
baseline and raise a drift alert when the answer has materially changed:
cosine-to-baseline < threshold OR competitive_position changed from baseline."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from ema_poc.drift.embeddings import cosine_similarity, embed_response
from ema_poc.models import Alert
from ema_poc.repositories.alerts import save_alert
from ema_poc.repositories.baselines import list_baselines
from ema_poc.repositories.embeddings import get_embedding
from ema_poc.repositories.responses import get_response, latest_scored_response
from ema_poc.repositories.scores import latest_score


@dataclass
class DriftSummary:
    compared: int
    drifted: int


def _position_value(resp) -> str | None:
    cp = getattr(resp, "competitive_position", None)
    return cp.value if cp is not None else None


def detect_drift(conn, *, client, config, now: str, id_factory=lambda: uuid4().hex) -> DriftSummary:
    model = config.drift.embedding_model
    threshold = config.drift.cosine_threshold
    compared = 0
    drifted = 0
    for b in list_baselines(conn):
        baseline_resp = get_response(conn, b.response_id)
        latest_resp = latest_scored_response(conn, b.question_id, b.llm_name)
        if latest_resp is None or baseline_resp is None:
            continue
        if latest_resp.response_id == b.response_id:
            continue  # nothing newer than the baseline
        compared += 1

        embed_response(conn, baseline_resp, client=client, model=model, now=now)
        embed_response(conn, latest_resp, client=client, model=model, now=now)
        base_vec = get_embedding(conn, b.response_id)
        new_vec = get_embedding(conn, latest_resp.response_id)
        cosine = cosine_similarity(base_vec, new_vec) if base_vec and new_vec else 0.0

        base_pos = _position_value(baseline_resp)
        new_pos = _position_value(latest_resp)
        position_changed = base_pos is not None and new_pos is not None and base_pos != new_pos

        reasons = []
        if cosine < threshold:
            reasons.append(f"DRIFT: cosine {cosine:.2f} < {threshold}")
        if position_changed:
            reasons.append(f"DRIFT: position {base_pos} -> {new_pos}")
        if reasons:
            score = latest_score(conn, latest_resp.response_id)
            if score is None:
                continue  # can't attach an alert without a score
            save_alert(conn, Alert(alert_id=id_factory(), score_id=score.score_id,
                                   reason="; ".join(reasons), created_at=now))
            drifted += 1
    return DriftSummary(compared=compared, drifted=drifted)
