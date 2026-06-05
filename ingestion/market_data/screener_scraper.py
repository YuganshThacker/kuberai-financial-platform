import re
import httpx
from dataclasses import dataclass
from typing import Optional
from bs4 import BeautifulSoup

SCREENER_BASE = "https://www.screener.in/company"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KuberAI/1.0)"}

@dataclass
class ScreenerData:
    symbol: str
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    roe: Optional[float] = None
    roce: Optional[float] = None
    debt_to_equity: Optional[float] = None
    market_cap_cr: Optional[float] = None

def _parse_float(text: str) -> Optional[float]:
    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None

def fetch_screener_ratios(symbol: str) -> Optional[ScreenerData]:
    url = f"{SCREENER_BASE}/{symbol}/"
    try:
        with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError:
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    data = ScreenerData(symbol=symbol)

    for li in soup.select("li.flex.flex-space-between"):
        name_el = li.select_one(".name")
        value_el = li.select_one(".nowrap.value") or li.select_one(".value")
        if not name_el or not value_el:
            continue
        name = name_el.get_text(strip=True).lower()
        val = _parse_float(value_el.get_text(strip=True))
        if val is None:
            continue
        if name == "p/e":
            data.pe_ratio = val
        elif name == "p/b":
            data.pb_ratio = val
        elif name == "roe":
            data.roe = val
        elif name == "roce":
            data.roce = val
        elif "debt to equity" in name:
            data.debt_to_equity = val
        elif "market cap" in name:
            data.market_cap_cr = val

    return data
