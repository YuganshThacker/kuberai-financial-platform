import os
from dataclasses import dataclass
from typing import List, Optional
from supabase import Client
from embeddings.embedder import embed_texts

# Feature flag: set ENABLE_ANNUAL_REPORTS=true to include annual report chunks in retrieval.
# When disabled, match_financial_chunks still runs (which queries corporate_documents via
# UNION ALL) but without the ef_search=300 boost. Enabling this flag adds a dedicated
# match_annual_report_chunks call with ef_search=300, ensuring annual report chunks are
# found even when the globally closest vectors in HNSW are transcripts.
_ANNUAL_REPORTS_ENABLED = os.environ.get("ENABLE_ANNUAL_REPORTS", "false").lower() == "true"


@dataclass
class RetrievedChunk:
    chunk_text: str
    symbol: Optional[str]
    source: str
    title: str
    source_url: Optional[str]
    similarity: float


def retrieve_similar_chunks(
    client: Client,
    query: str,
    top_k: int = 10,
    symbol: Optional[str] = None,
) -> List[RetrievedChunk]:
    vector = embed_texts([query])[0]

    # Primary retrieval — transcripts + news + web + corporate_documents (all types)
    response = client.rpc(
        "match_financial_chunks",
        params={
            "query_embedding": vector,
            "match_count": top_k,
            "symbol_filter": symbol,
        },
    ).execute()

    chunks: List[RetrievedChunk] = [
        RetrievedChunk(
            chunk_text=row["chunk_text"],
            symbol=row.get("symbol"),
            source=row["source"],
            title=row["title"],
            source_url=row.get("source_url"),
            similarity=row["similarity"],
        )
        for row in (response.data or [])
    ]

    if _ANNUAL_REPORTS_ENABLED:
        # Dedicated annual report retrieval with ef_search=300 to overcome HNSW
        # candidate starvation when filtering by document_type and symbol.
        ar_response = client.rpc(
            "match_annual_report_chunks",
            params={
                "query_embedding": vector,
                "match_count": top_k,
                "symbol_filter": symbol,
            },
        ).execute()

        seen_texts = {c.chunk_text for c in chunks}
        for row in (ar_response.data or []):
            text = row["chunk_text"]
            if text not in seen_texts:
                seen_texts.add(text)
                chunks.append(
                    RetrievedChunk(
                        chunk_text=text,
                        symbol=row.get("symbol"),
                        source="annual_report",
                        title=row.get("title", "Annual Report"),
                        source_url=row.get("source_url"),
                        similarity=row["similarity"],
                    )
                )

        # Re-rank merged results by similarity, keep top_k
        chunks.sort(key=lambda c: c.similarity, reverse=True)
        chunks = chunks[:top_k]

    return chunks
