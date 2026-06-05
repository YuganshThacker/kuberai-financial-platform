from fastapi import APIRouter, HTTPException
from api.models import QueryRequest, QueryResponse, SourceResponse
from db.client import get_client
from query.pipeline import run_query

router = APIRouter()

@router.post("/query", response_model=QueryResponse)
def query_endpoint(req: QueryRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    client = get_client()
    result = run_query(client, req.query, symbol=req.symbol)
    return QueryResponse(
        answer=result.answer,
        sources=[SourceResponse(title=s.title, url=s.url, source_type=s.source_type) for s in result.sources],
        used_fallback=result.used_fallback,
    )
