from urllib.parse import quote_plus

# Yahoo Finance RSS: per-stock news with direct publisher URLs (no JS redirects).
# NSE symbols map to Yahoo Finance as {SYMBOL}.NS (e.g. TCS.NS, RELIANCE.NS).
YAHOO_FINANCE_RSS_BASE = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}.NS&region=IN&lang=en-IN"
)

GOOGLE_NEWS_RSS_BASE = (
    "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)


def yahoo_finance_rss_url(symbol: str) -> str:
    return YAHOO_FINANCE_RSS_BASE.format(symbol=symbol)


def google_news_rss_url(company_name: str) -> str:
    query = quote_plus(f"{company_name} NSE India stock")
    return GOOGLE_NEWS_RSS_BASE.format(query=query)


def screener_url(symbol: str) -> str:
    return f"https://www.screener.in/company/{symbol}/"


def screener_consolidated_url(symbol: str) -> str:
    return f"https://www.screener.in/company/{symbol}/consolidated/"


def indiainfoline_url(symbol: str, company_name: str) -> str:
    import re as _re
    slug = _re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")
    return f"https://www.indiainfoline.com/company/{slug}/"


def alphaspread_url(symbol: str) -> str:
    return f"https://alphaspread.com/security/nse/{symbol.lower()}/summary"


def stockanalysis_url(symbol: str) -> str:
    return f"https://stockanalysis.com/stocks/{symbol.lower()}.ns/"


def nse_announcements_url(symbol: str) -> str:
    return f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={symbol}"


def tradingview_url(symbol: str) -> str:
    return f"https://in.tradingview.com/symbols/NSE-{symbol}/"


def tickertape_url(symbol: str, company_name: str) -> str:
    import re as _re
    slug = _re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")
    return f"https://www.tickertape.in/stocks/{slug}-{symbol}"


# General Indian financial RSS feeds — fetched once per Lambda run (cached) and
# filtered per stock by keyword. Each feed returns direct publisher URLs.
# Confirmed working as of June 2026.
GENERAL_RSS_FEEDS = [
    {"source": "economic_times",    "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"},
    {"source": "et_stocks",         "url": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"},
    {"source": "et_company_news",   "url": "https://economictimes.indiatimes.com/news/company/rssfeeds/2143429.cms"},
    {"source": "business_standard", "url": "https://www.business-standard.com/rss/markets-106.rss"},
    {"source": "bs_companies",      "url": "https://www.business-standard.com/rss/companies-101.rss"},
    {"source": "ndtv_profit",       "url": "https://feeds.feedburner.com/ndtvprofit-latest"},
    {"source": "mint",              "url": "https://www.livemint.com/rss/markets"},
    {"source": "financial_express", "url": "https://www.financialexpress.com/market/feed/"},
    {"source": "hindu_businessline","url": "https://www.thehindubusinessline.com/markets/?service=rss"},
    {"source": "moneycontrol",      "url": "https://www.moneycontrol.com/rss/marketreports.xml"},
    {"source": "cnbctv18",          "url": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml"},
]
