"""Tests for notification delivery reporting."""
from __future__ import annotations

from unittest.mock import Mock, patch

from factory.notify import _send_with_retry, configured_channels, send_notification


class TestConfiguredChannels:
    def test_reports_missing_channels(self):
        with patch.dict("factory.notify.os.environ", {}, clear=True):
            cfg = configured_channels()
        assert cfg["whatsapp"]["configured"] is False
        assert cfg["slack"]["configured"] is False

    def test_reports_present_channels(self):
        with patch.dict(
            "factory.notify.os.environ",
            {"WHATSAPP_GROUP_ID": "group-1", "SLACK_WEBHOOK_URL": "https://example.test/hook"},
            clear=True,
        ):
            cfg = configured_channels()
        assert cfg["whatsapp"]["configured"] is True
        assert cfg["slack"]["configured"] is True


class TestSendNotification:
    def test_returns_per_channel_report(self):
        with patch("factory.notify.send_whatsapp", side_effect=[False, True]) as whatsapp_send, \
             patch("factory.notify.send_slack", return_value=False) as slack_send, \
             patch("factory.notify.time.sleep") as sleep, \
             patch("factory.notify.configured_channels", return_value={
                 "whatsapp": {"configured": True, "target": "group-1"},
                 "slack": {"configured": True, "target": "webhook"},
             }):
            report = send_notification("hello")

        assert report["any_sent"] is True
        assert report["channels"]["whatsapp"]["sent"] is True
        assert report["channels"]["whatsapp"]["attempts"] == 2
        assert report["channels"]["slack"]["sent"] is False
        assert report["channels"]["slack"]["attempts"] == 3
        assert report["configured"]["slack"]["configured"] is True
        assert whatsapp_send.call_count == 2
        assert slack_send.call_count == 3
        assert sleep.call_count == 3

    def test_returns_false_when_nothing_sends(self):
        with patch("factory.notify.send_whatsapp", return_value=False), \
             patch("factory.notify.send_slack", return_value=False), \
             patch("factory.notify.time.sleep"), \
             patch("factory.notify.configured_channels", return_value={
                 "whatsapp": {"configured": False, "target": None},
                 "slack": {"configured": False, "target": None},
             }):
            report = send_notification("hello")

        assert report["any_sent"] is False
        assert report["channels"]["whatsapp"]["sent"] is False
        assert report["channels"]["slack"]["sent"] is False
        assert report["channels"]["whatsapp"]["attempts"] == 0
        assert report["channels"]["slack"]["attempts"] == 0


class TestSendWithRetry:
    def test_retries_until_success(self):
        sender = Mock(side_effect=[False, False, True])
        with patch("factory.notify.time.sleep") as sleep:
            report = _send_with_retry("slack", sender, "hello", configured=True)

        assert report == {"sent": True, "attempts": 3}
        assert sender.call_count == 3
        sleep.assert_any_call(1.0)
        sleep.assert_any_call(2.0)

    def test_stops_after_max_attempts(self):
        with patch("factory.notify.send_slack", return_value=False) as sender, \
             patch("factory.notify.time.sleep") as sleep:
            report = _send_with_retry("slack", sender, "hello", configured=True)

        assert report == {"sent": False, "attempts": 3}
        assert sender.call_count == 3
        assert sleep.call_count == 2
