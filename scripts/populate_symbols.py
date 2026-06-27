#!/usr/bin/env python3
"""
Populate the `symbols` table with the full NSE universe, tagged by membership.

Each symbol gets a `universe` text[] tag list, e.g. ['nse_all','nifty500','nifty50'],
which the ingestion engine uses to drive waves:
    Wave 1 → nifty500   Wave 2 → (liquid set)   Wave 3 → nse_all

Idempotent: upserts on `symbol`, so re-running just refreshes tags/names.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, ".")

from supabase import create_client
from config.nifty50 import NIFTY50_COMPANIES
from config.nse500 import NSE500_COMPANIES
from config.nse_all_stocks import NSE_ALL_COMPANIES


def main():
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    n50 = set(NIFTY50_COMPANIES)
    n500 = set(NSE500_COMPANIES)
    # Universe = everything in nse_all plus any nifty50/500 names not in the CSV snapshot
    all_syms = set(NSE_ALL_COMPANIES) | n500 | n50
    names = {**NIFTY50_COMPANIES, **NSE500_COMPANIES, **NSE_ALL_COMPANIES}

    rows = []
    for sym in sorted(all_syms):
        tags = ["nse_all"]
        if sym in n500:
            tags.append("nifty500")
        if sym in n50:
            tags.append("nifty50")
        rows.append({
            "symbol": sym,
            "company_name": names.get(sym, sym),
            "universe": tags,
            "active": True,
        })

    print(f"Upserting {len(rows)} symbols "
          f"(nifty50={len(n50)}, nifty500={len(n500)}, nse_all={len(NSE_ALL_COMPANIES)})...")
    for i in range(0, len(rows), 500):
        client.table("symbols").upsert(rows[i:i + 500], on_conflict="symbol").execute()
        print(f"  {min(i + 500, len(rows))}/{len(rows)}")
    print("Done.")


if __name__ == "__main__":
    main()
