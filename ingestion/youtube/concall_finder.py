import httpx
from dataclasses import dataclass
from typing import List, Optional

YT_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

@dataclass
class ConcallVideo:
    video_id: str
    title: str
    channel: str
    published_at: Optional[str]

def search_concalls(
    symbol: str,
    api_key: str,
    max_results: int = 10,
) -> List[ConcallVideo]:
    query = f"{symbol} concall earnings call investor Q4 Q3 FY26"
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "order": "date",
        "key": api_key,
    }
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(YT_SEARCH_URL, params=params)
            resp.raise_for_status()
            items = resp.json().get("items", [])
    except httpx.HTTPError as e:
        print(f"[youtube] search error for {symbol}: {e}")
        return []

    return [
        ConcallVideo(
            video_id=item["id"]["videoId"],
            title=item["snippet"]["title"],
            channel=item["snippet"]["channelTitle"],
            published_at=item["snippet"].get("publishedAt"),
        )
        for item in items
        if item.get("id", {}).get("videoId")
    ]
