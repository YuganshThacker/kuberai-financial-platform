from fastapi import APIRouter
from db.client import get_client
from query.sql_lookup import get_latest_metrics

router = APIRouter()

@router.get("/sources/{symbol}")
def get_symbol_sources(symbol: str):
    client = get_client()
    sym = symbol.upper()
    metrics = get_latest_metrics(client, sym)
    doc_count = (
        client.table("documents").select("id", count="exact").eq("symbol", sym).execute().count
    )
    news_count = (
        client.table("news_articles").select("id", count="exact").contains("symbols", [sym]).execute().count
    )
    transcript_count = (
        client.table("transcripts").select("id", count="exact").eq("symbol", sym).execute().count
    )
    web_count = (
        client.table("web_search_results").select("id", count="exact").eq("symbol", sym).execute().count
    )
    return {
        "symbol": sym,
        "has_market_data": metrics is not None,
        "latest_price": metrics.price if metrics else None,
        "document_chunks": doc_count,
        "news_chunks": news_count,
        "transcript_chunks": transcript_count,
        "web_search_chunks": web_count,
    }
