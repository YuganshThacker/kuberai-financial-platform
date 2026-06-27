"""
Supplemental annual report ingestion for Nifty50.

Runs AFTER run_nifty50_annual_reports.py to pick up:
  1. Symbols with 0 annual report chunks (FY2026/FY2025 were thin, need to reach FY2024/FY2023)
  2. Symbols with partial ingestion (upsert timeout cut off last batch)

Strategy:
  - max_years=5  — reaches back 5 fiscal years to find full annual reports
  - _UPSERT_BATCH=25 (in annual_report_ingester.py) — avoids HNSW index timeouts
  - discovery skips FY years already fully ingested (≥200 chunks)
  - For partially-ingested FY years: re-delete + re-ingest via --repair flag

Usage:
    python scripts/run_nifty50_supplemental.py [--dry-run] [--symbol AXISBANK] [--repair]
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client

from config.nifty50 import NIFTY50_SYMBOLS
from ingestion.official_filings.annual_report_discovery import discover_annual_reports
from ingestion.official_filings.annual_report_ingester import (
    MIN_ANNUAL_REPORT_CHUNKS,
    ingest_annual_report,
)
from monitoring.metrics import IngestionMetrics


def _client():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def _chunk_count_for_year(client, symbol: str, fiscal_year: str) -> int:
    """Return number of annual report chunks stored for this symbol+FY."""
    rows = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            client.table("corporate_documents")
            .select("id")
            .eq("symbol", symbol)
            .eq("document_type", "annual_report")
            .eq("fiscal_year", fiscal_year)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return len(rows)


def _get_zero_chunk_symbols(client, symbols: list[str]) -> list[str]:
    """Return symbols with 0 annual report chunks in the DB."""
    zero = []
    for symbol in symbols:
        rows = []
        page_size = 1000
        offset = 0
        while True:
            resp = (
                client.table("corporate_documents")
                .select("id")
                .eq("symbol", symbol)
                .eq("document_type", "annual_report")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            batch = resp.data or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        if len(rows) == 0:
            zero.append(symbol)
    return zero


def _delete_partial_year(client, symbol: str, fiscal_year: str) -> int:
    """Delete all annual report chunks for symbol+FY (for repair runs)."""
    # Paginated delete via upsert trick — Supabase doesn't expose bulk delete easily
    count = 0
    while True:
        resp = (
            client.table("corporate_documents")
            .select("id")
            .eq("symbol", symbol)
            .eq("document_type", "annual_report")
            .eq("fiscal_year", fiscal_year)
            .limit(100)
            .execute()
        )
        ids = [r["id"] for r in (resp.data or [])]
        if not ids:
            break
        for row_id in ids:
            client.table("corporate_documents").delete().eq("id", row_id).execute()
            count += 1
    return count


_PILOT_SYMBOLS = frozenset({"HDFCBANK", "ICICIBANK", "INFY", "RELIANCE", "TCS"})

# Partials at exactly 200 chunks (8 batches × 25) are caught by threshold > 200.
# Threshold 250 is safely below the smallest confirmed-complete ingestion (328).
_REPAIR_THRESHOLD = 250


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Run for a single symbol only")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repair", action="store_true",
                        help="Delete and re-ingest partially-stored FY years (< 250 chunks)")
    args = parser.parse_args()

    client = _client()
    metrics = IngestionMetrics("nifty50_supplemental")

    if args.symbol:
        symbols = [args.symbol.upper()]
        if args.repair:
            symbol = symbols[0]
            for fy in ["2026", "2025", "2024", "2023", "2022"]:
                n = _chunk_count_for_year(client, symbol, fy)
                if 0 < n < _REPAIR_THRESHOLD:
                    print(f"  Deleting partial {symbol} FY{fy} ({n} chunks < {_REPAIR_THRESHOLD})")
                    if not args.dry_run:
                        deleted = _delete_partial_year(client, symbol, fy)
                        print(f"  Deleted {deleted} rows for FY{fy}")
    else:
        if args.repair:
            # Global scan: delete partial FY years for all non-pilot symbols.
            # Catches exactly-200-chunk partials (8×25 batches before timeout).
            print(f"Global repair scan: checking all {len(NIFTY50_SYMBOLS)} symbols for partial FY years...")
            for sym in NIFTY50_SYMBOLS:
                if sym in _PILOT_SYMBOLS:
                    continue
                for fy in ["2026", "2025", "2024", "2023", "2022"]:
                    n = _chunk_count_for_year(client, sym, fy)
                    if 0 < n < _REPAIR_THRESHOLD:
                        print(f"  Deleting partial {sym} FY{fy} ({n} chunks < {_REPAIR_THRESHOLD})")
                        if not args.dry_run:
                            deleted = _delete_partial_year(client, sym, fy)
                            print(f"  Deleted {deleted} rows for {sym} FY{fy}")

        print("\nScanning for symbols with 0 annual report chunks...")
        zero_symbols = _get_zero_chunk_symbols(client, NIFTY50_SYMBOLS)
        symbols = zero_symbols
        print(f"Found {len(symbols)} symbols with 0 chunks: {', '.join(sorted(symbols))}")

    if not symbols:
        print("No symbols need supplemental ingestion.")
        return

    print(f"\nSupplemental ingestion — {len(symbols)} symbols, max_years=5\n" + "=" * 60)

    results = {}
    for i, symbol in enumerate(symbols, 1):
        print(f"\n[{i:02d}/{len(symbols)}] {symbol}")

        if args.repair and args.symbol:
            # Per-symbol repair already done above before the loop
            pass

        try:
            reports = discover_annual_reports(symbol, client, max_years=5)
        except Exception as exc:
            print(f"  discovery failed: {exc}")
            results[symbol] = {"status": "discovery_failed", "chunks": 0, "error": str(exc)}
            continue

        if not reports:
            print(f"  no annual reports found in NSE feed")
            results[symbol] = {"status": "no_reports", "chunks": 0}
            continue

        symbol_chunks = 0
        for report in reports:
            fy = report["fiscal_year"]
            chars = report["text_len"]
            print(f"  FY{fy}: {chars:,} chars {'(DRY RUN)' if args.dry_run else ''}")
            if not args.dry_run:
                n = ingest_annual_report(symbol, report, client, metrics)
                symbol_chunks += n

        results[symbol] = {"status": "success", "chunks": symbol_chunks}
        print(f"  → {symbol_chunks} chunks")

    print("\n" + "=" * 60)
    print("SUPPLEMENTAL SUMMARY")
    print("=" * 60)
    success = [s for s, r in results.items() if r.get("chunks", 0) > 0]
    failed = [s for s, r in results.items() if r.get("chunks", 0) == 0]
    print(f"Stored chunks: {sum(r.get('chunks',0) for r in results.values())}")
    print(f"Symbols with chunks: {sorted(success)}")
    print(f"Symbols still 0: {sorted(failed)}")


if __name__ == "__main__":
    main()
