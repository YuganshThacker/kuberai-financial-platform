"""
Ingest quarterly financial result PDFs from NSE filings.

Companies file detailed financial result press releases with NSE within 24h
of board approval (SEBI requirement). These PDFs contain:
  - Standalone and consolidated P&L
  - Balance sheet highlights
  - Segment performance
  - Management notes
"""

from __future__ import annotations

from supabase import Client

from embeddings.embedder import embed_texts
from ingestion.nse_bse.pdf_processor import chunk_text
from ingestion.official_filings.nse_fetcher import (
    download_and_extract,
    fetch_announcements,
    get_quarterly_results_entries,
)
from monitoring.metrics import IngestionMetrics

CHUNK_SIZE = 400
CHUNK_OVERLAP = 40
MIN_TEXT_CHARS = 200


def ingest_quarterly_results(
    symbol: str,
    client: Client,
    metrics: IngestionMetrics,
    max_recent: int = 8,
) -> int:
    """Ingest last `max_recent` quarterly result PDFs for a stock."""
    try:
        announcements = fetch_announcements(symbol)
    except Exception as exc:
        print(f"[quarterly_results_ingester] {symbol}: NSE API failed: {exc}")
        metrics.record_error()
        return 0

    entries = get_quarterly_results_entries(announcements, max_recent=max_recent)
    if not entries:
        return 0

    success = 0
    for entry in entries:
        text = download_and_extract(entry["url"])
        if len(text) < MIN_TEXT_CHARS:
            metrics.record_error()
            continue

        chunks = chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        try:
            vectors = embed_texts(chunks)
        except Exception as exc:
            print(f"[quarterly_results_ingester] {symbol} embedding failed: {exc}")
            metrics.record_error()
            continue

        rows = [
            {
                "symbol": symbol,
                "document_type": "quarterly_results",
                "quarter": entry["quarter"],
                "fiscal_year": entry["fiscal_year"],
                "filing_date": entry["filing_date"] or None,
                "pdf_url": entry["url"],
                "title": f"{symbol} - {entry['title']}",
                "chunk_index": i,
                "chunk_text": chunk,
                "embedding": vector,
            }
            for i, (chunk, vector) in enumerate(zip(chunks, vectors))
        ]
        failed = False
        for batch_start in range(0, len(rows), 20):
            batch = rows[batch_start : batch_start + 20]
            try:
                client.table("corporate_documents").upsert(
                    batch, on_conflict="pdf_url,chunk_index"
                ).execute()
            except Exception as exc:
                print(f"[quarterly_results_ingester] {symbol} upsert failed: {exc}")
                metrics.record_error()
                failed = True
                break
        if failed:
            continue

        metrics.record_pdf(chunks=len(chunks), embeddings=len(chunks))
        success += 1

    return success
