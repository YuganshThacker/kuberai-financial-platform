import re
import feedparser
import httpx
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from ingestion.news.content_fetcher import fetch_article_text
from config.company_ir_urls import COMPANY_IR_URLS
from ingestion.web_search.url_registry import (
    GENERAL_RSS_FEEDS,
    alphaspread_url,
    google_news_rss_url,
    indiainfoline_url,
    nse_announcements_url,
    screener_consolidated_url,
    screener_url,
    stockanalysis_url,
    tickertape_url,
    tradingview_url,
    yahoo_finance_rss_url,
)

_RSS_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KuberAI/1.0)"}
_SCRAPE_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com/",
    "Accept": "application/json",
}

MAX_ARTICLES_PER_STOCK = 15
MIN_TEXT_CHARS = 200

# Module-level RSS cache — populated once per Lambda container, keyed by feed URL.
# Avoids re-fetching the same general feed for each of the 50+ stocks per run.
_RSS_CACHE: dict[str, list] = {}


@dataclass
class ArticleResult:
    url: str
    title: str
    source_domain: str
    published_at: Optional[str]
    text: str


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.removeprefix("www.")
    except Exception:
        return ""


def _rss_date(entry) -> Optional[str]:
    t = getattr(entry, "published_parsed", None)
    if t:
        return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
    return None


def _fetch_rss(rss_url: str) -> list:
    """Fetch RSS via httpx (avoids macOS SSL issues) and parse with feedparser."""
    resp = httpx.get(rss_url, headers=_RSS_HEADERS, follow_redirects=True, timeout=15)
    resp.raise_for_status()
    return feedparser.parse(resp.text).entries


def _fetch_rss_cached(rss_url: str) -> list:
    """Fetch RSS with module-level cache — each general feed is fetched only once per run.

    Failures are NOT cached: a timeout on the first stock shouldn't permanently
    suppress a feed for all subsequent stocks in the same Lambda invocation.
    """
    if rss_url not in _RSS_CACHE:
        try:
            entries = _fetch_rss(rss_url)
            _RSS_CACHE[rss_url] = entries  # only cache on success
        except Exception:
            return []  # transient failure — don't poison the cache
    return _RSS_CACHE[rss_url]


def _entry_to_dict(e) -> dict:
    return {
        "url": getattr(e, "link", ""),
        "title": getattr(e, "title", ""),
        "published_at": _rss_date(e),
        "fetch_method": "jina",
    }


_BLOCKED_URL_PATTERNS = (
    "news.google.com",
    "finance.yahoo.com/sectors/",
    "finance.yahoo.com/news/",   # geo-blocked by Jina; regional mirrors (ca./sg.) still pass
)


def _is_usable_url(url: str) -> bool:
    return bool(url) and not any(p in url for p in _BLOCKED_URL_PATTERNS)


def fetch_from_general_rss(symbol: str, company_name: str, max_results: int = 10) -> list[dict]:
    """Search all general Indian financial RSS feeds for articles mentioning this stock.

    Uses module-level cache so each feed is fetched only once per Lambda run.
    Filters entries where the title contains the symbol or company name keyword.
    """
    keywords = {symbol.lower(), company_name.split()[0].lower()}
    results: list[dict] = []
    seen_urls: set[str] = set()

    for feed_cfg in GENERAL_RSS_FEEDS:
        try:
            entries = _fetch_rss_cached(feed_cfg["url"])
            for e in entries:
                title = getattr(e, "title", "").lower()
                url = getattr(e, "link", "")
                if (
                    any(kw in title for kw in keywords)
                    and _is_usable_url(url)
                    and url not in seen_urls
                ):
                    seen_urls.add(url)
                    results.append(_entry_to_dict(e))
        except Exception:
            pass
        if len(results) >= max_results:
            break

    return results[:max_results]


def fetch_rss_entries(symbol: str, company_name: str) -> list[dict]:
    """Return up to MAX_ARTICLES_PER_STOCK article dicts for a stock.

    Always combines:
    1. Yahoo Finance RSS (symbol.NS) — per-stock, direct publisher URLs.
    2. General RSS feeds (11 sources) filtered by company keyword — Indian sources.

    General feeds always run (cached) to ensure Indian publisher coverage regardless
    of how many Yahoo Finance articles survive Jina geo-filtering.
    """
    seen_urls: set[str] = set()
    results: list[dict] = []

    try:
        yahoo_entries = _fetch_rss(yahoo_finance_rss_url(symbol))
        for e in yahoo_entries[:MAX_ARTICLES_PER_STOCK]:
            url = getattr(e, "link", "")
            if _is_usable_url(url) and url not in seen_urls:
                seen_urls.add(url)
                results.append(_entry_to_dict(e))
    except Exception:
        pass

    general = fetch_from_general_rss(symbol, company_name, max_results=MAX_ARTICLES_PER_STOCK)
    for r in general:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            results.append(r)

    return results[:MAX_ARTICLES_PER_STOCK]


# ── Direct page scrapers ──────────────────────────────────────────────────────

