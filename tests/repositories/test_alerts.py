from ema_poc.db import connect, init_schema
from ema_poc.models import Alert
from ema_poc.repositories.alerts import list_alerts, save_alert

NOW = "2026-06-13T02:00:00+00:00"


def _conn(tmp_path):
    conn = connect(str(tmp_path / "t.sqlite"))
    init_schema(conn)
    return conn


def test_save_and_list_alerts(tmp_path):
    conn = _conn(tmp_path)
    save_alert(conn, Alert(alert_id="al-1", score_id="s-1",
                           reason="SENTIMENT_BELOW_THRESHOLD", created_at=NOW))
    save_alert(conn, Alert(alert_id="al-2", score_id="s-2",
                           reason="COMPETITIVE_POSITION_NOT_RECOMMENDED", created_at=NOW))
    alerts = list_alerts(conn)
    assert [a.alert_id for a in alerts] == ["al-1", "al-2"]
    assert alerts[0].reason == "SENTIMENT_BELOW_THRESHOLD"
    conn.close()
