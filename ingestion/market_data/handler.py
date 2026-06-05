from datetime import date
from db.client import get_client
from ingestion.market_data.nse_fetcher import fetch_quote
from ingestion.market_data.screener_scraper import fetch_screener_ratios

NIFTY_500_SYMBOLS = [
    "TCS", "INFY", "HDFCBANK", "RELIANCE", "ICICIBANK",
    "WIPRO", "HCLTECH", "LTI", "TECHM", "AXISBANK",
    "BAJFINANCE", "SBIN", "TATASTEEL", "MARUTI", "NESTLEIND",
    "POWERGRID", "NTPC", "ONGC", "COALINDIA",
]

def upsert_market_metrics(client, symbol: str, quote, screener) -> None:
    today = str(date.today())
    row = {"symbol": symbol, "as_of_date": today}
    if quote:
        row.update({
            "price": quote.price,
            "day_high": quote.day_high,
            "day_low": quote.day_low,
            "week_52_high": quote.week_52_high,
            "week_52_low": quote.week_52_low,
            "volume": quote.volume,
        })
    if screener:
        row.update({
            "pe_ratio": screener.pe_ratio,
            "pb_ratio": screener.pb_ratio,
            "roe": screener.roe,
            "roce": screener.roce,
            "debt_to_equity": screener.debt_to_equity,
            "market_cap_cr": screener.market_cap_cr,
        })
    client.table("market_metrics").upsert(row, on_conflict="symbol,as_of_date").execute()


def lambda_handler(event: dict, context) -> dict:
    """Triggered by EventBridge daily at market close (15:45 IST)."""
    client = get_client()
    symbols = event.get("symbols", NIFTY_500_SYMBOLS)
    success = 0
    for symbol in symbols:
        try:
            quote = fetch_quote(symbol)
            screener = fetch_screener_ratios(symbol)
            if quote or screener:
                upsert_market_metrics(client, symbol, quote, screener)
                success += 1
        except Exception as e:
            print(f"[market_data] {symbol}: {e}")
    return {"statusCode": 200, "updated": success}
