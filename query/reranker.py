"""
Reranker for KuberAI retrieval pipeline.

Given N candidate chunks (retrieved by vector similarity), reranks them by
true relevance to the query and returns the top_k best.

Strategy:
  - If COHERE_API_KEY is set: Cohere Rerank API (best quality, ~$1/1000 calls)
  - Otherwise: pass-through (returns top_k from the already-sorted vector results)

The retriever fetches top_k * 4 candidates from match_financial_chunks and passes
them here, so even the fallback mode benefits from a larger candidate pool across
all 5 source tables.

Usage:
    from query.reranker import rerank
    top8 = rerank(query="TCS Q4 guidance", chunks=candidates_25, top_k=8)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from query.retriever import RetrievedChunk


def _cohere_rerank(
    query: str,
    chunks: list["RetrievedChunk"],
    top_k: int,
) -> list["RetrievedChunk"]:
    """Rerank using Cohere Rerank API (requires COHERE_API_KEY)."""
    import httpx

    api_key = os.environ["COHERE_API_KEY"]
    documents = [c.chunk_text for c in chunks]

    resp = httpx.post(
        "https://api.cohere.com/v1/rerank",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "rerank-english-v3.0",
            "query": query,
            "documents": documents,
            "top_n": top_k,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    ranked: list["RetrievedChunk"] = []
    for result in data["results"]:
        idx = result["index"]
        chunk = chunks[idx]
        # Cohere returns a relevance_score in [0, 1]; store it as similarity
        chunk_copy = type(chunk)(
            chunk_text=chunk.chunk_text,
            symbol=chunk.symbol,
            source=chunk.source,
            title=chunk.title,
            source_url=chunk.source_url,
            similarity=result["relevance_score"],
        )
        ranked.append(chunk_copy)
    return ranked


def rerank(
    query: str,
    chunks: list["RetrievedChunk"],
    top_k: int,
) -> list["RetrievedChunk"]:
    """Rerank chunks by relevance to query, return top_k.

    Falls back to the already-sorted vector results if Cohere is not configured
    or if there are fewer candidates than top_k.
    """
    if not chunks:
        return []

    if len(chunks) <= top_k:
        return chunks

    cohere_key = os.environ.get("COHERE_API_KEY", "")
    if cohere_key:
        try:
            return _cohere_rerank(query, chunks, top_k)
        except Exception as exc:
            print(f"[reranker] Cohere rerank failed (falling back to vector order): {exc}")

    # Fallback: chunks are already sorted by cosine similarity from the SQL function
    return chunks[:top_k]
