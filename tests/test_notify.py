from ema_poc.config import Settings
from ema_poc.notify import send_summary


def test_send_summary_posts_payload_via_injected_poster():
    captured = {}

    def poster(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return 200

    status = send_summary("https://hook.example/notify",
                          {"run_id": "run-1", "alerts": 3}, poster=poster)
    assert status == 200
    assert captured["url"] == "https://hook.example/notify"
    assert captured["payload"]["run_id"] == "run-1"


def test_settings_notify_webhook_defaults_none():
    assert Settings().notify_webhook is None
