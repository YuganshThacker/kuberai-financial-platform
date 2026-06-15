from typing import List, Optional
from supabase import Client


def upsert_web_search_chunks(
    client: Client,
    symbol: str,
    url: str,
    title: str,
    source_domain: str,
    published_at: Optional[str],
    chunks: List[str],
    vectors: List[List[float]],
) -> None:
    rows = [
        {
            "symbol": symbol,
            "url": url,
            "title": title,
            "source_domain": source_domain,
            "published_at": published_at,
            "chunk_index": i,
            "chunk_text": chunk,
            "embedding": vector,
        }
        for i, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    client.table("web_search_results").upsert(rows, on_conflict="url,chunk_index").execute()

def upsert_document_chunks(
    client: Client,
    symbol: str,
    doc_type: str,
    title: str,
    source_url: Optional[str],
    filing_date: Optional[str],
    fiscal_year: Optional[str],
    fiscal_quarter: Optional[str],
    chunks: List[str],
    vectors: List[List[float]],
) -> None:
    rows = [
        {
            "symbol": symbol,
            "doc_type": doc_type,
            "title": title,
            "source_url": source_url,
            "filing_date": filing_date,
            "fiscal_year": fiscal_year,
            "fiscal_quarter": fiscal_quarter,
            "chunk_index": i,
            "chunk_text": chunk,
            "embedding": vector,
        }
        for i, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    client.table("documents").upsert(rows).execute()


def upsert_news_chunks(
    client: Client,
    title: str,
    url: str,
    source: str,
    published_at: Optional[str],
    symbols: List[str],
    chunks: List[str],
    vectors: List[List[float]],
) -> None:
    rows = [
        {
            "title": title,
            "url": url,
            "source": source,
            "published_at": published_at,
            "symbols": symbols,
            "chunk_index": i,
            "chunk_text": chunk,
            "embedding": vector,
        }
        for i, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    client.table("news_articles").upsert(rows).execute()


def upsert_transcript_chunks(
    client: Client,
    symbol: str,
    source_type: str,
    title: str,
    video_id: Optional[str],
    channel: Optional[str],
    published_at: Optional[str],
    fiscal_quarter: Optional[str],
    fiscal_year: Optional[str],
    chunks: List[str],
    vectors: List[List[float]],
) -> None:
    rows = [
        {
            "symbol": symbol,
            "source_type": source_type,
            "video_id": video_id,
            "title": title,
            "channel": channel,
            "published_at": published_at,
            "fiscal_quarter": fiscal_quarter,
            "fiscal_year": fiscal_year,
            "chunk_index": i,
            "chunk_text": chunk,
            "embedding": vector,
        }
        for i, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    client.table("transcripts").upsert(rows).execute()
