#!/usr/bin/env python3
"""
End-to-end smoke test for the web search pipeline.

Run this BEFORE deploying to Lambda to verify every layer works:
  OPENAI_API_KEY=sk-... SUPABASE_URL=https://... SUPABASE_SERVICE_KEY=svc-... \
  python3 scripts/smoke_test.py

It tests 5 stocks, fetches real Google News RSS, pulls full article text via Jina,
embeds with OpenAI, upserts to Supabase, then queries back to confirm rows exist.
"""

import os
import sys
import time

# --- pre-flight env check -------------------------------------------------
REQUIRED = ["OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"]
missing = [k for k in REQUIRED if not os.environ.get(k)]
if missing:
    print(f"[FAIL] Missing env vars: {', '.join(missing)}")
    print("       Set them before running: export OPENAI_API_KEY=sk-...")
    sys.exit(1)

# add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.client import get_client
from ingestion.web_search.stock_scraper import fetch_rss_entries, fetch_and_build_article
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

def check(label: str, value, expected=None):
    if expected is not None and value != expected:
        print(f"  [FAIL] {label}: expected {expected}, got {value}")
        return False
    if not value and value != 0:
        print(f"  [FAIL] {label}: got empty/None")
        return False
    print(f"  [OK]   {label}: {value}")
    return True

def test_supabase_connection(client):
    print("\n[1/5] Supabase connection")
    try:
        result = client.table("web_search_results").select("id").limit(1).execute()
        print(f"  [OK]   Connected — web_search_results table exists ({result.data})")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        print("         → Have you run migrations 009 and 010 in Supabase SQL editor?")
        return False

def test_rss_fetch(symbol, company):
    print(f"\n[2/5] Google News RSS for {symbol}")
    entries = fetch_rss_entries(symbol, company)
    ok = check("articles found", len(entries), None)
    if entries:
        check("first URL non-empty", entries[0]["url"])
        print(f"         Sample: {entries[0]['title'][:60]}")
    return ok, entries

def test_jina_fetch(entries):
    print(f"\n[3/5] Jina article fetch (first article only)")
    if not entries:
        print("  [SKIP] no RSS entries")
        return None
    article = fetch_and_build_article(entries[0])
    if not article:
        print(f"  [FAIL] article text too short or Jina unreachable")
        return None
    check("text length (chars)", len(article.text))
    check("source domain", article.source_domain)
    return article

def test_embedding(article):
    print(f"\n[4/5] OpenAI embedding")
    if not article:
        print("  [SKIP]")
        return None, None
    chunks = chunk_text(article.text, chunk_size=300, overlap=30)
    check("chunks produced", len(chunks))
    t0 = time.time()
    vectors = embed_texts(chunks[:3])  # only first 3 to save tokens
    elapsed = round(time.time() - t0, 2)
    check("vectors returned", len(vectors))
    check("vector dimension", len(vectors[0]), 1536)
    print(f"         Embedded 3 chunks in {elapsed}s")
    return chunks[:3], vectors

def test_upsert_and_query(client, symbol, article, chunks, vectors):
    print(f"\n[5/5] Supabase upsert + readback for {symbol}")
    if not chunks:
        print("  [SKIP]")
        return
    upsert_web_search_chunks(
        client=client,
        symbol=symbol,
        url=article.url,
        title=article.title,
        source_domain=article.source_domain,
        published_at=article.published_at,
        chunks=chunks,
        vectors=vectors,
    )
    result = (
        client.table("web_search_results")
        .select("id, symbol, source_domain, chunk_index")
        .eq("symbol", symbol)
        .eq("url", article.url)
        .execute()
    )
    check("rows in DB", len(result.data))
    for row in result.data:
        print(f"         chunk {row['chunk_index']} — {row['source_domain']}")

def main():
    print("=" * 60)
    print("KuberAI Web Search Pipeline — Smoke Test")
    print("=" * 60)

    client = get_client()

    if not test_supabase_connection(client):
        sys.exit(1)

    # Test just the first stock fully; RSS-only check for remaining 4
    first_sym, first_co = next(iter(TEST_STOCKS.items()))
    ok, entries = test_rss_fetch(first_sym, first_co)
    article = test_jina_fetch(entries)
    chunks, vectors = test_embedding(article)
    test_upsert_and_query(client, first_sym, article, chunks, vectors)

    print(f"\n[RSS check for remaining {len(TEST_STOCKS) - 1} stocks]")
    for sym, co in list(TEST_STOCKS.items())[1:]:
        entries = fetch_rss_entries(sym, co)
        status = "OK" if entries else "FAIL"
        print(f"  [{status}] {sym}: {len(entries)} articles")

    print("\n" + "=" * 60)
    print("Smoke test complete. If all steps are OK, deploy the Lambda.")
    print("=" * 60)

if __name__ == "__main__":
    main()
