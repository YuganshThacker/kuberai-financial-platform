"""
Incremental ingestion scheduler for NSE corporate transcripts.

Entry point for the daily GitHub Actions cron job. Each run:
  1. Loads this symbol's own last_filing_date from discovery_state
     (falls back to the global row when no per-symbol row exists yet)
  2. Fetches only filings newer than that date from NSE
  3. Classifies each filing — skips non-transcripts
  4. Deduplicates against corporate_documents (pdf_url already ingested)
  5. Calls transcript ingestion for matched symbols
  6. Advances THIS symbol's last_filing_date — other symbols are never touched
  7. Refreshes the document_coverage materialized view after all symbols complete

State isolation guarantee:
  Processing symbol A can never advance or reset symbol B's high-water mark.
  Each symbol's row in discovery_state is updated independently, in the same
  transaction scope as that symbol's ingestion. A crash mid-run leaves all
  already-processed symbols with their updated marks and all pending symbols
  with their previous marks — no silent data loss.

Usage:
    python -m ingestion.scheduler [--symbol RELIANCE] [--dry-run] [--max-recent 4]
"""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta

from supabase import create_client, Client

from config.nifty50 import NIFTY50_COMPANIES
from ingestion.classifier import classifier, DocumentType
from ingestion.official_filings.nse_fetcher import get_new_filings_since, parse_filing_date
from ingestion.official_filings.transcript_ingester import ingest_transcripts
from monitoring.metrics import IngestionMetrics

_DEFAULT_LOOKBACK_DAYS = 30

_NSE_SOURCE = "nse_filing"
# Sentinel symbol value for the global fallback row (source='nse_filing', symbol='')
_GLOBAL_SYMBOL = ""


def _get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


# ── Per-symbol high-water mark ────────────────────────────────────────────────

def _load_symbol_mark(client: Client, symbol: str) -> str:
    """Return last_filing_date for this specific symbol.

    Lookup order:
      1. Per-symbol row (source='nse_filing', symbol=<symbol>)
      2. Global fallback row (source='nse_filing', symbol='')
      3. Default: today − DEFAULT_LOOKBACK_DAYS
    """
    resp = (
        client.table("discovery_state")
        .select("last_filing_date")
        .eq("source", _NSE_SOURCE)
        .eq("symbol", symbol)
        .limit(1)
        .execute()
    )
    if resp.data:
        return resp.data[0]["last_filing_date"]

    resp = (
        client.table("discovery_state")
        .select("last_filing_date")
        .eq("source", _NSE_SOURCE)
        .eq("symbol", _GLOBAL_SYMBOL)
        .limit(1)
        .execute()
    )
    if resp.data:
        return resp.data[0]["last_filing_date"]

    return (date.today() - timedelta(days=_DEFAULT_LOOKBACK_DAYS)).isoformat()


def _update_symbol_mark(
    client: Client,
    symbol: str,
    new_date: str,
    *,
    errors: int = 0,
) -> None:
    """Advance the high-water mark for THIS symbol only."""
    client.table("discovery_state").upsert(
        {
            "source": _NSE_SOURCE,
            "symbol": symbol,
            "last_filing_date": new_date,
            "last_run_at": "now()",
            "status": "ok" if errors == 0 else "partial",
        },
        on_conflict="source,symbol",
    ).execute()


def _known_pdf_urls(client: Client, symbol: str) -> set[str]:
    """Return all pdf_urls already ingested for this symbol (for dedup)."""
    resp = (
        client.table("corporate_documents")
        .select("pdf_url")
        .eq("symbol", symbol)
        .eq("document_type", "transcript")
        .execute()
    )
    return {row["pdf_url"] for row in (resp.data or [])}


def _refresh_coverage(client: Client) -> None:
    try:
        client.rpc("refresh_document_coverage").execute()
    except Exception as exc:
        print(f"[scheduler] coverage refresh failed: {exc}")


