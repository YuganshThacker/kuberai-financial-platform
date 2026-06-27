"""
NSE Filings Lambda handler.

Triggered weekly (Sunday 00:00 IST) — separate from web_search since
transcripts and results are published quarterly.

For each stock:
  - Last 3 earnings call transcripts (PDF → text)
  - Last 5 quarterly financial results (PDF → text)
  - Last 8 press releases/investor presentations (PDF → text)
  - Chunks, embeds, upserts to web_search_results

Source domain in DB: nsearchives.nseindia.com
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from config.nifty50 import NIFTY50_SYMBOLS
from db.client import get_client
from embeddings.embedder import embed_texts
from embeddings.upserter import upsert_web_search_chunks
from ingestion.nse_bse.pdf_processor import chunk_text
from ingestion.nse_filings.transcript_fetcher import (
    download_and_extract_pdf,
    get_financial_result_urls,
    get_press_release_urls,
    get_transcript_urls,
)

MAX_WORKERS = 8
CHUNK_SIZE = 400
CHUNK_OVERLAP = 40
MIN_TEXT_CHARS = 300


def _process_pdf_entry(client, symbol: str, entry: dict) -> bool:
    try:
        text = download_and_extract_pdf(entry["url"])
        if len(text) < MIN_TEXT_CHARS:
            return False
        chunks = chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        vectors = embed_texts(chunks)
        upsert_web_search_chunks(
            client=client,
            symbol=symbol,
            url=entry["url"],
            title=entry["title"],
            source_domain="nsearchives.nseindia.com",
            published_at=entry.get("filing_date"),
            chunks=chunks,
            vectors=vectors,
        )
        return True
    except Exception as exc:
        print(f"[nse_filings] {symbol} {entry['url']}: {exc}")
        return False


def lambda_handler(event: dict, context) -> dict:
    """Weekly Lambda — transcripts + results + press release PDFs from NSE."""
    symbols = event.get("symbols", NIFTY50_SYMBOLS)
    mode = event.get("mode", "all")  # 'transcripts', 'results', 'press', or 'all'
    client = get_client()

    all_work: list[tuple[str, dict]] = []
    for symbol in symbols:
        if mode in ("transcripts", "all"):
            for entry in get_transcript_urls(symbol, max_recent=3):
                all_work.append((symbol, entry))
        if mode in ("results", "all"):
            for entry in get_financial_result_urls(symbol, max_recent=5):
                all_work.append((symbol, entry))
        if mode in ("press", "all"):
            for entry in get_press_release_urls(symbol, max_recent=8):
                all_work.append((symbol, entry))

    print(f"[nse_filings] {len(all_work)} PDFs queued for {len(symbols)} stocks")

    success = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_process_pdf_entry, client, sym, entry): (sym, entry["url"])
            for sym, entry in all_work
        }
        for future in as_completed(futures):
            sym, url = futures[future]
            try:
                if future.result():
                    success += 1
            except Exception as exc:
                print(f"[nse_filings] {sym} {url}: {exc}")

    result = {"statusCode": 200, "total": len(all_work), "success": success}
    print(json.dumps(result))
    return result