def _parse_screener_html(html: str, symbol: str) -> str:
    """Extract financial data from Screener.in HTML into clean plain text."""
    parts = []

    # Key ratios block (Market Cap, P/E, ROE, ROCE, etc.)
    m = re.search(r'id="top-ratios"[^>]*>(.*?)</ul>', html, re.DOTALL)
    if m:
        clean = re.sub(r'<[^>]+>', ' ', m.group(1))
        clean = re.sub(r'\s+', ' ', clean).strip()
        parts.append(f"Key Financial Ratios for {symbol}: {clean}")

    # Company overview paragraph
    m2 = re.search(r'id="about".*?<p[^>]*>(.*?)</p>', html, re.DOTALL)
    if m2:
        clean2 = re.sub(r'<[^>]+>', ' ', m2.group(1))
        parts.append(f"Company Overview ({symbol}): {clean2.strip()}")

    # Quarterly results table
    idx = html.find("Quarterly Results</h2>")
    if idx > 0:
        snippet = re.sub(r'<[^>]+>', ' ', html[idx:idx + 3000])
        parts.append(f"Quarterly Results: {re.sub(r' +', ' ', snippet).strip()[:800]}")

    # Annual Profit & Loss
    idx2 = html.find("Profit &amp; Loss</h2>")
    if idx2 < 0:
        idx2 = html.find("Profit & Loss</h2>")
    if idx2 > 0:
        snippet2 = re.sub(r'<[^>]+>', ' ', html[idx2:idx2 + 2000])
        parts.append(f"Annual P&L: {re.sub(r' +', ' ', snippet2).strip()[:600]}")

    return "\n\n".join(parts)


def _fetch_screener_text(symbol: str) -> str:
    """Fetch Screener.in and return extracted financial text; empty string on failure."""
    url = screener_url(symbol)
    try:
        r = httpx.get(url, headers=_SCRAPE_HEADERS, follow_redirects=True, timeout=20)
        r.raise_for_status()
        return _parse_screener_html(r.text, symbol)
    except Exception:
        return ""


def _fetch_nse_announcements_text(symbol: str, max_items: int = 40) -> str:
    """Fetch NSE corporate announcements JSON and return plain-text summary.

    Uses the official NSE API (nseindia.com) which returns 3000+ filings per stock.
    Takes the most recent max_items announcements with non-trivial text.
    """
    try:
        r = httpx.get(
            nse_announcements_url(symbol),
            headers=_NSE_HEADERS,
            follow_redirects=True,
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        items = [d for d in data if len(d.get("attchmntText", "")) > 50][:max_items]
        if not items:
            return ""
        parts = [f"NSE Official Corporate Announcements for {symbol}:"]
        for item in items:
            date = item.get("an_dt", "")
            category = item.get("desc", "")
            text = item.get("attchmntText", "")
            parts.append(f"[{date}] {category}: {text}")
        return "\n\n".join(parts)
    except Exception:
        return ""


def get_direct_page_entries(symbol: str, company_name: str = "") -> list[dict]:
    """Return direct financial data page entries for a stock (no RSS, no Jina yet).

    These are added to the work queue alongside RSS articles and fetched in parallel
    by the handler's ThreadPoolExecutor. Each entry has a 'fetch_method' key:
      'screener'          → httpx + HTML parser (Screener.in)
      'nse_announcements' → NSE official API JSON (nseindia.com)
      'jina'              → Jina reader API (AlphaSpread, StockAnalysis, Tickertape, TradingView)
    """
    return [
        {
            "url": screener_url(symbol),
            "title": f"{symbol} - Financial Ratios & Data (Screener.in)",
            "published_at": None,
            "fetch_method": "screener",
            "symbol": symbol,
        },
        {
            "url": nse_announcements_url(symbol),
            "title": f"{symbol} - NSE Official Corporate Announcements",
            "published_at": None,
            "fetch_method": "nse_announcements",
            "symbol": symbol,
        },
        {
            "url": alphaspread_url(symbol),
            "title": f"{symbol} - Valuation Summary (AlphaSpread)",
            "published_at": None,
            "fetch_method": "jina",
        },
        {
            "url": stockanalysis_url(symbol),
            "title": f"{symbol} - Financial Statements (StockAnalysis)",
            "published_at": None,
            "fetch_method": "jina",
        },
        {
            "url": screener_consolidated_url(symbol),
            "title": f"{symbol} - Consolidated Financials (Screener.in)",
            "published_at": None,
            "fetch_method": "screener",
            "symbol": symbol,
        },
        {
            "url": tickertape_url(symbol, company_name),
            "title": f"{symbol} - Stock Analysis & Scorecard (Tickertape)",
            "published_at": None,
            "fetch_method": "jina",
        },
        {
            "url": tradingview_url(symbol),
            "title": f"{symbol} - NSE Chart & Market Data (TradingView)",
            "published_at": None,
            "fetch_method": "jina",
        },
        {
            "url": indiainfoline_url(symbol, company_name),
            "title": f"{symbol} - Share Price & Analysis (IndiaInfoline)",
            "published_at": None,
            "fetch_method": "jina",
        },
    ] + (
        [
            {
                "url": COMPANY_IR_URLS[symbol],
                "title": f"{symbol} - Investor Relations (Official)",
                "published_at": None,
                "fetch_method": "jina",
            }
        ]
        if symbol in COMPANY_IR_URLS else []
    )


def fetch_and_build_article(entry: dict) -> Optional[ArticleResult]:
    """Fetch full article or page text; return ArticleResult or None if too short.

    Dispatch:
      fetch_method='jina'              → Jina reader API (news articles, AlphaSpread, StockAnalysis)
      fetch_method='screener'          → httpx + HTML parser (Screener.in)
      fetch_method='nse_announcements' → NSE official announcements API
    """
    url = entry["url"]
    fetch_method = entry.get("fetch_method", "jina")

    if fetch_method == "screener":
        symbol = entry.get("symbol") or url.rstrip("/").split("/")[-1]
        text = _fetch_screener_text(symbol)
    elif fetch_method == "nse_announcements":
        symbol = entry.get("symbol") or url.split("symbol=")[-1]
        text = _fetch_nse_announcements_text(symbol)
    else:
        text = fetch_article_text(url)

    if len(text) < MIN_TEXT_CHARS:
        return None

    return ArticleResult(
        url=url,
        title=entry["title"],
        source_domain=_domain(url),
        published_at=entry.get("published_at"),
        text=text,
    )
