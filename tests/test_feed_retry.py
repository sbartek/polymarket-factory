"""Tests for Gamma API retry logic in feed.py."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
import requests

from factory.feed import fetch_top


class TestFetchTopRetry:
    def test_succeeds_on_first_try(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"slug": "test"}]
        mock_resp.raise_for_status = MagicMock()

        with patch("factory.feed.requests.get", return_value=mock_resp):
            result = fetch_top(limit=10, retries=3)
        assert result == [{"slug": "test"}]

    def test_retries_on_failure_then_succeeds(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"slug": "test"}]
        mock_resp.raise_for_status = MagicMock()

        with patch("factory.feed.requests.get", side_effect=[
            requests.ConnectionError("timeout"),
            mock_resp,
        ]), patch("factory.feed.time.sleep"):
            result = fetch_top(limit=10, retries=3)
        assert result == [{"slug": "test"}]

    def test_raises_after_all_retries_exhausted(self):
        with patch("factory.feed.requests.get", side_effect=requests.ConnectionError("down")), \
             patch("factory.feed.time.sleep"):
            with pytest.raises(requests.ConnectionError):
                fetch_top(limit=10, retries=2)

    def test_retries_on_http_error(self):
        bad_resp = MagicMock()
        bad_resp.raise_for_status.side_effect = requests.HTTPError("500")

        good_resp = MagicMock()
        good_resp.json.return_value = []
        good_resp.raise_for_status = MagicMock()

        with patch("factory.feed.requests.get", side_effect=[bad_resp, good_resp]), \
             patch("factory.feed.time.sleep"):
            result = fetch_top(limit=10, retries=2)
        assert result == []
