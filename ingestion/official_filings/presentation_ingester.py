"""
Ingest investor/analyst presentation PDFs from NSE filings.

Companies file presentations with NSE for:
  - Quarterly earnings investor presentations
  - Annual capital markets / analyst days
  - Strategic announcement presentations

These are often richer than transcripts for financial models:
  revenue guidance, segment breakdowns, capex plans, market share data.
"""

from __future__ import annotations

from supabase import Client

from embeddings.embedder import embed_texts
from ingestion.nse_bse.pdf_processor import chunk_text, extract_text_from_pdf
from ingestion.official_filings.nse_fetcher import (
    download_pdf,
    fetch_announcements,
    get_presentation_entries,
    is_intimation_letter,
)
from ingestion.official_filings.table_extractor import extract_tables_as_text
from monitoring.metrics import IngestionMetrics

CHUNK_SIZE = 400
CHUNK_OVERLAP = 40
MIN_TEXT_CHARS = 300
# A doc is a pure cover/intimation letter only if it's SHORT *and* intimation-like.
# Real decks (50k+ chars) include a Reg-30 cover page but are far longer, so we must
# not flag them just because the cover page has intimation phrases.
INTIMATION_MAX_CHARS = 6000


def ingest_presentations(
    symbol: str,
    client: Client,
    metrics: IngestionMetrics,
    max_recent: int = 6,
) -> int:
    """Ingest last `max_recent` investor presentation PDFs for a stock."""
    try:
        announcements = fetch_announcements(symbol)
    except Exception as exc:
        print(f"[presentation_ingester] {symbol}: NSE API failed: {exc}")
        metrics.record_error()
        return 0

    entries = get_presentation_entries(announcements, max_recent=max_recent)
    if not entries:
        return 0

    success = 0
    for entry in entries:
        # Download bytes once, then extract BOTH the text layer (PyMuPDF) and the
        # structured tables (pdfplumber). Tables recover the financial grids that
        # plain text scrambles — at zero API cost.
        try:
            content = download_pdf(entry["url"])
        except Exception as exc:
            print(f"[presentation_ingester] {symbol} download failed: {exc}")
            metrics.record_error()
            continue

        text = extract_text_from_pdf(content)
        if len(text) < MIN_TEXT_CHARS:
            metrics.record_error()
            continue
        # Pure cover/intimation letters: short AND intimation-like (real decks are huge).
        if len(text) < INTIMATION_MAX_CHARS and is_intimation_letter(text):
            metrics.record_error()
            continue

        text_chunks = chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)

        # Structured tables become their own retrieval chunks (kept intact, not
        # split mid-table). section_type='table' lets the pipeline weight them.
        table_blocks = extract_tables_as_text(content)
        chunks = text_chunks + table_blocks
        section_types = [None] * len(text_chunks) + ["table"] * len(table_blocks)

        try:
            vectors = embed_texts(chunks)
        except Exception as exc:
            print(f"[presentation_ingester] {symbol} embedding failed: {exc}")
            metrics.record_error()
            continue

        if table_blocks:
            print(f"[presentation_ingester] {symbol}: {len(text_chunks)} text + "
                  f"{len(table_blocks)} table chunks — {entry['title'][:40]}")

        rows = [
            {
                "symbol": symbol,
                "document_type": "investor_presentation",
                "quarter": entry["quarter"],
                "fiscal_year": entry["fiscal_year"],
                "filing_date": entry["filing_date"] or None,
                "pdf_url": entry["url"],
                "title": f"{symbol} - {entry['title']}",
                "chunk_index": i,
                "chunk_text": chunk,
                "embedding": vector,
                "section_type": section_types[i],
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
                print(f"[presentation_ingester] {symbol} upsert failed: {exc}")
                metrics.record_error()
                failed = True
                break
        if failed:
            continue

        metrics.record_pdf(chunks=len(chunks), embeddings=len(chunks))
        success += 1

    return success
