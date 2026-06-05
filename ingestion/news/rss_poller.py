import feedparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

RSS_FEEDS = [
    {"source": "moneycontrol",      "url": "https://www.moneycontrol.com/rss/MCtopnews.xml"},
    {"source": "economic_times",    "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"},
    {"source": "mint",              "url": "https://www.livemint.com/rss/markets"},
    {"source": "business_standard", "url": "https://www.business-standard.com/rss/markets-106.rss"},
    {"source": "ndtv_profit",       "url": "https://feeds.feedburner.com/ndtvprofit-latest"},
    {"source": "financial_express", "url": "https://www.financialexpress.com/market/feed/"},
    {"source": "reuters_india",     "url": "https://feeds.reuters.com/reuters/INbusinessNews"},
    {"source": "hindu_businessline","url": "https://www.thehindubusinessline.com/markets/?service=rss"},
    {"source": "cnbctv18",          "url": "https://www.cnbctv18.com/commonfeeds/v1/hin/rss/market.xml"},
    {"source": "google_news_india", "url": "https://news.google.com/rss/search?q=NSE+BSE+stock+India&hl=en-IN&gl=IN&ceid=IN:en"},
]

@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published_at: Optional[str] = None
    summary: Optional[str] = None
    symbols: List[str] = field(default_factory=list)

def _parse_time(entry) -> Optional[str]:
    t = getattr(entry, "published_parsed", None)
    if t:
        return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
    return None

def poll_feeds(max_per_feed: int = 50) -> List[NewsItem]:
    items = []
    for feed_config in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_config["url"])
            for entry in feed.entries[:max_per_feed]:
                items.append(NewsItem(
                    title=getattr(entry, "title", ""),
                    url=getattr(entry, "link", ""),
                    source=feed_config["source"],
                    published_at=_parse_time(entry),
                    summary=getattr(entry, "summary", None),
                ))
        except Exception as e:
            print(f"[rss] Error polling {feed_config['source']}: {e}")
    return items
