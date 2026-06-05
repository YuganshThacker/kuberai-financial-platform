import os
import httpx
from dataclasses import dataclass
from typing import List

SERPER_URL = "https://google.serper.dev/search"

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str

def serper_search(query: str, api_key: str = "", num: int = 5) -> List[SearchResult]:
    key = api_key or os.environ.get("SERPER_API_KEY", "")
    if not key:
        return []
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                SERPER_URL,
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                json={
                    "q": query + " site:moneycontrol.com OR site:economictimes.com OR site:screener.in",
                    "num": num,
                },
            )
            resp.raise_for_status()
    except httpx.HTTPError:
        return []

    return [
        SearchResult(
            title=r.get("title", ""),
            url=r.get("link", ""),
            snippet=r.get("snippet", ""),
            source=r.get("source", "web"),
        )
        for r in resp.json().get("organic", [])
    ]
