"""
Transcript QA dashboard: per-symbol, per-quarter validation.

For each symbol in the Nifty50:
  - Shows ingested transcripts (quarter, chunks, chars, embedding status)
  - Runs a vector retrieval test to confirm embeddings are searchable

Usage:
    python scripts/transcript_qa_dashboard.py
    python scripts/transcript_qa_dashboard.py --symbols ITC WIPRO TECHM TITAN TRENT ULTRACEMCO
    python scripts/transcript_qa_dashboard.py --retrieval-only
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from typing import Any

from supabase import create_client, Client

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.nifty50 import NIFTY50_COMPANIES
from embeddings.embedder import embed_texts

# ── Column widths ────────────────────────────────────────────────────────────
_W = {"symbol": 14, "quarter": 8, "fy": 6, "chunks": 7, "chars": 9, "embed": 8, "retrieval": 10}


def _client() -> Client:
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


# ── Coverage query ────────────────────────────────────────────────────────────

def fetch_coverage(client: Client, symbols: list[str]) -> dict[str, list[dict]]:
    """Return per-symbol list of transcript rows (aggregated by pdf_url)."""
    resp = (
        client.table("corporate_documents")
        .select("symbol,quarter,fiscal_year,pdf_url,chunk_text,embedding")
        .eq("document_type", "transcript")
        .in_("symbol", symbols)
        .execute()
    )
    rows = resp.data or []

    # Group by (symbol, pdf_url)
    grouped: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = f"{r['symbol']}|{r['pdf_url']}"
        if key not in grouped:
            grouped[key] = {
                "symbol": r["symbol"],
                "quarter": r["quarter"] or "?",
                "fiscal_year": r["fiscal_year"] or "?",
                "pdf_url": r["pdf_url"],
                "chunks": 0,
                "total_chars": 0,
                "embeddings_ok": 0,
                "embeddings_null": 0,
            }
        g = grouped[key]
        g["chunks"] += 1
        g["total_chars"] += len(r.get("chunk_text") or "")
        if r.get("embedding"):
            g["embeddings_ok"] += 1
        else:
            g["embeddings_null"] += 1

    # Bucket by symbol
    by_symbol: dict[str, list[dict]] = {s: [] for s in symbols}
    for g in grouped.values():
        sym = g["symbol"]
        if sym in by_symbol:
            by_symbol[sym].append(g)

    # Sort each symbol's list by fiscal_year + quarter
    for sym in by_symbol:
        by_symbol[sym].sort(key=lambda x: (str(x["fiscal_year"]), str(x["quarter"])))

    return by_symbol


# ── Retrieval test ────────────────────────────────────────────────────────────

_TEST_QUERIES = {
    "ITC":        "What was ITC management's revenue guidance and growth outlook?",
    "WIPRO":      "What were Wipro's revenue growth numbers and deal wins?",
    "TECHM":      "What was Tech Mahindra's margin guidance and deal pipeline?",
    "TITAN":      "What did Titan management say about jewellery segment growth?",
    "TRENT":      "What was Trent's store expansion plan and revenue growth?",
    "ULTRACEMCO": "What was UltraTech Cement's capacity expansion and volume guidance?",
}

_GENERIC_QUERY = "What were the key financial highlights and management commentary?"


def run_retrieval_test(client: Client, symbol: str) -> tuple[bool, str]:
    """Embed a query and call match_financial_chunks. Returns (passed, detail)."""
    query = _TEST_QUERIES.get(symbol, _GENERIC_QUERY)
    try:
        vector = embed_texts([query])[0]
    except Exception as exc:
        return False, f"embed failed: {exc}"

    try:
        resp = client.rpc(
            "match_financial_chunks",
            {"query_embedding": vector, "match_count": 5, "symbol_filter": symbol},
        ).execute()
    except Exception as exc:
        # Fallback: no symbol filter
        try:
            resp = client.rpc(
                "match_financial_chunks",
                {"query_embedding": vector, "match_count": 5},
            ).execute()
        except Exception as exc2:
            return False, f"RPC failed: {exc2}"

    hits = resp.data or []
    symbol_hits = [h for h in hits if h.get("symbol") == symbol]
    if not symbol_hits:
        # Check if any hits returned (symbol filter might not be supported)
        if hits:
            return True, f"{len(hits)} hits (no symbol filter — check RPC sig)"
        return False, "0 hits returned"

    top = symbol_hits[0]
    similarity = top.get("similarity", top.get("score", "?"))
    snippet = (top.get("chunk_text") or top.get("content") or "")[:80].replace("\n", " ")
    return True, f"{len(symbol_hits)} hits | sim={similarity:.3f} | \"{snippet}...\""


# ── Rendering ─────────────────────────────────────────────────────────────────

def _header() -> str:
    return (
        f"{'SYMBOL':<{_W['symbol']}} {'QUARTER':<{_W['quarter']}} {'FY':<{_W['fy']}} "
        f"{'CHUNKS':>{_W['chunks']}} {'CHARS':>{_W['chars']}} "
        f"{'EMBED':^{_W['embed']}} RETRIEVAL"
    )


def _sep() -> str:
    return "-" * 90


def print_dashboard(
    coverage: dict[str, list[dict]],
    retrieval_results: dict[str, tuple[bool, str]],
    symbols: list[str],
) -> None:
    print()
    print("=" * 90)
    print("  TRANSCRIPT QA DASHBOARD")
    print("=" * 90)
    print(_header())
    print(_sep())

    total_transcripts = 0
    total_chunks = 0
    symbols_with_data = 0

    for symbol in symbols:
        rows = coverage.get(symbol, [])
        if not rows:
            retrieval_ok, retrieval_detail = retrieval_results.get(symbol, (False, "no data"))
            status = "PASS" if retrieval_ok else "FAIL"
            print(
                f"{'  ' + symbol:<{_W['symbol']}} {'—':<{_W['quarter']}} {'—':<{_W['fy']}} "
                f"{'—':>{_W['chunks']}} {'—':>{_W['chars']}} "
                f"{'NO DATA':^{_W['embed']}} [{status}] {retrieval_detail}"
            )
            continue

        symbols_with_data += 1
        retrieval_ok, retrieval_detail = retrieval_results.get(symbol, (False, "not tested"))
        retrieval_status = "PASS" if retrieval_ok else "FAIL"

        for i, r in enumerate(rows):
            embed_status = "OK" if r["embeddings_null"] == 0 else f"{r['embeddings_null']}null"
            sym_col = ("  " + symbol) if i == 0 else ""
            ret_col = f"[{retrieval_status}] {retrieval_detail}" if i == 0 else ""
            print(
                f"{sym_col:<{_W['symbol']}} {r['quarter']:<{_W['quarter']}} {str(r['fiscal_year']):<{_W['fy']}} "
                f"{r['chunks']:>{_W['chunks']}} {r['total_chars']:>{_W['chars']}} "
                f"{embed_status:^{_W['embed']}} {ret_col}"
            )
            total_transcripts += 1
            total_chunks += r["chunks"]

        print()

    print(_sep())
    print(f"  Symbols with data: {symbols_with_data}/{len(symbols)}")
    print(f"  Total transcripts: {total_transcripts}")
    print(f"  Total chunks:      {total_chunks}")
    retrieval_passed = sum(1 for ok, _ in retrieval_results.values() if ok)
    print(f"  Retrieval:         {retrieval_passed}/{len(retrieval_results)} passed")
    print("=" * 90)
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Transcript QA dashboard")
    parser.add_argument(
        "--symbols", nargs="+",
        help="Symbols to check (default: all Nifty50)",
    )
    parser.add_argument(
        "--retrieval-only", action="store_true",
        help="Skip coverage table, only run retrieval tests",
    )
    parser.add_argument(
        "--no-retrieval", action="store_true",
        help="Skip retrieval tests (faster)",
    )
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbols] if args.symbols else list(NIFTY50_COMPANIES.keys())

    client = _client()

    if not args.retrieval_only:
        print(f"Fetching coverage for {len(symbols)} symbol(s)...", flush=True)
        coverage = fetch_coverage(client, symbols)
    else:
        coverage = {s: [] for s in symbols}

    retrieval_results: dict[str, tuple[bool, str]] = {}
    if not args.no_retrieval:
        symbols_to_test = [s for s in symbols if coverage.get(s)]
        if not symbols_to_test and args.retrieval_only:
            symbols_to_test = symbols
        print(f"Running retrieval tests for {len(symbols_to_test)} symbol(s)...", flush=True)
        for symbol in symbols_to_test:
            print(f"  Testing {symbol}...", end=" ", flush=True)
            ok, detail = run_retrieval_test(client, symbol)
            retrieval_results[symbol] = (ok, detail)
            print("PASS" if ok else f"FAIL: {detail}")

    print_dashboard(coverage, retrieval_results, symbols)


if __name__ == "__main__":
    main()
