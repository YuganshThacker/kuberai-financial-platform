from unittest.mock import MagicMock, patch
import respx
import httpx

from ingestion.web_search.url_registry import google_news_rss_url, screener_page_url
from ingestion.web_search.stock_scraper import (
    _domain,
    fetch_and_build_article,
    fetch_rss_entries,
)


# --- url_registry ---

def test_google_news_rss_url_contains_company():
    url = google_news_rss_url("Tata Consultancy Services")
    assert "Tata+Consultancy+Services" in url or "Tata%20Consultancy" in url or "Tata" in url
    assert "news.google.com/rss/search" in url
    assert "IN:en" in url


def test_screener_page_url():
    assert screener_page_url("TCS") == "https://www.screener.in/company/TCS/"


# --- stock_scraper helpers ---

def test_domain_strips_www():
    assert _domain("https://www.economictimes.com/markets/tcs") == "economictimes.com"


def test_domain_handles_bad_url():
    assert _domain("not-a-url") == ""


# --- fetch_rss_entries ---

def _make_mock_entry(link, title, published_parsed=None):
    e = MagicMock()
    e.link = link
    e.title = title
    e.published_parsed = published_parsed
    return e


def test_fetch_rss_entries_returns_entries():
    mock_feed = MagicMock()
    mock_feed.entries = [
        _make_mock_entry("https://et.com/tcs-q4", "TCS Q4 Results"),
        _make_mock_entry("https://mc.com/tcs-buy", "TCS Buy Call"),
    ]
    with patch("ingestion.web_search.stock_scraper.feedparser.parse", return_value=mock_feed):
        entries = fetch_rss_entries("TCS", "Tata Consultancy Services")

    assert len(entries) == 2
    assert entries[0]["url"] == "https://et.com/tcs-q4"
    assert entries[0]["title"] == "TCS Q4 Results"
    assert entries[0]["published_at"] is None


def test_fetch_rss_entries_skips_empty_links():
    mock_feed = MagicMock()
    no_link = MagicMock()
    no_link.link = ""
    no_link.title = "No link"
    no_link.published_parsed = None
    with patch("ingestion.web_search.stock_scraper.feedparser.parse", return_value=mock_feed):
        mock_feed.entries = [no_link]
        entries = fetch_rss_entries("TCS", "Tata Consultancy Services")
    assert entries == []


def test_fetch_rss_entries_handles_parse_error():
    with patch("ingestion.web_search.stock_scraper.feedparser.parse", side_effect=Exception("timeout")):
        entries = fetch_rss_entries("TCS", "Tata Consultancy Services")
    assert entries == []


# --- fetch_and_build_article ---

@respx.mock
def test_fetch_and_build_article_success():
    url = "https://economictimes.com/tcs-results"
    jina_url = f"https://r.jina.ai/{url}"
    long_text = "TCS reported strong Q4 results. " * 20  # >200 chars
    respx.get(jina_url).mock(return_value=httpx.Response(200, text=long_text))

    entry = {"url": url, "title": "TCS Q4", "published_at": "2024-04-15T00:00:00+00:00"}
    result = fetch_and_build_article(entry)

    assert result is not None
    assert result.url == url
    assert result.source_domain == "economictimes.com"
    assert result.title == "TCS Q4"
    assert len(result.text) > 200


@respx.mock
def test_fetch_and_build_article_returns_none_for_short_text():
    url = "https://example.com/stub"
    respx.get(f"https://r.jina.ai/{url}").mock(return_value=httpx.Response(200, text="Too short"))

    result = fetch_and_build_article({"url": url, "title": "stub", "published_at": None})
    assert result is None


# --- handler integration (no real network) ---

def test_lambda_handler_processes_and_returns_counts():
    from ingestion.web_search.handler import lambda_handler

    mock_entry = {"url": "https://et.com/reliance", "title": "Reliance Q4", "published_at": None}
    long_text = "Reliance reported strong results this quarter. " * 20

    with patch("ingestion.web_search.handler.fetch_rss_entries", return_value=[mock_entry]), \
         patch("ingestion.web_search.handler.fetch_and_build_article") as mock_build, \
         patch("ingestion.web_search.handler.chunk_text", return_value=["chunk1", "chunk2"]), \
         patch("ingestion.web_search.handler.embed_texts", return_value=[[0.1] * 1536, [0.2] * 1536]), \
         patch("ingestion.web_search.handler.upsert_web_search_chunks") as mock_upsert, \
         patch("ingestion.web_search.handler.get_client", return_value=MagicMock()):
        from ingestion.web_search.stock_scraper import ArticleResult
        mock_build.return_value = ArticleResult(
            url="https://et.com/reliance", title="Reliance Q4",
            source_domain="et.com", published_at=None, text=long_text,
        )
        result = lambda_handler({"symbols": ["RELIANCE"]}, None)

    assert result["statusCode"] == 200
    assert result["success"] >= 1
    mock_upsert.assert_called_once()


# --- config completeness ---

def test_nifty50_has_50_symbols():
    from config.nifty50 import NIFTY50_COMPANIES, NIFTY50_SYMBOLS
    assert len(NIFTY50_COMPANIES) == 50
    assert len(NIFTY50_SYMBOLS) == 50
    assert "TCS" in NIFTY50_COMPANIES
    assert "RELIANCE" in NIFTY50_COMPANIES
