"""
Nifty50 full ingestion — all 5 document types for all 50 symbols.

Run order:
  1. annual      — annual reports (discovery + embed, skips already-ingested)
  2. transcripts — earnings call transcripts (skips already-ingested)
  3. quarterly   — quarterly result PDFs
  4. presentations — investor presentation PDFs
  5. announcements — NSE announcement text (no PDF, direct from API)

Usage:
  python scripts/run_nifty50_all.py
  python scripts/run_nifty50_all.py --mode annual
  python scripts/run_nifty50_all.py --mode presentations,quarterly
  python scripts/run_nifty50_all.py --symbol TCS
  python scripts/run_nifty50_all.py --skip-annual     # skip annual (slow), run the rest

Environment: SUPABASE_URL, SUPABASE_SERVICE_KEY, OPENAI_API_KEY
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client

from config.nifty50 import NIFTY50_COMPANIES, NIFTY50_SYMBOLS
from monitoring.metrics import IngestionMetrics
from ingestion.official_filings.transcript_ingester import ingest_transcripts
from ingestion.official_filings.presentation_ingester import ingest_presentations
from ingestion.official_filings.quarterly_results_ingester import ingest_quarterly_results
from ingestion.official_filings.annual_report_ingester import ingest_annual_report
from ingestion.official_filings.announcement_ingester import ingest_announcements
from ingestion.official_filings.annual_report_discovery import discover_annual_reports

ALL_MODES = ["annual", "transcripts", "quarterly", "presentations", "announcements"]


def _client():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def run_symbol(symbol: str, modes: list[str], client, metrics: IngestionMetrics) -> dict:
    result = {m: 0 for m in ALL_MODES}
    result["symbol"] = symbol
    t0 = time.perf_counter()

    if "annual" in modes:
        try:
            reports = discover_annual_reports(symbol, client, max_years=3)
            for report in reports:
                n = ingest_annual_report(symbol, report, client, metrics)
                result["annual"] += n
        except Exception as exc:
            print(f"  [annual] {symbol}: {exc}")
            metrics.record_error()

    if "transcripts" in modes:
        try:
            result["transcripts"] = ingest_transcripts(symbol, client, metrics)
        except Exception as exc:
            print(f"  [transcripts] {symbol}: {exc}")
            metrics.record_error()

    if "quarterly" in modes:
        try:
            result["quarterly"] = ingest_quarterly_results(symbol, client, metrics)
        except Exception as exc:
            print(f"  [quarterly] {symbol}: {exc}")
            metrics.record_error()

    if "presentations" in modes:
        try:
            result["presentations"] = ingest_presentations(symbol, client, metrics)
        except Exception as exc:
            print(f"  [presentations] {symbol}: {exc}")
            metrics.record_error()

    if "announcements" in modes:
        try:
            result["announcements"] = ingest_announcements(symbol, client, metrics)
        except Exception as exc:
            print(f"  [announcements] {symbol}: {exc}")
            metrics.record_error()

    result["elapsed"] = round(time.perf_counter() - t0, 1)
    return result


def print_summary(results: list[dict], modes: list[str]) -> None:
    print("\n" + "=" * 75)
    print(f"NIFTY50 INGESTION SUMMARY  ({', '.join(modes)})")
    print("=" * 75)
    header = f"{'SYMBOL':<14}" + "".join(f"{m[:6]:>8}" for m in modes) + f"{'TIME':>7}"
    print(header)
    print("-" * 75)

    totals = defaultdict(int)
    for r in sorted(results, key=lambda x: x["symbol"]):
        sym = r["symbol"]
        counts = "".join(f"{r.get(m, 0):>8}" for m in modes)
        elapsed = r.get("elapsed", 0)
        print(f"{sym:<14}{counts}{elapsed:>7.1f}s")
        for m in modes:
            totals[m] += r.get(m, 0)

    print("-" * 75)
    total_line = "TOTAL" + " " * 9 + "".join(f"{totals[m]:>8}" for m in modes)
    print(total_line)

    total_chunks = sum(totals.values())
    est_cost = total_chunks * 550 / 1_000_000 * 0.020
    print(f"\nTotal new chunks: {total_chunks:,}")
    print(f"Est. embed cost : ${est_cost:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Nifty50 full document ingestion")
    parser.add_argument("--mode", default=",".join(ALL_MODES),
                        help=f"Comma-separated modes: {','.join(ALL_MODES)}")
    parser.add_argument("--symbol", help="Run for a single symbol only")
    parser.add_argument("--skip-annual", action="store_true",
                        help="Skip annual reports (slow, use to run other types quickly)")
    args = parser.parse_args()

    modes = [m.strip() for m in args.mode.split(",") if m.strip() in ALL_MODES]
    if args.skip_annual and "annual" in modes:
        modes.remove("annual")

    if not modes:
        print("No valid modes specified.")
        sys.exit(1)

    symbols = [args.symbol.upper()] if args.symbol else NIFTY50_SYMBOLS

    print(f"\nNifty50 ingestion — {len(symbols)} symbols, modes: {', '.join(modes)}")
    print("=" * 75)

    client = _client()
    metrics = IngestionMetrics("nifty50_all")
    results = []

    for i, symbol in enumerate(symbols, 1):
        print(f"\n[{i:02d}/{len(symbols)}] {symbol} ({NIFTY50_COMPANIES.get(symbol, '')})")
        r = run_symbol(symbol, modes, client, metrics)
        results.append(r)
        chunks_this = sum(r.get(m, 0) for m in modes)
        print(f"  → {chunks_this} new chunks in {r['elapsed']}s")

    print_summary(results, modes)
    metrics.finish(client=client, metadata={"modes": modes, "symbols": len(symbols)})


if __name__ == "__main__":
    main()
