#!/usr/bin/env python3
"""
End-to-end smoke test for the web search pipeline.

Run this BEFORE deploying to Lambda to verify every layer works:
  OPENAI_API_KEY=sk-... SUPABASE_URL=https://... SUPABASE_SERVICE_KEY=svc-... \
  python3 scripts/smoke_test.py

Tests all 40+ source types:
  - Yahoo Finance RSS + 11 general Indian RSS feeds
  - Screener.in (httpx + HTML parse)
  - NSE official corporate announcements API
  - AlphaSpread valuation (Jina)
  - StockAnalysis financials (Jina)
"""

import os
import sys
import time

REQUIRED = ["OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"]
missing = [k for k in REQUIRED if not os.environ.get(k)]
if missing:
    print(f"[FAIL] Missing env vars: {', '.join(missing)}")
    print("       Set them before running: export OPENAI_API_KEY=sk-...")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from concurrent.futures import ThreadPoolExecutor, as_completed
from db.client import get_client
from ingestion.web_search.stock_scraper import (
    fetch_rss_entries,
    get_direct_page_entries,
    fetch_and_build_article,
)
from ingestion.nse_bse.pdf_processor import chunk_text
from embeddings.embedder import embed_texts
from embeddings.upserter import upsert_web_search_chunks

TEST_STOCKS = {
    "TCS":      "Tata Consultancy Services",
    "RELIANCE": "Reliance Industries",
    "INFY":     "Infosys",
    "HDFCBANK": "HDFC Bank",
    "SBIN":     "State Bank of India",
}


def _ok(label, val, expected=None):
    if expected is not None and val != expected:
        print(f"  [FAIL] {label}: expected {expected}, got {val}")
        return False
    if not val and val != 0:
        print(f"  [FAIL] {label}: got empty/None")
        return False
    print(f"  [OK]   {label}: {val}")
    return True


def test_supabase(client):
    print("\n[1/6] Supabase connection")
    try:
        result = client.table("web_search_results").select("id").limit(1).execute()
        print(f"  [OK]   Connected — web_search_results table exists ({result.data})")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False


def test_rss_sources(symbol, company):
    print(f"\n[2/6] RSS sources for {symbol}")
    entries = fetch_rss_entries(symbol, company)
    _ok("articles found", len(entries))
    if entries:
        _ok("first URL non-empty", entries[0]["url"])
        print(f"         Sample: {entries[0]['title'][:60]}")
    return entries


def test_direct_sources(symbol):
    print(f"\n[3/6] Direct page sources for {symbol} (Screener, NSE, AlphaSpread, StockAnalysis)")
    entries = get_direct_page_entries(symbol)
    _ok("direct entries generated", len(entries), 4)
    for e in entries:
        print(f"         [{e['fetch_method']:20}] {e['url'][:60]}")

    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_and_build_article, entry): entry for entry in entries}
        for f in as_completed(futures):
            entry = futures[f]
            try:
                result = f.result()
                if result:
                    results.append(result)
                    print(f"  [OK]   [{result.source_domain:30}] {len(result.text):6} chars")
                else:
                    print(f"  [FAIL] {entry['url'][:50]}: too short / blocked")
            except Exception as exc:
                print(f"  [ERR]  {entry['url'][:50]}: {exc}")
    return results


def test_jina_article(entries):
    print(f"\n[4/6] Jina article fetch (first RSS article)")
    if not entries:
        print("  [SKIP] no RSS entries")
        return None
    article = fetch_and_build_article(entries[0])
    if not article:
        print("  [FAIL] article text too short or Jina unreachable")
        return None
    _ok("text length (chars)", len(article.text))
    _ok("source domain", article.source_domain)
    return article


def test_embedding(article):
    print(f"\n[5/6] OpenAI embedding")
    if not article:
        print("  [SKIP]")
        return None, None
    chunks = chunk_text(article.text, chunk_size=300, overlap=30)
    _ok("chunks produced", len(chunks))
    t0 = time.time()
    vectors = embed_texts(chunks[:3])
    elapsed = round(time.time() - t0, 2)
    _ok("vectors returned", len(vectors))
    _ok("vector dimension", len(vectors[0]), 1536)
    print(f"         Embedded {len(vectors)} chunks in {elapsed}s")
    return chunks[:3], vectors


def test_upsert(client, symbol, article, chunks, vectors):
    print(f"\n[6/6] Supabase upsert + readback for {symbol}")
    if not chunks:
        print("  [SKIP]")
        return
    upsert_web_search_chunks(
        client=client, symbol=symbol, url=article.url, title=article.title,
        source_domain=article.source_domain, published_at=article.published_at,
        chunks=chunks, vectors=vectors,
    )
    result = (
        client.table("web_search_results")
        .select("id, symbol, source_domain, chunk_index")
        .eq("symbol", symbol).eq("url", article.url)
        .execute()
    )
    _ok("rows in DB", len(result.data))
    for row in result.data:
        print(f"         chunk {row['chunk_index']} — {row['source_domain']}")


def main():
    print("=" * 60)
    print("KuberAI Web Search Pipeline — Smoke Test")
    print("=" * 60)

    client = get_client()
    if not test_supabase(client):
        sys.exit(1)

    first_sym, first_co = next(iter(TEST_STOCKS.items()))

    rss_entries = test_rss_sources(first_sym, first_co)
    direct_results = test_direct_sources(first_sym)
    article = test_jina_article(rss_entries)
    chunks, vectors = test_embedding(article)
    test_upsert(client, first_sym, article, chunks, vectors)

    print(f"\n[Source count summary for {first_sym}]")
    total = len([e for e in rss_entries]) + len(direct_results)
    print(f"  RSS articles: {len(rss_entries)}")
    print(f"  Direct pages successfully fetched: {len(direct_results)}")
    print(f"  Total live sources: {total}")

    print(f"\n[RSS check for remaining {len(TEST_STOCKS) - 1} stocks]")
    for sym, co in list(TEST_STOCKS.items())[1:]:
        entries = fetch_rss_entries(sym, co)
        status = "OK" if entries else "FAIL"
        print(f"  [{status}] {sym}: {len(entries)} RSS articles")

    print("\n" + "=" * 60)
    print("Smoke test complete. If all steps OK, deploy the Lambda.")
    print("=" * 60)


if __name__ == "__main__":
    main()
