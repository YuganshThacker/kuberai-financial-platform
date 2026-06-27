"""
Nifty50 annual report ingestion — all 50 symbols, up to 2 fiscal years each.

Phases:
  1. Discovery (NSE feed)
  2. Ingestion (embed + upsert to corporate_documents)
  3. Coverage report

Usage:
    python scripts/run_nifty50_annual_reports.py [--dry-run] [--symbol SYMBOL]
    python scripts/run_nifty50_annual_reports.py --phase1-only   # Phase 1 hardening check

Environment:
    SUPABASE_URL, SUPABASE_SERVICE_KEY, OPENAI_API_KEY
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client

from config.nifty50 import NIFTY50_SYMBOLS
from embeddings.embedder import embed_texts
from ingestion.official_filings.annual_report_discovery import discover_annual_reports
from ingestion.official_filings.annual_report_ingester import (
    MIN_ANNUAL_REPORT_CHARS,
    MIN_ANNUAL_REPORT_CHUNKS,
    _MIN_KEYWORD_SCORE,
    _keyword_score,
    ingest_annual_report,
)
from monitoring.metrics import IngestionMetrics

# Pilot symbols already in DB — skip re-ingestion unless --force
PILOT_SYMBOLS = {"RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"}


def _client():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


# ── Phase 1 hardening check ───────────────────────────────────────────────────

def run_phase1_hardening(client) -> None:
    """Re-validate pilot symbols against new quality gates. Report only."""
    print("\n" + "=" * 70)
    print("PHASE 1 — HARDENING VALIDATION (new gates: 500K chars, 200 chunks, score≥5)")
    print("=" * 70)
    print(f"\nGates active:")
    print(f"  MIN_ANNUAL_REPORT_CHARS  = {MIN_ANNUAL_REPORT_CHARS:,}")
    print(f"  MIN_ANNUAL_REPORT_CHUNKS = {MIN_ANNUAL_REPORT_CHUNKS}")
    print(f"  _MIN_KEYWORD_SCORE       = {_MIN_KEYWORD_SCORE}")

    print(f"\n{'SYMBOL':<14} {'FY':<6} {'CHARS':>12} {'CHUNKS':>8} {'SCORE':>6} {'RESULT':<10} SECTIONS")
    print("-" * 90)

    rows = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            client.table("corporate_documents")
            .select("symbol,fiscal_year,section_type,chunk_index,chunk_text")
            .eq("document_type", "annual_report")
            .in_("symbol", sorted(PILOT_SYMBOLS))
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    # Group by symbol+FY
    by_key: dict[str, dict] = {}
    for r in rows:
        key = f"{r['symbol']}|{r['fiscal_year']}"
        if key not in by_key:
            by_key[key] = {
                "symbol": r["symbol"],
                "fy": r["fiscal_year"],
                "chunks": 0,
                "sections": set(),
                "sample_text": "",
            }
        by_key[key]["chunks"] += 1
        if r.get("section_type"):
            by_key[key]["sections"].add(r["section_type"])
        if len(by_key[key]["sample_text"]) < 5000:
            by_key[key]["sample_text"] += r.get("chunk_text", "")

    passed = 0
    failed = 0
    for entry in sorted(by_key.values(), key=lambda x: (x["symbol"], x["fy"])):
        sym = entry["symbol"]
        fy = entry["fy"]
        n_chunks = entry["chunks"]
        sections = entry["sections"]
        sample = entry["sample_text"]

        # Reconstruct approximate char count from chunk count
        approx_chars = n_chunks * 2_200  # ~2200 chars per chunk (500 words × 4.4 chars/word)
        score = _keyword_score(sample[:50_000])  # score first 50K of sample text

        chunk_ok = n_chunks >= MIN_ANNUAL_REPORT_CHUNKS
        # Score gate fires on raw PDF text at ingestion time, not on chunks.
        # Retrospective check uses chunk count as proxy: full ARs have 200+ chunks.
        chars_ok = approx_chars >= MIN_ANNUAL_REPORT_CHARS

        result = "PASS" if chunk_ok else "FAIL"
        if result == "PASS":
            passed += 1
        else:
            failed += 1

        print(
            f"{sym:<14} {fy:<6} {approx_chars:>12,} {n_chunks:>8} {score:>6} {result:<10} "
            f"{', '.join(sorted(sections))}"
        )

    print(f"\nSummary: {passed} PASS / {failed} FAIL")
    print("\nNote: AGM notices (34 chunks, RELIANCE FY2025) would fail new 200-chunk gate.")
    print("These are already in DB from pilot; new gate prevents future AGM contamination.")


# ── Ingestion ─────────────────────────────────────────────────────────────────

def run_ingestion(
    symbols: list[str],
    client,
    dry_run: bool = False,
    force: bool = False,
    max_years: int = 2,
) -> dict[str, dict]:
    """
    Discover and ingest annual reports for a list of symbols.

    Returns per-symbol result dict:
        status: 'success' | 'no_reports' | 'discovery_failed' | 'all_failed'
        chunks: int
        reports: list of {fy, chunks, sections, chars}
        error: str (if failed)
    """
    results: dict[str, dict] = {}
    metrics = IngestionMetrics("nifty50_annual_reports")

    for i, symbol in enumerate(symbols, 1):
        print(f"\n[{i:02d}/{len(symbols)}] {symbol}")
        t0 = time.perf_counter()

        try:
            reports = discover_annual_reports(symbol, client, max_years=max_years)
        except Exception as exc:
            print(f"  discovery failed: {exc}")
            results[symbol] = {"status": "discovery_failed", "chunks": 0, "error": str(exc)}
            continue

        if not reports:
            print(f"  no annual reports found in NSE feed")
            results[symbol] = {"status": "no_reports", "chunks": 0}
            continue

        symbol_chunks = 0
        report_details = []
        all_failed = True

        for report in reports:
            fy = report["fiscal_year"]
            chars = report["text_len"]
            print(f"  FY{fy}: {chars:,} chars {'(DRY RUN)' if dry_run else ''}")
            if dry_run:
                report_details.append({"fy": fy, "chars": chars, "chunks": 0, "sections": []})
                all_failed = False
                continue

            n = ingest_annual_report(symbol, report, client, metrics)
            if n > 0:
                all_failed = False
            symbol_chunks += n
            report_details.append({"fy": fy, "chars": chars, "chunks": n, "sections": []})

        elapsed = time.perf_counter() - t0
        status = "all_failed" if (all_failed and not dry_run) else "success"
        results[symbol] = {
            "status": status,
            "chunks": symbol_chunks,
            "reports": report_details,
            "elapsed": elapsed,
        }
        print(f"  → {symbol_chunks} chunks in {elapsed:.1f}s")

    return results


# ── Coverage query ────────────────────────────────────────────────────────────

def print_coverage_report(symbols: list[str], client) -> None:
    print("\n" + "=" * 70)
    print("ANNUAL REPORT COVERAGE — NIFTY50")
    print("=" * 70)

    rows = []
    page_size = 1000
    offset = 0
    while True:
        resp = (
            client.table("corporate_documents")
            .select("symbol,fiscal_year,section_type")
            .eq("document_type", "annual_report")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    by_key: dict[str, dict] = {}
    symbol_set = set(symbols)
    for r in rows:
        sym = r["symbol"]
        if sym not in symbol_set:
            continue
        key = f"{sym}|{r['fiscal_year']}"
        if key not in by_key:
            by_key[key] = {"symbol": sym, "fy": r["fiscal_year"], "chunks": 0, "sections": set()}
        by_key[key]["chunks"] += 1
        if r.get("section_type"):
            by_key[key]["sections"].add(r["section_type"])

    covered_symbols = {e["symbol"] for e in by_key.values()}
    missing = sorted(symbol_set - covered_symbols)

    print(f"\n{'SYMBOL':<14} {'FY':<6} {'CHUNKS':>8}  SECTIONS")
    print("-" * 70)
    for entry in sorted(by_key.values(), key=lambda x: (x["symbol"], x["fy"])):
        print(
            f"{entry['symbol']:<14} {entry['fy']:<6} {entry['chunks']:>8}  "
            f"{', '.join(sorted(entry['sections']))}"
        )

    total_chunks = sum(e["chunks"] for e in by_key.values())
    est_cost = total_chunks * 550 / 1_000_000 * 0.020
    print(f"\nTotal chunks : {total_chunks:,}")
    print(f"Est. embed $ : ${est_cost:.4f}")
    print(f"Symbols covered: {len(covered_symbols)}/50")
    if missing:
        print(f"Missing ({len(missing)}): {', '.join(missing)}")


# ── Ingestion result summary ──────────────────────────────────────────────────

def print_ingestion_summary(results: dict[str, dict]) -> None:
    print("\n" + "=" * 70)
    print("INGESTION SUMMARY")
    print("=" * 70)

    success = [s for s, r in results.items() if r["status"] == "success"]
    no_reports = [s for s, r in results.items() if r["status"] == "no_reports"]
    disc_failed = [s for s, r in results.items() if r["status"] == "discovery_failed"]
    all_failed = [s for s, r in results.items() if r["status"] == "all_failed"]

    print(f"\nSuccessful   ({len(success):2d}): {', '.join(sorted(success)) or '—'}")
    print(f"No reports   ({len(no_reports):2d}): {', '.join(sorted(no_reports)) or '—'}")
    print(f"Disc. failed ({len(disc_failed):2d}): {', '.join(sorted(disc_failed)) or '—'}")
    for s in disc_failed:
        print(f"    {s}: {results[s].get('error', '?')}")
    print(f"All ingst.   ({len(all_failed):2d}): {', '.join(sorted(all_failed)) or '—'}")

    total_chunks = sum(r.get("chunks", 0) for r in results.values())
    print(f"\nTotal new chunks: {total_chunks:,}")
    est_cost = total_chunks * 550 / 1_000_000 * 0.020
    print(f"Est. embed cost: ${est_cost:.4f}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Run for a single symbol only")
    parser.add_argument("--dry-run", action="store_true",
                        help="Discover only — skip embedding and storage")
    parser.add_argument("--force", action="store_true",
                        help="Re-ingest pilot symbols even if already present")
    parser.add_argument("--phase1-only", action="store_true",
                        help="Phase 1 hardening check against existing pilot data only")
    parser.add_argument("--max-years", type=int, default=2,
                        help="Max fiscal years to ingest per symbol (default: 2)")
    args = parser.parse_args()

    client = _client()

    if args.phase1_only:
        run_phase1_hardening(client)
        return

    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        # Exclude pilot symbols unless --force
        if args.force:
            symbols = NIFTY50_SYMBOLS
        else:
            symbols = [s for s in NIFTY50_SYMBOLS if s not in PILOT_SYMBOLS]
            if not args.dry_run:
                print(f"Skipping pilot symbols (already in DB): {sorted(PILOT_SYMBOLS)}")
                print(f"Running {len(symbols)} new symbols. Use --force to re-ingest all.")

    print(f"\nNifty50 Annual Report Ingestion — {len(symbols)} symbols, max {args.max_years} FY")
    print("=" * 70)

    results = run_ingestion(
        symbols, client,
        dry_run=args.dry_run,
        force=args.force,
        max_years=args.max_years,
    )

    print_ingestion_summary(results)

    if not args.dry_run:
        all_symbols = list(PILOT_SYMBOLS) + symbols if not args.force else NIFTY50_SYMBOLS
        print_coverage_report(list(set(all_symbols)), client)


if __name__ == "__main__":
    main()
