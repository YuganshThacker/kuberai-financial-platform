from unittest.mock import patch, MagicMock
from ingestion.market_data.nse_fetcher import fetch_quote, MarketQuote

def test_fetch_quote_returns_market_quote():
    mock_data = {
        "priceInfo": {
            "lastPrice": 3920.5,
            "high": 3950.0,
            "low": 3890.0,
            "52WeekHigh": 4200.0,
            "52WeekLow": 3100.0,
        },
        "marketDeptOrderBook": {
            "tradeInfo": {"totalTradedVolume": 1500000}
        },
        "securityInfo": {},
    }
    with patch("ingestion.market_data.nse_fetcher.nse_eq", return_value=mock_data):
        quote = fetch_quote("TCS")
    assert isinstance(quote, MarketQuote)
    assert quote.price == 3920.5
    assert quote.week_52_high == 4200.0

def test_fetch_quote_returns_none_on_error():
    with patch("ingestion.market_data.nse_fetcher.nse_eq", side_effect=Exception("timeout")):
        quote = fetch_quote("INVALID")
    assert quote is None
