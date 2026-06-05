import respx
import httpx
from ingestion.youtube.concall_finder import search_concalls, ConcallVideo

@respx.mock
def test_search_concalls_returns_videos():
    mock_response = {
        "items": [
            {
                "id": {"videoId": "abc123"},
                "snippet": {
                    "title": "TCS Q4 FY26 Earnings Call",
                    "channelTitle": "TCS Investor Relations",
                    "publishedAt": "2026-05-01T10:00:00Z",
                }
            }
        ]
    }
    respx.get("https://www.googleapis.com/youtube/v3/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )
    results = search_concalls("TCS", api_key="test-key", max_results=5)
    assert len(results) == 1
    assert isinstance(results[0], ConcallVideo)
    assert results[0].video_id == "abc123"
    assert "TCS" in results[0].title

@respx.mock
def test_search_concalls_handles_api_error():
    respx.get("https://www.googleapis.com/youtube/v3/search").mock(
        return_value=httpx.Response(403, json={"error": {"message": "quota exceeded"}})
    )
    results = search_concalls("TCS", api_key="test-key")
    assert results == []
