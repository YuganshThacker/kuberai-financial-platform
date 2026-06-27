#!/usr/bin/env python3
"""
Universe-scale ingestion CLI — drives the 4 research doc types across NSE waves.

Examples:
  # Wave 1 — Nifty500, all 4 doc types, resumable:
  python scripts/ingest_universe.py --universe nifty500

  # Specific symbols, transcripts + annual only:
  python scripts/ingest_universe.py --symbols DIXON,POLYCAB --doc-types transcripts,annual

  # Full NSE (after compute upgrade):
  python scripts/ingest_universe.py --universe nse_all

  # Retry only the pairs that previously errored (NSE outage recovery):
  python scripts/ingest_universe.py --universe nifty500   # resume retries errors automatically

State lives in discovery_state (per symbol × doc type). Re-running is safe:
completed/empty pairs are skipped, errored pairs are retried.
"""
from __future__ import annotations
import argparse, os, sys
sys.path.insert(0, ".")

from supabase import create_client
from ingestion.universe_engine import (
    ingest_universe, DOC_TYPES, DEFAULT_DOC_TYPES,
)
from monitoring.metrics import IngestionMetrics


def load_symbols(client, universe: str, limit: int | None, offset: int) -> list[str]:
    """Symbols carrying the given universe tag, ordered, with paging for batching."""
    rows, page, off = [], 1000, offset
    while True:
        q = (client.table("symbols").select("symbol")
             .contains("universe", [universe])
             .eq("active", True)
             .order("symbol")
             .range(off, off + page - 1))
        data = q.execute().data or []
        rows.extend(r["symbol"] for r in data)
        if len(data) < page:
            break
        off += page
        if limit and len(rows) >= limit:
            break
    return rows[:limit] if limit else rows


def main():
    p = argparse.ArgumentParser(description="Universe-scale KuberAI ingestion")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--universe", choices=["nifty50", "nifty500", "nse_all"],
                   help="Ingest all symbols carrying this universe tag")
    g.add_argument("--symbols", help="Comma-separated explicit symbol list")
    p.add_argument("--doc-types", default=",".join(DEFAULT_DOC_TYPES),
                   help=f"Comma-separated subset of {','.join(DOC_TYPES)}")
    p.add_argument("--max-years", type=int, default=5,
                   help="Years back to search for annual reports (default 5)")
    p.add_argument("--no-resume", action="store_true",
                   help="Re-ingest even pairs already marked complete")
    p.add_argument("--retry-empty", action="store_true",
                   help="Also retry pairs previously found empty (e.g. after outage)")
    p.add_argument("--limit", type=int, help="Cap number of symbols (batching/testing)")
    p.add_argument("--offset", type=int, default=0, help="Skip first N symbols (batching)")
    args = p.parse_args()

    doc_types = [d.strip() for d in args.doc_types.split(",") if d.strip() in DOC_TYPES]
    if not doc_types:
        sys.exit("No valid doc types.")

    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = load_symbols(client, args.universe, args.limit, args.offset)

    print("=" * 72)
    print(f"  KuberAI universe ingestion")
    print(f"  symbols : {len(symbols)}"
          + (f"  (universe={args.universe})" if args.universe else "  (explicit)"))
    print(f"  types   : {', '.join(doc_types)}")
    print(f"  resume  : {not args.no_resume}   retry_empty: {args.retry_empty}")
    print("=" * 72, flush=True)

    metrics = IngestionMetrics("universe_ingest")
    ingest_universe(symbols, doc_types, client, metrics,
                    resume=not args.no_resume, max_years=args.max_years,
                    retry_empty=args.retry_empty)

    metrics.print_summary()
    try:
        metrics.finish(client, metadata={"universe": args.universe, "doc_types": doc_types})
    except Exception as exc:
        print(f"(metrics.finish skipped: {exc})")


if __name__ == "__main__":
    main()
