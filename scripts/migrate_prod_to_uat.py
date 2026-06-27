#!/usr/bin/env python3
"""
Stream all data from PROD (Web Search) → UAT (KuberAI-UAT) via Supabase REST.

No Postgres password needed — uses service-role keys for both projects.
Run AFTER pasting db/uat_migration/01_schema.sql into the UAT SQL editor.
After this completes, paste db/uat_migration/02_build_index.sql.

Idempotent: tables with a natural conflict key use upsert; others are skipped
if UAT already holds >= prod's row count, so re-running is safe.
"""
from __future__ import annotations
import sys, time
import httpx

import os as _os
PROD_URL = _os.environ.get("PROD_SUPABASE_URL", "https://xtewpylutqnvbkuspsmv.supabase.co")
PROD_KEY = _os.environ["PROD_SUPABASE_SERVICE_KEY"]
UAT_URL  = _os.environ.get("UAT_SUPABASE_URL", "https://xqutgxdwmsvabwaioszq.supabase.co")
UAT_KEY  = _os.environ["UAT_SUPABASE_SERVICE_KEY"]

def hdr(key, extra=None):
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h

# table -> (on_conflict cols or None, read_page, write_batch)
TABLES = [
    ("symbols",                      "symbol",            1000, 500),
    ("discovery_state",              "source,symbol",     1000, 500),
    ("ir_pages",                     "symbol",            1000, 500),
    ("ingestion_runs",               None,                1000, 500),
    ("failed_documents",             None,                1000, 500),
    ("document_coverage",            None,                1000, 500),
    ("transcript_insights",          "pdf_url",           1000, 200),
    ("web_search_results",           "url,chunk_index",    500, 100),
    ("official_transcripts_backup",  None,                 500, 100),
    ("corporate_documents",          "pdf_url,chunk_index", 500, 100),
]

def count(base, key, table):
    r = httpx.get(f"{base}/rest/v1/{table}", headers=hdr(key, {"Range": "0-0", "Prefer": "count=exact"}),
                  params={"select": "id"}, timeout=30)
    cr = r.headers.get("content-range", "")
    if "/" in cr and cr.split("/")[1].isdigit():
        return int(cr.split("/")[1])
    # tables without 'id' (e.g. some state tables) — fall back to a wildcard count
    r = httpx.get(f"{base}/rest/v1/{table}", headers=hdr(key, {"Range": "0-0", "Prefer": "count=exact"}),
                  params={"select": "*"}, timeout=30)
    cr = r.headers.get("content-range", "")
    return int(cr.split("/")[1]) if "/" in cr and cr.split("/")[1].isdigit() else 0

def read_page(table, offset, limit):
    r = httpx.get(f"{PROD_URL}/rest/v1/{table}", headers=hdr(PROD_KEY),
                  params={"select": "*", "offset": str(offset), "limit": str(limit), "order": "id"},
                  timeout=120)
    if r.status_code not in (200, 206):
        # some tables have no 'id' to order by
        r = httpx.get(f"{PROD_URL}/rest/v1/{table}", headers=hdr(PROD_KEY),
                      params={"select": "*", "offset": str(offset), "limit": str(limit)}, timeout=120)
    r.raise_for_status()
    return r.json()

def write_batch(table, rows, on_conflict):
    extra = {"Prefer": "resolution=merge-duplicates,return=minimal"} if on_conflict else {"Prefer": "return=minimal"}
    params = {"on_conflict": on_conflict} if on_conflict else {}
    for attempt in range(4):
        try:
            r = httpx.post(f"{UAT_URL}/rest/v1/{table}", headers=hdr(UAT_KEY, extra),
                           params=params, json=rows, timeout=180)
            if r.status_code in (200, 201, 204):
                return
            print(f"    write {table} HTTP {r.status_code}: {r.text[:300]}", flush=True)
        except Exception as exc:
            print(f"    write {table} attempt {attempt+1} error: {exc}", flush=True)
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to write batch to {table} after retries")

def migrate_table(table, on_conflict, read_pg, write_b):
    src_n = count(PROD_URL, PROD_KEY, table)
    dst_n = count(UAT_URL, UAT_KEY, table)
    print(f"\n[{table}]  prod={src_n:,}  uat={dst_n:,}", flush=True)
    if src_n == 0:
        print("  prod empty — skip", flush=True)
        return
    if dst_n >= src_n and on_conflict is None:
        print("  uat already populated (no conflict key) — skip to avoid dupes", flush=True)
        return

    moved, offset, t0 = 0, 0, time.perf_counter()
    while offset < src_n:
        page = read_page(table, offset, read_pg)
        if not page:
            break
        for i in range(0, len(page), write_b):
            write_batch(table, page[i:i + write_b], on_conflict)
        moved += len(page)
        offset += read_pg
        rate = moved / max(time.perf_counter() - t0, 0.1)
        print(f"  {moved:,}/{src_n:,}  ({rate:.0f} rows/s)", flush=True)
    print(f"  ✓ {table} done — {moved:,} rows in {time.perf_counter()-t0:.0f}s", flush=True)

def main():
    only = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    print("=" * 60)
    print("  PROD → UAT  REST migration")
    print("=" * 60, flush=True)
    for table, oc, rp, wb in TABLES:
        if only and table not in only:
            continue
        try:
            migrate_table(table, oc, rp, wb)
        except Exception as exc:
            print(f"  !! {table} FAILED: {exc}", flush=True)
    print("\nAll done. Now paste db/uat_migration/02_build_index.sql into UAT.", flush=True)

if __name__ == "__main__":
    main()
