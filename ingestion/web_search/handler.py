import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from config.nifty50 import NIFTY50_COMPANIES, NIFTY50_SYMBOLS
from config.nse_all_stocks import NSE_ALL_COMPANIES
from db.client import get_client
from embeddings.embedder import embed_texts
from embeddings.upserter import upsert_web_search_chunks
from ingestion.nse_bse.pdf_processor import chunk_text
from ingestion.web_search.stock_scraper import fetch_and_build_article, fetch_rss_entries

# 15 parallel Jina fetches keeps Lambda well within 900 s for 50 stocks × 12 articles
MAX_WORKERS = 15
WEB_CHUNK_SIZE = 300
WEB_CHUNK_OVERLAP = 30


def _process_entry(client, symbol: str, entry: dict) -> bool:
    article = fetch_and_build_article(entry)
    if not article:
        return False
    try:
        chunks = chunk_text(article.text, chunk_size=WEB_CHUNK_SIZE, overlap=WEB_CHUNK_OVERLAP)
        vectors = embed_texts(chunks)
        upsert_web_search_chunks(
            client=client,
            symbol=symbol,
            url=article.url,
            title=article.title,
            source_domain=article.source_domain,
            published_at=article.published_at,
            chunks=chunks,
            vectors=vectors,
        )
        return True
    except Exception as exc:
        print(f"[web_search] embed/upsert error {symbol} {article.url}: {exc}")
        return False


def lambda_handler(event: dict, context) -> dict:
    """Triggered by EventBridge daily at 07:30 IST and 17:00 IST."""
    symbols = event.get("symbols", NIFTY50_SYMBOLS)
    client = get_client()

    # company name lookup: full NSE list first, then Nifty 50, then symbol itself
    def _company_name(sym: str) -> str:
        return NSE_ALL_COMPANIES.get(sym) or NIFTY50_COMPANIES.get(sym) or sym

    # Step 1: RSS parse (fast, no Jina yet)
    all_entries: list[tuple[str, dict]] = []
    for symbol in symbols:
        company = _company_name(symbol)
        for entry in fetch_rss_entries(symbol, company):
            all_entries.append((symbol, entry))

    print(f"[web_search] RSS collected {len(all_entries)} articles for {len(symbols)} stocks")

    # Step 2: Parallel Jina fetch + embed + upsert
    success = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_process_entry, client, sym, entry): (sym, entry["url"])
            for sym, entry in all_entries
        }
        for future in as_completed(futures):
            sym, url = futures[future]
            try:
                if future.result():
                    success += 1
            except Exception as exc:
                print(f"[web_search] {sym} {url}: {exc}")

    result = {"statusCode": 200, "total": len(all_entries), "success": success}
    print(json.dumps(result))
    return result
