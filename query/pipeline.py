import os
from dataclasses import dataclass, field
from typing import List, Optional
from openai import OpenAI
from supabase import Client
from config.nifty50 import NIFTY50_SYMBOLS
from query.retriever import retrieve_similar_chunks
from query.sql_lookup import get_latest_metrics, format_metrics_as_context
from query.fallback_search import serper_search

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
CONFIDENCE_THRESHOLD = 0.5

KNOWN_SYMBOLS: set[str] = set(NIFTY50_SYMBOLS)

@dataclass
class Source:
    title: str
    url: Optional[str]
    source_type: str

@dataclass
class QueryResult:
    answer: str
    sources: List[Source] = field(default_factory=list)
    used_fallback: bool = False

def _extract_symbol(query: str) -> Optional[str]:
    # Substring match handles symbols with special chars (BAJAJ-AUTO, M&M)
    upper = query.upper()
    for sym in KNOWN_SYMBOLS:
        if sym in upper:
            return sym
    return None

def run_query(client: Client, query: str, symbol: Optional[str] = None) -> QueryResult:
    detected_symbol = symbol or _extract_symbol(query)

    chunks = retrieve_similar_chunks(client, query, top_k=8, symbol=detected_symbol)
    top_similarity = max((c.similarity for c in chunks), default=0.0)

    context_parts: List[str] = []
    sources: List[Source] = []

    if detected_symbol:
        metrics = get_latest_metrics(client, detected_symbol)
        if metrics:
            context_parts.append(format_metrics_as_context(metrics))
            sources.append(Source(
                title=f"{detected_symbol} Market Metrics",
                url=None,
                source_type="market_data",
            ))

    for chunk in chunks:
        context_parts.append(chunk.chunk_text)
        if chunk.source_url:
            sources.append(Source(title=chunk.title, url=chunk.source_url, source_type=chunk.source))

    used_fallback = False
    if top_similarity < CONFIDENCE_THRESHOLD:
        for r in serper_search(query):
            context_parts.append(f"{r.title}\n{r.snippet}")
            sources.append(Source(title=r.title, url=r.url, source_type="web_search"))
        used_fallback = True

    context = "\n\n---\n\n".join(context_parts)
    system_prompt = (
        "You are KuberAI, an expert Indian stock market research assistant. "
        "Answer based only on the provided context. Be concise and cite sources by name. "
        "For numbers (price, PE, revenue), always state units (₹, Cr, %). "
        "If the context is insufficient, say so — do not hallucinate."
    )

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
        ],
        temperature=0.1,
        max_tokens=800,
    )

    return QueryResult(
        answer=response.choices[0].message.content,
        sources=list({s.url: s for s in sources if s.url}.values()),
        used_fallback=used_fallback,
    )
