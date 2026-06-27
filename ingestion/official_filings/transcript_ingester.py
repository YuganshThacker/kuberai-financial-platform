"""
Ingest NSE earnings call transcripts into corporate_documents table.

Each transcript PDF is:
  1. Fetched from nsearchives.nseindia.com (with intimation-letter fallback to company IR site)
  2. Validated through 4 quality gates before any embedding is generated
  3. Chunked (~400 words/chunk) and embedded via text-embedding-3-small
  4. Upserted into corporate_documents (deduped on pdf_url, chunk_index)
  5. Passed to insight_extractor for structured extraction (guidance, capex, risks)

Quality gates (in order):
  Gate 1 — Intimation letter check: if NSE PDF is a cover letter, follow the
            company IR URL embedded in the letter to get the real transcript.
  Gate 2 — Minimum text length: real transcripts are 10k–50k chars; letters ~1k.
  Gate 3 — Minimum chunk count: real transcripts produce 20–200 chunks; stubs <5.
  Gate 4 — Transcript keyword validation: real calls contain operator/analyst/Q&A language.

All rejections are written to failed_documents for monitoring and replay.
official_transcripts remains available as a view over corporate_documents.
"""

from __future__ import annotations

import re
from supabase import Client

from embeddings.embedder import embed_texts
from ingestion.nse_bse.pdf_processor import chunk_text
from ingestion.official_filings.nse_fetcher import (
    download_and_extract_with_fallback,
    extract_any_url,
    fetch_announcements,
    get_transcript_entries,
    FetchResult,
)
from ingestion.official_filings.insight_extractor import extract_and_store_insights
from monitoring.metrics import IngestionMetrics

CHUNK_SIZE = 400
CHUNK_OVERLAP = 40

# Gate 2: real transcripts are 10k–50k chars; intimation letters are ~1–2k
MIN_TEXT_CHARS = 3_000

# Gate 3: real transcripts produce 20–200 chunks; cover pages/stubs produce <5
MIN_CHUNKS = 5

# Gate 4: at least 2 of these must appear for a document to be a real call transcript
_TRANSCRIPT_KEYWORDS = (
    r"\boperator\b",
    r"\banalyst\b",
    r"\bq&a\b",
    r"\bquestion\b",
    r"\bconference call\b",
    r"\bearnings call\b",
    r"\bparticipants\b",
    r"\bmanagement\b",
    r"\bspeaker\b",
    r"\bmoderat",   # moderator
)
_MIN_KEYWORD_SCORE = 2


def _keyword_score(text: str) -> int:
    lower = text.lower()
    return sum(1 for kw in _TRANSCRIPT_KEYWORDS if re.search(kw, lower))


def _log_rejection(
    client: Client,
    symbol: str,
    pdf_url: str,
    reason: str,
    *,
    quarter: str | None = None,
    document_type: str = "transcript",
    company_url: str | None = None,
    text_length: int = 0,
    chunk_count: int = 0,
    notes: str | None = None,
) -> None:
    try:
        client.table("failed_documents").upsert(
            {
                "symbol": symbol,
                "pdf_url": pdf_url,
                "company_url": company_url,
                "reason": reason,
                "quarter": quarter,
                "document_type": document_type,
                "text_length": text_length,
                "chunk_count": chunk_count,
                "notes": notes,
            },
            on_conflict="pdf_url,reason,document_type",
        ).execute()
    except Exception as exc:
        print(f"[transcript_ingester] failed_documents write error: {exc}")



