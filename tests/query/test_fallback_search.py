import respx
import httpx
from query.fallback_search import serper_search, SearchResult

@respx.mock
def test_serper_search_returns_results():
    mock_resp = {
        "organic": [
            {
                "title": "TCS Q4 results beat estimates",
                "link": "https://economictimes.com/tcs",
                "snippet": "TCS reported 10% profit growth",
                "source": "Economic Times",
            }
        ]
    }
    respx.post("https://google.serper.dev/search").mock(
        return_value=httpx.Response(200, json=mock_resp)
    )
    results = serper_search("TCS Q4 FY26 results", api_key="test")
    assert len(results) == 1
    assert isinstance(results[0], SearchResult)
    assert "TCS" in results[0].snippet

@respx.mock
def test_serper_search_returns_empty_on_error():
    respx.post("https://google.serper.dev/search").mock(
        return_value=httpx.Response(429)
    )
    results = serper_search("TCS", api_key="test")
    assert results == []
