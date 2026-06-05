from dataclasses import dataclass
from typing import List, Optional
from supabase import Client
from embeddings.embedder import embed_texts

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
    response = client.rpc(
        "match_financial_chunks",
        params={
            "query_embedding": vector,
            "match_count": top_k,
            "symbol_filter": symbol,
        },
    ).execute()

    return [
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
