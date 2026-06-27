import pytest
from unittest.mock import MagicMock, patch
import respx
import httpx

from ingestion.web_search.url_registry import (
    google_news_rss_url,
    screener_url,
    alphaspread_url,
    stockanalysis_url,
)
from ingestion.web_search.stock_scraper import (
    _domain,
    _parse_screener_html,
    fetch_and_build_article,
    fetch_rss_entries,
    get_direct_page_entries,
)


@pytest.fixture(autouse=True)
def clear_rss_cache():
    """Clear module-level RSS cache before each test to prevent cross-test pollution."""
    import ingestion.web_search.stock_scraper as scraper
    scraper._RSS_CACHE.clear()
    yield
    scraper._RSS_CACHE.clear()


# --- url_registry ---

def test_google_news_rss_url_contains_company():
    url = google_news_rss_url("Tata Consultancy Services")
    assert "Tata+Consultancy+Services" in url or "Tata%20Consultancy" in url or "Tata" in url
    assert "news.google.com/rss/search" in url
    assert "IN:en" in url


def test_screener_url():
    assert screener_url("TCS") == "https://www.screener.in/company/TCS/"


def test_alphaspread_url_lowercased():
    assert alphaspread_url("TCS") == "https://alphaspread.com/security/nse/tcs/summary"


def test_stockanalysis_url_lowercased():
    assert stockanalysis_url("RELIANCE") == "https://stockanalysis.com/stocks/reliance.ns/"


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


def _mock_httpx_response(text: str = "<rss/>"):
    mock_resp = MagicMock()
    mock_resp.text = text
    mock_resp.raise_for_status = lambda: None
    return mock_resp


def test_fetch_rss_entries_returns_entries():
    mock_feed = MagicMock()
    mock_feed.entries = [
        _make_mock_entry("https://et.com/tcs-q4", "TCS Q4 Results"),
        _make_mock_entry("https://mc.com/tcs-buy", "TCS Buy Call"),
    ]
    with patch("ingestion.web_search.stock_scraper.httpx.get", return_value=_mock_httpx_response()), \
         patch("ingestion.web_search.stock_scraper.feedparser.parse", return_value=mock_feed):
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
    mock_feed.entries = [no_link]
    with patch("ingestion.web_search.stock_scraper.httpx.get", return_value=_mock_httpx_response()), \
         patch("ingestion.web_search.stock_scraper.feedparser.parse", return_value=mock_feed):
        entries = fetch_rss_entries("TCS", "Tata Consultancy Services")
    assert entries == []


def test_fetch_rss_entries_handles_parse_error():
    with patch("ingestion.web_search.stock_scraper.httpx.get", side_effect=Exception("timeout")):
        entries = fetch_rss_entries("TCS", "Tata Consultancy Services")
    assert entries == []


def test_fetch_rss_entries_skips_google_news_links():
    """Yahoo Finance fallback should filter out news.google.com redirect URLs."""
    mock_feed = MagicMock()
    mock_feed.entries = [
        _make_mock_entry("https://news.google.com/rss/articles/CBM123", "Some Article"),
        _make_mock_entry("https://economictimes.com/real-article", "Real Article"),
    ]
    with patch("ingestion.web_search.stock_scraper.httpx.get", return_value=_mock_httpx_response()), \
         patch("ingestion.web_search.stock_scraper.feedparser.parse", return_value=mock_feed):
        entries = fetch_rss_entries("TCS", "Tata Consultancy Services")
    # Google News URL should be filtered; only the ET URL should remain
    assert len(entries) == 1
    assert entries[0]["url"] == "https://economictimes.com/real-article"


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
         patch("ingestion.web_search.handler.get_direct_page_entries", return_value=[]), \
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


# --- get_direct_page_entries ---

def test_direct_page_entries_core_sources_present():
    entries = get_direct_page_entries("TCS", "Tata Consultancy Services")
    urls = [e["url"] for e in entries]
    # Core sources always present
    assert any("screener.in/company/TCS/" in u for u in urls), "screener standalone missing"
    assert any("consolidated" in u for u in urls), "screener consolidated missing"
    assert any("alphaspread.com" in u for u in urls), "alphaspread missing"
    assert any("stockanalysis.com" in u for u in urls), "stockanalysis missing"
    assert any("nseindia.com" in u for u in urls), "nse announcements missing"
    assert any("tickertape.in" in u for u in urls), "tickertape missing"
    assert any("tradingview.com" in u for u in urls), "tradingview missing"
    assert any("indiainfoline.com" in u for u in urls), "indiainfoline missing"
    # TCS has an IR page in COMPANY_IR_URLS
    assert any("tcs.com" in u for u in urls), "company IR page missing"
    assert len(entries) >= 8


