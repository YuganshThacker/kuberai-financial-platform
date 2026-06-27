"""
Annual report pilot: ingest and validate FY2026 annual reports for 5 symbols.

Runs discovery + ingestion, then executes 5 retrieval queries to confirm
semantic search works across document_type='annual_report'.

Usage:
    python scripts/run_annual_report_pilot.py [--symbol RELIANCE] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client

from embeddings.embedder import embed_texts
from ingestion.official_filings.annual_report_discovery import discover_annual_reports
from ingestion.official_filings.annual_report_ingester import ingest_annual_report
from monitoring.metrics import IngestionMetrics

PILOT_SYMBOLS = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]

_RETRIEVAL_QUERIES = [
    ("revenue growth",      "What was the company's revenue growth and key revenue drivers?"),
    ("capex",               "What were the capital expenditure plans and investments?"),
    ("management outlook",  "What is management's business outlook and strategic priorities?"),
    ("risks",               "What are the key business risks and mitigation strategies?"),
    ("segment performance", "What was the performance by business segment or geography?"),
]


def _client():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


# ── Ingestion phase ───────────────────────────────────────────────────────────

def run_ingestion(symbols: list[str], client, dry_run: bool = False) -> dict[str, int]:
    """Discover and ingest annual reports. Returns {symbol: chunks_stored}."""
    results = {}
    total_metrics = IngestionMetrics("annual_report_pilot")

    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"[pilot] {symbol}: discovering annual reports...")
        t0 = time.perf_counter()

        try:
            reports = discover_annual_reports(symbol, client, max_years=2)
        except Exception as exc:
            print(f"[pilot] {symbol}: discovery failed: {exc}")
            results[symbol] = 0
            continue

        if not reports:
            print(f"[pilot] {symbol}: no annual reports found in NSE feed")
            results[symbol] = 0
            continue

        symbol_chunks = 0
        for report in reports:
            print(
                f"[pilot] {symbol} FY{report['fiscal_year']}: "
                f"{report['text_len']:,} chars "
                f"({'DRY RUN — skipping embed/store' if dry_run else 'ingesting...'})"
            )
            if dry_run:
                continue
            n = ingest_annual_report(symbol, report, client, total_metrics)
            symbol_chunks += n

        results[symbol] = symbol_chunks
        elapsed = time.perf_counter() - t0
        print(f"[pilot] {symbol}: {symbol_chunks} chunks stored in {elapsed:.1f}s")

    return results


# ── Retrieval validation phase ────────────────────────────────────────────────

def run_retrieval_tests(symbols: list[str], client) -> None:
    """Run 5 semantic queries per symbol; report hit count and top similarity."""
    print(f"\n{'='*60}")
    print("RETRIEVAL VALIDATION")
    print(f"{'='*60}")
    print(f"{'SYMBOL':<14} {'QUERY':<22} {'HITS':>5} {'TOP SIM':>10} {'SECTION':>20}")
    print("-" * 75)

    for symbol in symbols:
        for query_label, query_text in _RETRIEVAL_QUERIES:
            try:
                vector = embed_texts([query_text])[0]
                resp = client.rpc(
                    "match_annual_report_chunks",
                    {
                        "query_embedding": vector,
                        "match_count": 5,
                        "symbol_filter": symbol,
                    },
                ).execute()
                hits = resp.data or []
                if hits:
                    top = hits[0]
                    sim = top.get("similarity", 0)
                    section = top.get("section_type", "—") or "—"
                    print(
                        f"{symbol:<14} {query_label:<22} {len(hits):>5} "
                        f"{sim:>10.3f} {section:>20}"
                    )
                else:
                    print(f"{symbol:<14} {query_label:<22} {'0':>5} {'—':>10} {'no hits':>20}")
            except Exception as exc:
                print(f"{symbol:<14} {query_label:<22} ERROR: {exc}")


# ── Coverage summary ──────────────────────────────────────────────────────────

def print_coverage(symbols: list[str], client) -> None:
    print(f"\n{'='*60}")
    print("ANNUAL REPORT COVERAGE")
    print(f"{'='*60}")

    # Paginate: Supabase default limit is 1000 rows; annual reports can exceed this.
    rows = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            client.table("corporate_documents")
            .select("symbol,fiscal_year,section_type,pdf_url")
            .eq("document_type", "annual_report")
            .in_("symbol", symbols)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    by_symbol: dict[str, dict] = {}
    for r in rows:
        sym = r["symbol"]
        fy = r["fiscal_year"]
        key = f"{sym}|{fy}"
        if key not in by_symbol:
            by_symbol[key] = {"symbol": sym, "fy": fy, "chunks": 0, "sections": set()}
        by_symbol[key]["chunks"] += 1
        if r.get("section_type"):
            by_symbol[key]["sections"].add(r["section_type"])

    print(f"{'SYMBOL':<14} {'FY':<6} {'CHUNKS':>8} {'SECTIONS'}")
    print("-" * 60)
    for entry in sorted(by_symbol.values(), key=lambda x: (x["symbol"], x["fy"])):
        print(
            f"{entry['symbol']:<14} {entry['fy']:<6} {entry['chunks']:>8} "
            f"{', '.join(sorted(entry['sections']))}"
        )

    total_chunks = sum(e["chunks"] for e in by_symbol.values())
    print(f"\nTotal annual report chunks: {total_chunks:,}")
    est_embed_cost = total_chunks * 550 / 1_000_000 * 0.020
    print(f"Estimated embedding cost: ${est_embed_cost:.4f}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Run for a single symbol only")
    parser.add_argument("--dry-run", action="store_true",
                        help="Discover only, skip embedding and storage")
    parser.add_argument("--retrieval-only", action="store_true",
                        help="Skip ingestion, only run retrieval tests")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else PILOT_SYMBOLS
    client = _client()

    if not args.retrieval_only:
        results = run_ingestion(symbols, client, dry_run=args.dry_run)
        print(f"\n[pilot] Ingestion summary: {results}")

    if not args.dry_run:
        print_coverage(symbols, client)
        run_retrieval_tests(symbols, client)


if __name__ == "__main__":
    main()
