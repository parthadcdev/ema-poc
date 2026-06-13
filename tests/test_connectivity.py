from ema_poc.adapters.base import LLMResponse
from ema_poc.connectivity import TargetStatus, check_targets


class _OK:
    name = "GPT-4o"

    def query(self, system_prompt, question_text):
        return LLMResponse("pong", "stop", "SUCCESS")


class _Blocked:
    name = "Gemini"

    def query(self, system_prompt, question_text):
        return LLMResponse("", "blocked", "BLOCKED")


class _Down:
    name = "Claude"

    def query(self, system_prompt, question_text):
        raise RuntimeError("connection refused")


def test_check_targets_reports_status_per_adapter():
    statuses = check_targets([_OK(), _Blocked(), _Down()])
    by_name = {s.name: s for s in statuses}
    assert by_name["GPT-4o"].ok is True
    assert by_name["Gemini"].ok is True   # got a response (BLOCKED) -> reachable
    assert by_name["Claude"].ok is False  # raised -> unreachable
    assert "connection refused" in by_name["Claude"].detail
    assert isinstance(statuses[0], TargetStatus)
