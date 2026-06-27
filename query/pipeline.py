import os
from dataclasses import dataclass, field
from typing import List, Optional
from openai import OpenAI
from supabase import Client
from config.nse_all_stocks import NSE_ALL_COMPANIES
from query.retriever import retrieve_similar_chunks
from query.sql_lookup import get_latest_metrics, format_metrics_as_context
from query.fallback_search import serper_search
from ingestion.official_filings.insight_extractor import get_insights_context

_api_key = os.environ.get("OPENAI_API_KEY", "")
if not _api_key:
    raise ValueError(
        "OPENAI_API_KEY environment variable is not set. "
        "Set it before importing pipeline."
    )

openai_client = OpenAI(api_key=_api_key)
CONFIDENCE_THRESHOLD = 0.5

# All 2107 NSE-listed stocks — ensures symbol extraction works for any NSE company,
# not just Nifty 50. Updated by scripts/refresh_nse_symbols.py when NSE adds stocks.
KNOWN_SYMBOLS: set[str] = set(NSE_ALL_COMPANIES.keys())


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
    upper = query.upper()
    for sym in KNOWN_SYMBOLS:
        if sym in upper:
            return sym
    return None


def run_query(client: Client, query: str, symbol: Optional[str] = None) -> QueryResult:
    detected_symbol = symbol or _extract_symbol(query)

    try:
        chunks = retrieve_similar_chunks(client, query, top_k=8, symbol=detected_symbol)
    except Exception as exc:
        print(f"[pipeline] Embedding/retrieval failed: {exc}")
        chunks = []

    top_similarity = max((c.similarity for c in chunks), default=0.0)

    context_parts: List[str] = []
    sources: List[Source] = []

    if detected_symbol:
        # Structured transcript insights (guidance, capex, risks) — highest priority context
        try:
            insights_ctx = get_insights_context(client, detected_symbol, max_quarters=4)
            if insights_ctx:
                context_parts.append(insights_ctx)
                sources.append(Source(
                    title=f"{detected_symbol} Earnings Intelligence (Last 4 Quarters)",
                    url=None,
                    source_type="transcript_insights",
                ))
        except Exception as exc:
            print(f"[pipeline] Insights lookup failed for {detected_symbol}: {exc}")

        try:
            metrics = get_latest_metrics(client, detected_symbol)
            if metrics:
                context_parts.append(format_metrics_as_context(metrics))
                sources.append(Source(
                    title=f"{detected_symbol} Market Metrics",
                    url=None,
                    source_type="market_data",
                ))
        except Exception as exc:
            print(f"[pipeline] Metrics lookup failed for {detected_symbol}: {exc}")

    for chunk in chunks:
        context_parts.append(chunk.chunk_text)
        if chunk.source_url:
            sources.append(Source(title=chunk.title, url=chunk.source_url, source_type=chunk.source))

    used_fallback = False
    if top_similarity < CONFIDENCE_THRESHOLD:
        try:
            for r in serper_search(query):
                context_parts.append(f"{r.title}\n{r.snippet}")
                sources.append(Source(title=r.title, url=r.url, source_type="web_search"))
            used_fallback = True
        except Exception as exc:
            print(f"[pipeline] Fallback search failed: {exc}")

    context = "\n\n---\n\n".join(context_parts)
    system_prompt = (
        "You are KuberAI, an expert Indian stock market research assistant. "
        "Answer based only on the provided context. Be concise and cite sources by name. "
        "For numbers (price, PE, revenue), always state units (₹, Cr, %). "
        "If the context is insufficient, say so — do not hallucinate."
    )

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
            ],
            temperature=0.1,
            max_tokens=800,
        )
        answer = response.choices[0].message.content
    except Exception as exc:
        print(f"[pipeline] LLM call failed: {exc}")
        answer = (
            "I'm unable to generate an answer right now due to a service error. "
            "Please try again in a moment."
        )

    return QueryResult(
        answer=answer,
        sources=list({s.url: s for s in sources if s.url}.values()),
        used_fallback=used_fallback,
    )
