from urllib.parse import quote_plus

# Google News RSS is the zero-cost aggregator for per-stock news from
# ET, Moneycontrol, NDTV Profit, Business Standard, etc.
# No API key needed; deduplication happens via URL uniqueness in the DB.
GOOGLE_NEWS_RSS_BASE = (
    "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)


def google_news_rss_url(company_name: str) -> str:
    query = quote_plus(f"{company_name} NSE India stock")
    return GOOGLE_NEWS_RSS_BASE.format(query=query)


def screener_page_url(symbol: str) -> str:
    return f"https://www.screener.in/company/{symbol}/"
