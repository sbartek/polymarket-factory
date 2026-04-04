"""Tests for paginated market fetch."""
from unittest.mock import patch, MagicMock

from factory.feed import fetch_top_paginated


def _make_events(start: int, count: int) -> list[dict]:
    return [{"slug": f"event-{i}", "title": f"Event {i}"} for i in range(start, start + count)]


class TestFetchTopPaginated:
    @patch("factory.feed.requests.get")
    def test_fetches_two_pages(self, mock_get):
        page1 = _make_events(0, 100)
        page2 = _make_events(100, 50)
        resp1, resp2 = MagicMock(), MagicMock()
        resp1.json.return_value = page1
        resp2.json.return_value = page2
        mock_get.side_effect = [resp1, resp2]

        result = fetch_top_paginated(total=200, page_size=100)
        assert len(result) == 150
        assert mock_get.call_count == 2

    @patch("factory.feed.requests.get")
    def test_deduplicates_by_slug(self, mock_get):
        page1 = _make_events(0, 3)
        page2 = [{"slug": "event-2", "title": "Dup"}, {"slug": "event-3", "title": "New"}]
        resp1, resp2 = MagicMock(), MagicMock()
        resp1.json.return_value = page1
        resp2.json.return_value = page2
        mock_get.side_effect = [resp1, resp2]

        result = fetch_top_paginated(total=10, page_size=3)
        slugs = [e["slug"] for e in result]
        assert slugs == ["event-0", "event-1", "event-2", "event-3"]

    @patch("factory.feed.requests.get")
    def test_stops_when_api_returns_fewer_than_page_size(self, mock_get):
        page1 = _make_events(0, 50)  # fewer than page_size=100
        resp = MagicMock()
        resp.json.return_value = page1
        mock_get.return_value = resp

        result = fetch_top_paginated(total=200, page_size=100)
        assert len(result) == 50
        assert mock_get.call_count == 1

    @patch("factory.feed.requests.get")
    def test_continues_on_page_failure_if_have_results(self, mock_get):
        import requests as req
        page1 = _make_events(0, 100)
        resp1 = MagicMock()
        resp1.json.return_value = page1
        mock_get.side_effect = [resp1, req.RequestException("timeout"), req.RequestException("timeout"), req.RequestException("timeout")]

        result = fetch_top_paginated(total=200, page_size=100, retries=3)
        assert len(result) == 100

    @patch("factory.feed.requests.get")
    def test_raises_on_first_page_failure(self, mock_get):
        import requests as req
        mock_get.side_effect = req.RequestException("timeout")

        try:
            fetch_top_paginated(total=100, page_size=100, retries=1)
            assert False, "should have raised"
        except req.RequestException:
            pass
