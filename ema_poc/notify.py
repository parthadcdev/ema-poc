"""Prototype run-completion notification (FR-505).

POSTs a JSON summary to a configured webhook. The poster is injectable so tests
don't hit the network; the default uses stdlib urllib."""

from __future__ import annotations


def _default_post(url: str, payload: dict) -> int:
    import json
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (configured URL)
        return resp.status


def send_summary(url: str, payload: dict, *, poster=_default_post) -> int:
    """POST `payload` to `url`, returning the HTTP status. Caller decides whether
    to send (only when a webhook is configured)."""
    return poster(url, payload)
