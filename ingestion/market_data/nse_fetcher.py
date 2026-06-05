from dataclasses import dataclass
from typing import Optional
from nsepython import nse_eq

@dataclass
class MarketQuote:
    symbol: str
    price: Optional[float]
    day_high: Optional[float]
    day_low: Optional[float]
    week_52_high: Optional[float]
    week_52_low: Optional[float]
    volume: Optional[int]

def fetch_quote(symbol: str) -> Optional[MarketQuote]:
    try:
        data = nse_eq(symbol)
        price_info = data.get("priceInfo", {})
        trade_info = data.get("marketDeptOrderBook", {}).get("tradeInfo", {})
        return MarketQuote(
            symbol=symbol,
            price=price_info.get("lastPrice"),
            day_high=price_info.get("high"),
            day_low=price_info.get("low"),
            week_52_high=price_info.get("52WeekHigh"),
            week_52_low=price_info.get("52WeekLow"),
            volume=trade_info.get("totalTradedVolume"),
        )
    except Exception as e:
        print(f"[nse_fetcher] {symbol}: {e}")
        return None