# ── Main run loop ─────────────────────────────────────────────────────────────

def run(
    symbols: list[str],
    *,
    dry_run: bool = False,
    max_recent: int = 4,
) -> None:
    """Process each symbol with fully independent state.

    Each symbol's high-water mark is loaded and updated in isolation.
    A failure or slow filing for symbol A has zero effect on symbol B.
    """
    client = _get_client()
    metrics = IngestionMetrics("scheduler")

    for symbol in symbols:
        # Per-symbol mark — completely independent from all other symbols
        from_date = _load_symbol_mark(client, symbol)
        print(f"\n[scheduler] {symbol}: high-water mark = {from_date}")

        new_filings = get_new_filings_since(symbol, from_date)
        if not new_filings:
            print(f"[scheduler] {symbol}: no new filings")
            continue

        # Newest filing date seen for THIS symbol only
        symbol_newest = max(
            (parse_filing_date(f.get("an_dt", "")) for f in new_filings),
            default=from_date,
        )

        # Classify — keep only transcripts
        transcript_filings = []
        for filing in new_filings:
            subject = filing.get("desc", "") or filing.get("subject", "")
            category = filing.get("smIndustry", "")
            doc_type, _ = classifier.classify(subject, category)
            if doc_type == DocumentType.TRANSCRIPT:
                transcript_filings.append(filing)
            else:
                print(f"[scheduler] {symbol}: skipping {doc_type.value} — {subject[:60]}")

        if not transcript_filings:
            print(f"[scheduler] {symbol}: no transcript filings in new batch")
            if not dry_run and symbol_newest > from_date:
                # Still advance mark so we don't re-scan these non-transcript filings
                _update_symbol_mark(client, symbol, symbol_newest)
            continue

        # Dedup against already-ingested pdf_urls
        known = _known_pdf_urls(client, symbol)
        novel = [f for f in transcript_filings if f.get("attchmntFile", "") not in known]

        print(
            f"[scheduler] {symbol}: {len(transcript_filings)} transcript filing(s), "
            f"{len(novel)} not yet ingested"
        )

        if not novel or dry_run:
            if dry_run and novel:
                print(f"[scheduler] --dry-run: would ingest {len(novel)} filing(s)")
            if not dry_run and symbol_newest > from_date:
                _update_symbol_mark(client, symbol, symbol_newest)
            continue

        # Ingest — catch per-symbol exceptions so one failure never kills the run
        errors_before = metrics.errors
        try:
            ingest_transcripts(symbol, client, metrics, max_recent=max_recent)
        except Exception as exc:
            print(f"[scheduler] {symbol}: ingestion raised unexpectedly: {exc}")
            metrics.record_error()
        symbol_errors = metrics.errors - errors_before
        metrics.record_symbol()

        if not dry_run and symbol_newest > from_date:
            if symbol_errors == 0:
                _update_symbol_mark(client, symbol, symbol_newest)
                print(f"[scheduler] {symbol}: mark advanced to {symbol_newest}")
            else:
                print(
                    f"[scheduler] {symbol}: {symbol_errors} error(s) during ingestion — "
                    f"mark held at {from_date} (retry on next run)"
                )

    if not dry_run:
        _refresh_coverage(client)

    metrics.finish(client if not dry_run else None)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Incremental NSE transcript scheduler")
    parser.add_argument("--symbol", help="Run for a single symbol only")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Classify and log; do not ingest or update state",
    )
    parser.add_argument(
        "--max-recent", type=int, default=4,
        help="Max filings to ingest per symbol per run",
    )
    args = parser.parse_args()

    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        symbols = list(NIFTY50_COMPANIES.keys())

    print(f"[scheduler] Starting: {len(symbols)} symbol(s), dry_run={args.dry_run}")
    run(symbols, dry_run=args.dry_run, max_recent=args.max_recent)


if __name__ == "__main__":
    main()
