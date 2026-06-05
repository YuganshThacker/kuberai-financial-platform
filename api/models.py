from pydantic import BaseModel
from typing import List, Optional

class QueryRequest(BaseModel):
    query: str
    symbol: Optional[str] = None

class SourceResponse(BaseModel):
    title: str
    url: Optional[str]
    source_type: str

class QueryResponse(BaseModel):
    answer: str
    sources: List[SourceResponse]
    used_fallback: bool
