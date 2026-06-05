import httpx

JINA_BASE = "https://r.jina.ai/"
HEADERS = {"Accept": "text/plain", "X-Return-Format": "text"}

def fetch_article_text(url: str, timeout: int = 20) -> str:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(f"{JINA_BASE}{url}", headers=HEADERS)
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPError:
        return ""