def test_direct_page_entries_have_fetch_methods():
    entries = get_direct_page_entries("TCS", "Tata Consultancy Services")
    methods = {e["fetch_method"] for e in entries}
    assert "screener" in methods
    assert "nse_announcements" in methods
    assert "jina" in methods


def test_tickertape_url_uses_company_slug():
    from ingestion.web_search.url_registry import tickertape_url
    url = tickertape_url("TCS", "Tata Consultancy Services")
    assert "tickertape.in" in url
    assert "TCS" in url
    assert "tata-consultancy-services" in url


def test_tradingview_url_uses_nse_prefix():
    from ingestion.web_search.url_registry import tradingview_url
    url = tradingview_url("RELIANCE")
    assert "tradingview.com" in url
    assert "NSE-RELIANCE" in url


# --- Screener HTML parser ---

_SCREENER_SAMPLE_HTML = """
<ul id="top-ratios">
  <li><span class="name">Market Cap</span><span class="value">₹ 7,95,617 Cr.</span></li>
  <li><span class="name">Stock P/E</span><span class="value">15.1</span></li>
  <li><span class="name">ROE</span><span class="value">65.2 %</span></li>
</ul>
<section id="about">
  <p>TCS is an IT services company.</p>
</section>
<h2 class="flex flex-wrap">Quarterly Results</h2>
<table><tr><td>Sales</td><td>63,973</td></tr></table>
"""


def test_parse_screener_html_extracts_ratios():
    text = _parse_screener_html(_SCREENER_SAMPLE_HTML, "TCS")
    assert "P/E" in text or "PE" in text or "15.1" in text
    assert "ROE" in text or "65.2" in text


def test_parse_screener_html_extracts_overview():
    text = _parse_screener_html(_SCREENER_SAMPLE_HTML, "TCS")
    assert "IT services" in text


def test_parse_screener_html_extracts_quarterly():
    text = _parse_screener_html(_SCREENER_SAMPLE_HTML, "TCS")
    assert "Quarterly" in text


# --- fetch_and_build_article with screener fetch_method ---

def test_fetch_and_build_article_screener_dispatch():
    """Screener entries use httpx+parser, not Jina."""
    long_text = "TCS key ratios: P/E 15.1, ROE 65%. " * 10  # noqa: F841 (used via return_value)
    entry = {
        "url": "https://www.screener.in/company/TCS/",
        "title": "TCS - Screener",
        "published_at": None,
        "fetch_method": "screener",
        "symbol": "TCS",
    }
    long_text = "TCS key ratios: P/E 15.1, ROE 65%. " * 10
    with patch("ingestion.web_search.stock_scraper._fetch_screener_text", return_value=long_text):
        result = fetch_and_build_article(entry)
    assert result is not None
    assert result.source_domain == "screener.in"
    assert "P/E" in result.text or "ROE" in result.text


def test_fetch_and_build_article_nse_announcements_dispatch():
    """NSE announcement entries use the NSE API fetcher, not Jina."""
    long_text = "NSE Corporate Announcements for TCS:\n\n" + "[16-Jun-2026] Updates: TCS launches AI center. " * 5
    entry = {
        "url": "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=TCS",
        "title": "TCS - NSE Announcements",
        "published_at": None,
        "fetch_method": "nse_announcements",
        "symbol": "TCS",
    }
    with patch("ingestion.web_search.stock_scraper._fetch_nse_announcements_text", return_value=long_text):
        result = fetch_and_build_article(entry)
    assert result is not None
    assert result.source_domain == "nseindia.com"
    assert "TCS" in result.text


# --- config completeness ---

def test_nifty50_has_50_symbols():
    from config.nifty50 import NIFTY50_COMPANIES, NIFTY50_SYMBOLS
    assert len(NIFTY50_COMPANIES) == 50
    assert len(NIFTY50_SYMBOLS) == 50
    assert "TCS" in NIFTY50_COMPANIES
    assert "RELIANCE" in NIFTY50_COMPANIES
