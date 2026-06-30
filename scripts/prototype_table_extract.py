#!/usr/bin/env python3
"""
Prototype: measure how much MORE structured data table-extraction (pdfplumber)
recovers from investor-presentation decks vs. the current plain-text method
(PyMuPDF text layer). Zero API cost, pure CPU.

For each sampled deck it reports:
  - current: chars + numeric tokens captured by plain text
  - tables : tables found, cells, numeric cells captured by pdfplumber
  - a sample recovered table (the structured data the LLM currently never sees)
"""
from __future__ import annotations
import io, re, sys
sys.path.insert(0, ".")

import httpx
import fitz            # PyMuPDF — current method
import pdfplumber      # table extraction — new

from ingestion.official_filings.nse_fetcher import download_pdf

UAT = "https://xqutgxdwmsvabwaioszq.supabase.co"
KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhxdXRneGR3bXN2YWJ3YWlvc3pxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MTUxNDQzNCwiZXhwIjoyMDk3MDkwNDM0fQ.ud6j4bZTF-AMO1rvlrEq5ZnBDVCVSpbb2znfwjaVL-M"
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

_NUM = re.compile(r"-?\d[\d,]*\.?\d*%?")


def num_count(text: str) -> int:
    return len(_NUM.findall(text or ""))


def sample_rich_decks(n=4):
    """Pick a few presentation decks with the most chunks (real decks)."""
    from collections import Counter
    cnt, sym = Counter(), {}
    r = httpx.get(f"{UAT}/rest/v1/corporate_documents", headers=H,
                  params={"select": "pdf_url,symbol", "document_type": "eq.investor_presentation",
                          "limit": "1000"}, timeout=30)
    for x in r.json():
        if x["pdf_url"].startswith("http"):
            cnt[x["pdf_url"]] += 1
            sym[x["pdf_url"]] = x["symbol"]
    # spread across distinct symbols
    picked, seen = [], set()
    for url, _ in cnt.most_common():
        if sym[url] in seen:
            continue
        seen.add(sym[url]); picked.append((sym[url], url))
        if len(picked) >= n:
            break
    return picked


def analyze(pdf_bytes: bytes):
    # current method — PyMuPDF plain text
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    plain = "\n".join(p.get_text() for p in doc)
    pages = len(doc)

    # new — pdfplumber tables
    tables, cells, num_cells, sample = 0, 0, 0, None
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for tbl in page.extract_tables() or []:
                rows = [r for r in tbl if any(c and c.strip() for c in r)]
                if len(rows) < 2:
                    continue
                tables += 1
                for row in rows:
                    for c in row:
                        if c and c.strip():
                            cells += 1
                            if _NUM.search(c):
                                num_cells += 1
                if sample is None and num_cells > 4:
                    sample = rows[:6]
    return {
        "pages": pages,
        "plain_chars": len(plain),
        "plain_nums": num_count(plain),
        "tables": tables,
        "cells": cells,
        "num_cells": num_cells,
        "sample": sample,
    }


def main():
    decks = sample_rich_decks(4)
    print(f"Sampled {len(decks)} rich decks\n" + "=" * 60)
    tot_plain_nums = tot_table_nums = 0
    for symbol, url in decks:
        try:
            pdf = download_pdf(url)
        except Exception as e:
            print(f"[{symbol}] download failed: {str(e)[:60]}")
            continue
        a = analyze(pdf)
        tot_plain_nums += a["plain_nums"]
        tot_table_nums += a["num_cells"]
        print(f"\n[{symbol}] {a['pages']} pages")
        print(f"  CURRENT (plain text): {a['plain_chars']:,} chars, {a['plain_nums']:,} numeric tokens")
        print(f"  TABLES  (pdfplumber): {a['tables']} tables, {a['cells']:,} cells, "
              f"{a['num_cells']:,} numeric cells")
        if a["sample"]:
            print(f"  ─ sample recovered table ─")
            for row in a["sample"]:
                cleaned = " | ".join((c or "").strip().replace("\n", " ")[:18] for c in row)
                print(f"    {cleaned}")
    print("\n" + "=" * 60)
    print(f"TOTAL numeric tokens — plain text: {tot_plain_nums:,}")
    print(f"TOTAL numeric cells  — tables:     {tot_table_nums:,}")
    print("(table cells are STRUCTURED — row/col context the LLM can read precisely)")


if __name__ == "__main__":
    main()
