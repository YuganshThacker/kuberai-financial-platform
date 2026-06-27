"""
Transcript corpus quality audit.

Prints a table showing every ingested symbol's coverage (transcripts, chunks,
avg chunk length) alongside any failure records from failed_documents.

Usage:
    python3 scripts/audit_transcripts.py [--symbol SYMBOL]

Flags:
  🚨  avg_chunks_per_transcript < 20   (too thin — likely not a real transcript)
  ⚠️   transcripts < 4                 (poor historical coverage)
  📋  has entries in failed_documents  (some quarters couldn't be ingested)
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.client import get_client


def _run_audit(symbol_filter: str | None = None) -> None:
    client = get_client()

    # ── Fetch all official_transcripts rows (paginated) ─────────────────────
    # chunk_text can be large — omit it to avoid Supabase's 1000-row page limit impact.
    # Paginate to ensure we get every row regardless of corpus size.
    PAGE = 1000
    raw: list[dict] = []
    offset = 0
    while True:
        query = (
            client.table("official_transcripts")
            .select("symbol, pdf_url, filing_date")
            .range(offset, offset + PAGE - 1)
        )
        if symbol_filter:
            query = query.eq("symbol", symbol_filter)
        page = query.execute().data or []
        raw.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE

    stats: dict[str, dict] = defaultdict(lambda: {
        "pdfs": set(), "chunks": 0, "char_total": 0, "dates": []
    })
    for row in raw:
        sym = row["symbol"]
        stats[sym]["pdfs"].add(row["pdf_url"])
        stats[sym]["chunks"] += 1
        if row.get("filing_date"):
            stats[sym]["dates"].append(row["filing_date"])

    # ── Fetch failed_documents rows ──────────────────────────────────────────
    fail_query = client.table("failed_documents").select("symbol, reason, text_length")
    if symbol_filter:
        fail_query = fail_query.eq("symbol", symbol_filter)
    fail_raw = fail_query.execute().data or []

    failures: dict[str, list[dict]] = defaultdict(list)
    for row in fail_raw:
        failures[row["symbol"]].append(row)

    # ── Print report ─────────────────────────────────────────────────────────
    all_symbols = sorted(set(list(stats.keys()) + list(failures.keys())))

    print(f"\n{'Symbol':<14} {'PDFs':>5} {'Chunks':>7} {'Avg/PDF':>7} "
          f"{'Oldest':>11} {'Newest':>11}  Flags")
    print("─" * 85)

    total_pdfs = total_chunks = 0
    for sym in all_symbols:
        s = stats.get(sym)
        fails = failures.get(sym, [])

        if s and s["chunks"] > 0:
            n_pdfs = len(s["pdfs"])
            n_chunks = s["chunks"]
            avg_per = round(n_chunks / n_pdfs, 1) if n_pdfs else 0
            oldest = min(s["dates"]) if s["dates"] else "—"
            newest = max(s["dates"]) if s["dates"] else "—"
            total_pdfs += n_pdfs
            total_chunks += n_chunks
        else:
            n_pdfs = n_chunks = avg_per = 0
            oldest = newest = "—"

        flags = []
        if n_chunks == 0:
            flags.append("🚨 NO DATA")
        elif avg_per < 20:
            flags.append("🚨 thin")
        if 0 < n_pdfs < 4:
            flags.append("⚠️  <4 qtrs")
        if fails:
            reasons = ", ".join(sorted({f["reason"] for f in fails}))
            flags.append(f"📋 {len(fails)} failed ({reasons})")

        print(
            f"{sym:<14} {n_pdfs:>5} {n_chunks:>7} {avg_per:>7} "
            f"{oldest:>11} {newest:>11}  {'  '.join(flags)}"
        )

    print("─" * 90)
    print(f"{'TOTAL':<14} {total_pdfs:>5} {total_chunks:>7}")

    # ── Failed documents by reason ────────────────────────────────────────────
    all_fails = [f for sym_fails in failures.values() for f in sym_fails]
    if all_fails:
        print(f"\nFailed documents by reason:")
        reason_counts: dict[str, int] = defaultdict(int)
        for f in all_fails:
            reason_counts[f["reason"]] += 1
        for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
            print(f"  {reason:<40} {count:>4}")
        print(f"\n  Total failed: {len(all_fails)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transcript corpus quality audit")
    parser.add_argument("--symbol", help="Audit a single symbol only")
    args = parser.parse_args()
    _run_audit(symbol_filter=args.symbol)
