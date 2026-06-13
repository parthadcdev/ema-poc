from ema_poc.adapters.base import LLMResponse
from ema_poc.agent.executor import execute


class _Adapter:
    """Replays a list of behaviors: each is an LLMResponse to return or an
    Exception to raise on that call."""

    name = "X"
    model_version = "m"

    def __init__(self, behaviors):
        self._behaviors = behaviors
        self.calls = 0

    def query(self, system_prompt, question_text):
        self.calls += 1
        b = self._behaviors[min(self.calls - 1, len(self._behaviors) - 1)]
        if isinstance(b, Exception):
            raise b
        return b


def test_success_on_first_attempt():
    a = _Adapter([LLMResponse("ok", "stop", "SUCCESS")])
    r = execute(a, "s", "q", max_retries=3, backoff=[2, 4, 8], sleep=lambda d: None)
    assert r.status == "SUCCESS"
    assert a.calls == 1


def test_retries_then_succeeds():
    sleeps = []
    a = _Adapter([RuntimeError("boom"), LLMResponse("ok", "stop", "SUCCESS")])
    r = execute(a, "s", "q", max_retries=3, backoff=[2, 4, 8], sleep=sleeps.append)
    assert r.status == "SUCCESS"
    assert a.calls == 2
    assert sleeps == [2]  # one backoff before the retry


def test_exhausts_retries_then_returns_failed():
    sleeps = []
    a = _Adapter([RuntimeError("down")])
    r = execute(a, "s", "q", max_retries=3, backoff=[2, 4, 8], sleep=sleeps.append)
    assert r.status == "FAILED"
    assert r.finish_reason == "error"
    assert a.calls == 4  # initial + 3 retries
    assert sleeps == [2, 4, 8]
    assert "down" in r.raw["error"]


def test_rate_limiter_acquired_once_per_attempt():
    acquired = []

    class _RL:
        def acquire(self):
            acquired.append(1)

    a = _Adapter([RuntimeError("x"), LLMResponse("ok", "stop", "SUCCESS")])
    execute(a, "s", "q", max_retries=3, backoff=[2, 4, 8],
            rate_limiter=_RL(), sleep=lambda d: None)
    assert len(acquired) == 2  # acquired before each of the 2 attempts
