"""Tests for notification delivery reporting."""
from __future__ import annotations

from unittest.mock import patch

from factory.notify import configured_channels, send_notification


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
        with patch("factory.notify.send_whatsapp", return_value=True), \
             patch("factory.notify.send_slack", return_value=False), \
             patch("factory.notify.configured_channels", return_value={
                 "whatsapp": {"configured": True, "target": "group-1"},
                 "slack": {"configured": True, "target": "webhook"},
             }):
            report = send_notification("hello")

        assert report["any_sent"] is True
        assert report["channels"]["whatsapp"]["sent"] is True
        assert report["channels"]["slack"]["sent"] is False
        assert report["configured"]["slack"]["configured"] is True

    def test_returns_false_when_nothing_sends(self):
        with patch("factory.notify.send_whatsapp", return_value=False), \
             patch("factory.notify.send_slack", return_value=False), \
             patch("factory.notify.configured_channels", return_value={
                 "whatsapp": {"configured": False, "target": None},
                 "slack": {"configured": False, "target": None},
             }):
            report = send_notification("hello")

        assert report["any_sent"] is False
        assert report["channels"]["whatsapp"]["sent"] is False
        assert report["channels"]["slack"]["sent"] is False
