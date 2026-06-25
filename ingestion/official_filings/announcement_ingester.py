"""
Ingest NSE corporate announcement text into official_filings.

NSE's corporate-announcements API returns structured metadata + the full
announcement text (attchmntText) for every filing. Unlike transcripts and
annual reports, no PDF download is required — the text is already in the API
response.

What gets stored:
  - Board meeting outcomes (decisions on dividends, buybacks, capex, M&A)
  - Financial result summaries and press releases
  - Shareholding pattern disclosures
  - SEBI regulatory filings and intimation letters (when they contain text)
  - Capital market communications

Filtering logic:
  - Min 200 chars (skip one-line boilerplate)
  - Skip pure intimation letters (text = "please find below link ...")
  - Max 50 most-recent announcements per symbol (~2–3 years coverage)

Storage:
  - Table: official_filings  (filing_type = 'announcement')
  - Dedup key: (pdf_url, chunk_index) — pdf_url = stable pseudo-URL
    nse://annc/{symbol}/{YYYY-MM-DD}/{8-char-hash}

The pseudo-URL is deterministic: same announcement always produces the same
key, so re-running is fully idempotent.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from supabase import Client

from embeddings.embedder import embed_texts
from ingestion.nse_bse.pdf_processor import chunk_text
from ingestion.official_filings.nse_fetcher import (
    fetch_announcements,
    is_intimation_letter,
    parse_filing_date,
    infer_quarter,
)
from monitoring.metrics import IngestionMetrics

CHUNK_SIZE = 400
CHUNK_OVERLAP = 40
MIN_TEXT_CHARS = 200
MAX_ANNOUNCEMENTS = 50

# NSE announcement categories worth indexing (desc field from the API).
# Omit purely administrative filings with no investor-relevant text.
_SKIP_CATEGORIES = frozenset({
    "Compliance Certificate",
    "Reg-7",
    "Reg 7",
    "Secretarial Compliance Report",
    "Annual Secretarial Compliance Report",
    "Statement of Investor Complaints",
    "Reconciliation of Share Capital Audit Report",
})


def _pseudo_url(symbol: str, filing_date: str, text: str) -> str:
    """Stable dedup key: deterministic from content, never changes on re-run."""
    h = hashlib.sha256(text[:500].encode()).hexdigest()[:8]
    return f"nse://annc/{symbol}/{filing_date}/{h}"


def _is_worth_indexing(ann: dict) -> bool:
    text = ann.get("attchmntText", "")
    if len(text) < MIN_TEXT_CHARS:
        return False
    if is_intimation_letter(text):
        return False
    category = ann.get("desc", "")
    if category in _SKIP_CATEGORIES:
        return False
    return True


def _already_stored(client: Client, pseudo_url: str) -> bool:
    resp = (
        client.table("official_filings")
        .select("id")
        .eq("pdf_url", pseudo_url)
        .limit(1)
        .execute()
    )
    return bool(resp.data)


def ingest_announcements(
    symbol: str,
    client: Client,
    metrics: IngestionMetrics,
    max_recent: int = MAX_ANNOUNCEMENTS,
) -> int:
    """Ingest recent NSE corporate announcements for *symbol*.

    Returns number of announcement documents successfully stored.
    """
    try:
        all_announcements = fetch_announcements(symbol)
    except Exception as exc:
        print(f"[announcement_ingester] {symbol}: NSE API failed: {exc}")
        metrics.record_error()
        return 0

    candidates = [a for a in all_announcements if _is_worth_indexing(a)][:max_recent]
    if not candidates:
        print(f"[announcement_ingester] {symbol}: no indexable announcements")
        return 0

    success = 0
    for ann in candidates:
        text = ann.get("attchmntText", "")
        filing_date = parse_filing_date(ann.get("an_dt", ""))
        quarter, fiscal_year = infer_quarter(filing_date)
        category = ann.get("desc", "Corporate Announcement")
        pseudo_url = _pseudo_url(symbol, filing_date, text)

        if _already_stored(client, pseudo_url):
            continue

        chunks = chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        if not chunks:
            continue

        try:
            vectors = embed_texts(chunks)
        except Exception as exc:
            print(f"[announcement_ingester] {symbol} embed failed: {exc}")
            metrics.record_error()
            continue

        rows = [
            {
                "symbol": symbol,
                "filing_type": "announcement",
                "quarter": quarter or None,
                "fiscal_year": fiscal_year or None,
                "filing_date": filing_date or None,
                "pdf_url": pseudo_url,
                "title": f"{symbol} — {category} — {filing_date}",
                "chunk_index": i,
                "chunk_text": chunk,
                "embedding": vector,
            }
            for i, (chunk, vector) in enumerate(zip(chunks, vectors))
        ]
        try:
            client.table("official_filings").upsert(
                rows, on_conflict="pdf_url,chunk_index"
            ).execute()
        except Exception as exc:
            print(f"[announcement_ingester] {symbol} upsert failed: {exc}")
            metrics.record_error()
            continue

        metrics.record_pdf(chunks=len(chunks), embeddings=len(chunks))
        success += 1
        print(f"[announcement_ingester] {symbol} [{filing_date}] {category[:50]}: {len(chunks)} chunks")

    return success
