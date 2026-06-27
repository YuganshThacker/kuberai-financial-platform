import re
from db.client import get_client
from config.nse_all_stocks import NSE_ALL_COMPANIES
from ingestion.news.rss_poller import poll_feeds, NewsItem
from ingestion.news.content_fetcher import fetch_article_text
from ingestion.nse_bse.pdf_processor import chunk_text
from embeddings.embedder import embed_texts
from embeddings.upserter import upsert_news_chunks

# All 2107 NSE-listed stocks — enables symbol tagging for any NSE company,
# not just the original 19-stock hardcoded set.
_KNOWN_SYMBOLS: frozenset[str] = frozenset(NSE_ALL_COMPANIES.keys())


def _extract_symbols(text: str) -> list:
    words = set(re.findall(r'\b[A-Z0-9&-]{2,10}\b', text))
    return list(words & _KNOWN_SYMBOLS)


def process_article(item: NewsItem, client) -> bool:
    full_text = fetch_article_text(item.url)
    if not full_text or len(full_text) < 100:
        full_text = item.summary or item.title
    if not full_text.strip():
        return False

    symbols = _extract_symbols(item.title + " " + full_text)
    chunks = chunk_text(full_text, chunk_size=300, overlap=30)
    vectors = embed_texts(chunks)
    upsert_news_chunks(
        client=client,
        title=item.title,
        url=item.url,
        source=item.source,
        published_at=item.published_at,
        symbols=symbols,
        chunks=chunks,
        vectors=vectors,
    )
    return True


def lambda_handler(event: dict, context) -> dict:
    """Triggered by EventBridge every 30 minutes."""
    client = get_client()
    items = poll_feeds(max_per_feed=30)
    success, skipped = 0, 0
    for item in items:
        if not item.url:
            skipped += 1
            continue
        try:
            ok = process_article(item, client)
            success += int(ok)
        except Exception as e:
            print(f"[news] Error: {item.url}: {e}")
            skipped += 1

    return {"statusCode": 200, "processed": success, "skipped": skipped}
