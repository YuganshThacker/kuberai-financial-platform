import respx
import httpx
from ingestion.news.content_fetcher import fetch_article_text

@respx.mock
def test_fetch_article_text_returns_content():
    target_url = "https://economictimes.com/tcs-q4"
    jina_url = f"https://r.jina.ai/{target_url}"
    respx.get(jina_url).mock(return_value=httpx.Response(200, text="TCS reported strong Q4 results..."))

    result = fetch_article_text(target_url)
    assert "TCS" in result

@respx.mock
def test_fetch_article_text_returns_empty_on_error():
    target_url = "https://broken.com/article"
    jina_url = f"https://r.jina.ai/{target_url}"
    respx.get(jina_url).mock(return_value=httpx.Response(429))

    result = fetch_article_text(target_url)
    assert result == ""
