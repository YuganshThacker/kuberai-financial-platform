from unittest.mock import patch, MagicMock
from ingestion.news.rss_poller import poll_feeds, NewsItem, RSS_FEEDS

def test_rss_feeds_has_required_sources():
    sources = {f["source"] for f in RSS_FEEDS}
    assert "moneycontrol" in sources
    assert "economic_times" in sources
    assert "mint" in sources
    assert "ndtv_profit" in sources
    assert "business_standard" in sources

def test_poll_feeds_returns_news_items():
    mock_entry = MagicMock()
    mock_entry.title = "TCS Q4 profit rises 10%"
    mock_entry.link = "https://economictimes.com/tcs-q4"
    mock_entry.published_parsed = (2026, 5, 15, 10, 0, 0, 0, 0, 0)
    mock_feed = MagicMock()
    mock_feed.entries = [mock_entry]

    with patch("ingestion.news.rss_poller.feedparser.parse", return_value=mock_feed):
        items = poll_feeds(max_per_feed=5)
    assert len(items) >= 1
    assert isinstance(items[0], NewsItem)
    assert items[0].url == "https://economictimes.com/tcs-q4"
