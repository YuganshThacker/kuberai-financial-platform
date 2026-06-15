import feedparser
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from ingestion.news.content_fetcher import fetch_article_text
from ingestion.web_search.url_registry import google_news_rss_url

MAX_ARTICLES_PER_STOCK = 12
MIN_TEXT_CHARS = 200


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


def fetch_rss_entries(symbol: str, company_name: str) -> list[dict]:
    """Parse Google News RSS for a stock; returns raw entry dicts (no HTTP to articles yet)."""
    rss_url = google_news_rss_url(company_name)
    try:
        feed = feedparser.parse(rss_url)
        return [
            {
                "url": getattr(e, "link", ""),
                "title": getattr(e, "title", ""),
                "published_at": _rss_date(e),
            }
            for e in feed.entries[:MAX_ARTICLES_PER_STOCK]
            if getattr(e, "link", "")
        ]
    except Exception as exc:
        print(f"[web_search] RSS error {symbol}: {exc}")
        return []


def fetch_and_build_article(entry: dict) -> Optional[ArticleResult]:
    """Fetch full article text via Jina and return ArticleResult; None if too short."""
    url = entry["url"]
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