def ingest_transcripts(
    symbol: str,
    client: Client,
    metrics: IngestionMetrics,
    max_recent: int = 8,
) -> int:
    """Ingest last `max_recent` transcript PDFs for a stock.

    Returns count of successfully ingested transcripts.
    """
    try:
        announcements = fetch_announcements(symbol)
    except Exception as exc:
        print(f"[transcript_ingester] {symbol}: NSE API failed: {exc}")
        metrics.record_error()
        return 0

    entries = get_transcript_entries(announcements, max_recent=max_recent)
    if not entries:
        return 0

    success = 0
    for entry in entries:
        nse_url = entry["url"]
        filing_date = entry.get("filing_date", "")
        quarter = entry.get("quarter") or None

        # Gate 1 — Intimation letter: detect + follow company IR URL
        result: FetchResult = download_and_extract_with_fallback(nse_url, filing_date=filing_date)
        text, actual_url = result.text, result.url

        # Update fetch-stage metrics
        if result.is_letter and result.url_method:
            url_method_str = result.url_method
            base_method = url_method_str.split("_")[0]  # strip "_fail" / "_short" suffix
            metrics.record_fetch(base_method, recovered=result.recovered)
            if url_method_str.endswith("_fail"):
                metrics.pdf_download_fail += 1
            else:
                metrics.pdf_download_ok += 1
            if base_method == "webpage":
                metrics.webpages_scraped += 1

        if not text:
            print(f"[transcript_ingester] {symbol}: empty text from {nse_url}")
            _log_rejection(
                client, symbol, nse_url, "pdf_download_failed",
                quarter=quarter,
                notes="download_and_extract_with_fallback returned empty string",
            )
            metrics.record_error()
            continue

        # Gate 2 — Minimum text length
        if len(text) < MIN_TEXT_CHARS:
            # Distinguish: letter with IR webpage URL vs letter with no URL at all
            if result.is_letter and result.url_method is None:
                any_url = extract_any_url(text)
                if any_url and not any_url.lower().endswith(".pdf"):
                    reason = "transcript_on_webpage"
                    notes = f"IR page (requires scraping): {any_url}"
                else:
                    reason = "text_too_short"
                    notes = f"text={len(text)} chars; no URL in letter"
            elif result.url_method and "_fail" in result.url_method:
                reason = "text_too_short"
                notes = f"URL download failed ({result.url_method}); text={len(text)} chars"
            else:
                reason = "text_too_short"
                notes = f"actual_url={actual_url}; text={len(text)} chars"
            print(
                f"[transcript_ingester] {symbol}: {reason} "
                f"({len(text)} chars) — {actual_url}"
            )
            _log_rejection(
                client, symbol, nse_url, reason,
                quarter=quarter,
                company_url=actual_url if actual_url != nse_url else None,
                text_length=len(text),
                notes=notes,
            )
            metrics.record_error()
            continue

        chunks = chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)

        # Gate 3 — Minimum chunk count
        if len(chunks) < MIN_CHUNKS:
            print(
                f"[transcript_ingester] {symbol}: too few chunks "
                f"({len(chunks)}) — {actual_url}"
            )
            _log_rejection(
                client, symbol, nse_url, "too_few_chunks",
                quarter=quarter,
                company_url=actual_url if actual_url != nse_url else None,
                text_length=len(text),
                chunk_count=len(chunks),
            )
            metrics.record_error()
            continue

        # Gate 4 — Keyword validation
        score = _keyword_score(text)
        if score < _MIN_KEYWORD_SCORE:
            print(
                f"[transcript_ingester] {symbol}: keyword score {score} < {_MIN_KEYWORD_SCORE} "
                f"— likely not a real transcript: {actual_url}"
            )
            _log_rejection(
                client, symbol, nse_url, "keyword_validation_failed",
                quarter=quarter,
                company_url=actual_url if actual_url != nse_url else None,
                text_length=len(text),
                chunk_count=len(chunks),
                notes=f"keyword_score={score}",
            )
            metrics.record_error()
            continue

        try:
            vectors = embed_texts(chunks)
        except Exception as exc:
            print(f"[transcript_ingester] {symbol} embedding failed: {exc}")
            metrics.record_error()
            continue

        rows = [
            {
                "symbol": symbol,
                "document_type": "transcript",
                "quarter": entry["quarter"],
                "fiscal_year": entry["fiscal_year"],
                "filing_date": entry["filing_date"] or None,
                "pdf_url": actual_url,
                "title": f"{symbol} - {entry['title']}",
                "chunk_index": i,
                "chunk_text": chunk,
                "embedding": vector,
                "discovery_source": "nse_filing",
                "retrieval_method": result.url_method or "direct",
            }
            for i, (chunk, vector) in enumerate(zip(chunks, vectors))
        ]
        try:
            client.table("corporate_documents").upsert(
                rows, on_conflict="pdf_url,chunk_index"
            ).execute()
        except Exception as exc:
            print(f"[transcript_ingester] {symbol} upsert failed: {exc}")
            metrics.record_error()
            continue

        metrics.record_pdf(chunks=len(chunks), embeddings=len(chunks))

        # Structured insights extraction (guidance, capex, risks)
        try:
            extract_and_store_insights(client, symbol, entry, text)
        except Exception as exc:
            print(f"[transcript_ingester] {symbol} insight extraction failed: {exc}")

        success += 1

    return success
