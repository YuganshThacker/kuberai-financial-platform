"""
Dry-run the transcript fetch pipeline without any OpenAI calls.

Tests URL extraction, webpage scraping, and PDF validation for every
NSE announcement entry — prints per-symbol recovery rates and stage
counters so you can measure the fallback chain's effectiveness offline.

Usage:
    python3 scripts/test_scraper.py [--symbol SYM [SYM ...]] [--max-recent N]

Examples:
    python3 scripts/test_scraper.py --symbol BPCL KOTAKBANK MARUTI ONGC LT JSWSTEEL
    python3 scripts/test_scraper.py                        # all Nifty50 symbols
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from config.nifty50 import NIFTY50_SYMBOLS
from ingestion.official_filings.nse_fetcher import (
    FetchResult,
    download_and_extract_with_fallback,
    fetch_announcements,
    get_transcript_entries,
    is_intimation_letter,
)
from ingestion.nse_bse.pdf_processor import chunk_text

# Quality gate thresholds (must match transcript_ingester.py)
MIN_TEXT_CHARS = 3_000
MIN_CHUNKS = 5

CHUNK_SIZE = 400
CHUNK_OVERLAP = 40


def _gate_status(text: str) -> str:
    if not text:
        return "EMPTY"
    if len(text) < MIN_TEXT_CHARS:
        return f"SHORT({len(text)})"
    chunks = chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    if len(chunks) < MIN_CHUNKS:
        return f"FEW_CHUNKS({len(chunks)})"
    return f"OK({len(text)} chars, {len(chunks)} chunks)"


def _method_label(result: FetchResult) -> str:
    if not result.is_letter:
        return "direct"
    return result.url_method or "no_url"


def run(symbols: list[str], max_recent: int = 8) -> None:
    # Stage counters
    stage = defaultdict(int)
    per_symbol: dict[str, dict] = {}

    for symbol in symbols:
        t0 = time.time()
        try:
            anns = fetch_announcements(symbol)
        except Exception as exc:
            print(f"[{symbol}] NSE API failed: {exc}")
            stage["api_error"] += 1
            continue

        entries = get_transcript_entries(anns, max_recent=max_recent)
        if not entries:
            print(f"[{symbol}] No transcript entries found")
            stage["no_entries"] += 1
            continue

        ok = 0
        fail = 0
        details = []

        for entry in entries:
            nse_url = entry["url"]
            filing_date = entry.get("filing_date", "")

            result = download_and_extract_with_fallback(nse_url, filing_date=filing_date)
            status = _gate_status(result.text)
            method = _method_label(result)
            stage[f"method_{method}"] += 1

            if status.startswith("OK"):
                ok += 1
                stage["gate_ok"] += 1
            else:
                fail += 1
                stage[f"gate_{status.split('(')[0].lower()}"] += 1

            details.append({
                "quarter": entry.get("quarter", ""),
                "date": filing_date,
                "method": method,
                "status": status,
                "recovered": result.recovered,
            })

        per_symbol[symbol] = {"ok": ok, "fail": fail, "total": len(entries), "details": details}
        elapsed = round(time.time() - t0, 1)
        rate = round(100 * ok / len(entries)) if entries else 0
        print(
            f"[{symbol}] {ok}/{len(entries)} recovered ({rate}%) in {elapsed}s"
        )
        for d in details:
            mark = "✓" if d["status"].startswith("OK") else "✗"
            print(f"  {mark} {d['quarter']} {d['date']} [{d['method']}] {d['status']}")

    # ── Summary ────────────────────────────────────────────────────────────
    total = sum(s["total"] for s in per_symbol.values())
    total_ok = sum(s["ok"] for s in per_symbol.values())

    print()
    print("=" * 70)
    print(f"TOTAL: {total_ok}/{total} transcripts recoverable ({round(100*total_ok/total) if total else 0}%)")
    print()
    print("Stage counters:")
    for k in sorted(stage):
        print(f"  {k:<40} {stage[k]:>4}")

    print()
    print("Per-symbol summary:")
    header = f"{'Symbol':<14} {'OK':>3} {'Fail':>4} {'Total':>5}  {'Rate':>5}"
    print(header)
    print("─" * len(header))
    for sym, s in sorted(per_symbol.items()):
        rate = round(100 * s["ok"] / s["total"]) if s["total"] else 0
        flag = "🚨" if rate == 0 else ("⚠️ " if rate < 50 else "")
        print(f"{sym:<14} {s['ok']:>3} {s['fail']:>4} {s['total']:>5}  {rate:>4}%  {flag}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dry-run transcript scraper (no OpenAI)")
    parser.add_argument("--symbol", nargs="+", default=None,
                        help="Symbols to test (default: all Nifty50)")
    parser.add_argument("--max-recent", type=int, default=8,
                        help="Max NSE transcript entries per symbol (default: 8)")
    args = parser.parse_args()

    symbols = args.symbol or NIFTY50_SYMBOLS
    print(f"Testing {len(symbols)} symbols, max_recent={args.max_recent}")
    print("=" * 70)
    run(symbols, max_recent=args.max_recent)
