"""
Scheduler load test: measure per-symbol timing and project to 50/100/500 symbols.

Runs the scheduler in --dry-run mode for a sample of symbols and reports:
  - NSE API call latency per symbol
  - DB query latency (discovery_state + known_pdf_urls)
  - Estimated total runtime for Nifty50 / NSE500 / all-NSE
  - GitHub Actions feasibility

Usage:
    python scripts/scheduler_load_test.py [--sample N]
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client

from config.nifty50 import NIFTY50_COMPANIES
from ingestion.official_filings.nse_fetcher import get_new_filings_since


_GITHUB_ACTIONS_LIMIT_S = 6 * 60  # default 6-minute job timeout
_DEFAULT_FROM_DATE = "2024-01-01"   # worst-case: cold-start scan


def _client():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def _measure_nse_api(symbols: list[str]) -> list[float]:
    """Return per-symbol NSE API latency in seconds."""
    latencies = []
    for sym in symbols:
        t0 = time.perf_counter()
        try:
            get_new_filings_since(sym, _DEFAULT_FROM_DATE)
        except Exception:
            pass
        latencies.append(time.perf_counter() - t0)
        print(f"  {sym}: {latencies[-1]:.2f}s")
    return latencies


def _measure_db(client, symbols: list[str]) -> list[float]:
    """Return per-symbol DB round-trip latency for discovery_state + known_pdf_urls."""
    latencies = []
    for sym in symbols:
        t0 = time.perf_counter()
        # Simulates _load_symbol_mark
        client.table("discovery_state").select("last_filing_date").eq("source", "nse_filing").eq("symbol", sym).limit(1).execute()
        # Simulates _known_pdf_urls
        client.table("corporate_documents").select("pdf_url").eq("symbol", sym).eq("document_type", "transcript").execute()
        latencies.append(time.perf_counter() - t0)
    return latencies


def _project(mean_s: float, stddev_s: float, sizes: list[int]) -> None:
    print(f"\n  {'Symbols':>10}  {'Est. time':>12}  {'GitHub Actions':>16}")
    print(f"  {'-'*10}  {'-'*12}  {'-'*16}")
    for n in sizes:
        est = n * mean_s
        warn = " ⚠ OVER LIMIT" if est > _GITHUB_ACTIONS_LIMIT_S else ""
        mins = int(est // 60)
        secs = int(est % 60)
        print(f"  {n:>10}  {mins:>3}m {secs:>02}s       {'✓ safe' if not warn else '⚠ exceeds 6m':>16}{warn}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=8,
                        help="Number of symbols to sample (default 8)")
    args = parser.parse_args()

    symbols = list(NIFTY50_COMPANIES.keys())[:args.sample]

    print(f"\n{'='*60}")
    print("  SCHEDULER LOAD TEST")
    print(f"{'='*60}")
    print(f"  Sample size: {len(symbols)} symbols")
    print(f"  Symbols:     {', '.join(symbols)}")
    print(f"  From date:   {_DEFAULT_FROM_DATE} (cold-start worst case)\n")

    print("── NSE API latency ──────────────────────────────────────")
    nse_times = _measure_nse_api(symbols)
    nse_mean = statistics.mean(nse_times)
    nse_std  = statistics.stdev(nse_times) if len(nse_times) > 1 else 0.0
    print(f"\n  Mean:   {nse_mean:.2f}s  Stddev: {nse_std:.2f}s")
    print(f"  Min:    {min(nse_times):.2f}s  Max:    {max(nse_times):.2f}s")

    print("\n── DB round-trip latency ─────────────────────────────────")
    client = _client()
    db_times = _measure_db(client, symbols)
    db_mean = statistics.mean(db_times)
    db_std  = statistics.stdev(db_times) if len(db_times) > 1 else 0.0
    print(f"  Mean:   {db_mean:.3f}s  Stddev: {db_std:.3f}s")
    print(f"  Min:    {min(db_times):.3f}s  Max:    {max(db_times):.3f}s")

    total_per_symbol = nse_mean + db_mean
    total_std = (nse_std**2 + db_std**2) ** 0.5

    print(f"\n── Per-symbol total (API + DB) ───────────────────────────")
    print(f"  Mean:   {total_per_symbol:.2f}s  Stddev: {total_std:.2f}s")

    print(f"\n── Projections (cold-start, no ingestion) ────────────────")
    _project(total_per_symbol, total_std, [50, 100, 500, 2000])

    print(f"\n── Bottleneck analysis ───────────────────────────────────")
    nse_pct = nse_mean / total_per_symbol * 100
    db_pct  = db_mean / total_per_symbol * 100
    print(f"  NSE API:    {nse_pct:.0f}% of per-symbol time")
    print(f"  DB queries: {db_pct:.0f}% of per-symbol time")

    # Recommendations
    print(f"\n── Production recommendations ────────────────────────────")
    if total_per_symbol > _GITHUB_ACTIONS_LIMIT_S / 50:
        print("  ⚠ At current speed, a 50-symbol run may approach the 6-min limit.")
        print("    Recommend: increase GHA job timeout to 20 minutes, or shard by batch.")
    else:
        print("  ✓ Nifty50 run fits comfortably within 6-min GHA limit.")

    if nse_pct > 80:
        print("  ⚠ NSE API is the dominant bottleneck — parallelization or caching")
        print("    would have the highest impact for NSE500+ expansion.")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
