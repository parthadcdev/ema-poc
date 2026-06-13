"""Probe each configured LLM target for reachability (FR-209 dry-run, NF-009
health-check). A probe that returns ANY response means the target is reachable;
an exception means it is not. Does not write to the repository."""

from __future__ import annotations

from dataclasses import dataclass

_PROBE_SYSTEM = "You are a connectivity probe. Reply with a single short word."
_PROBE_QUESTION = "ping"


@dataclass
class TargetStatus:
    name: str
    ok: bool
    detail: str


def check_targets(adapters) -> list[TargetStatus]:
    statuses: list[TargetStatus] = []
    for adapter in adapters:
        try:
            resp = adapter.query(_PROBE_SYSTEM, _PROBE_QUESTION)
            statuses.append(TargetStatus(adapter.name, True, resp.status))
        except Exception as exc:  # transport / auth failure -> unreachable
            statuses.append(TargetStatus(adapter.name, False, f"error: {exc}"))
    return statuses
