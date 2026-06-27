from config.nse500 import NSE500_COMPANIES, NSE500_SYMBOLS
from config.nifty50 import NIFTY50_COMPANIES


def test_nse500_has_minimum_coverage():
    assert len(NSE500_COMPANIES) >= 100, f"Expected ≥100 stocks, got {len(NSE500_COMPANIES)}"


def test_nse500_contains_all_nifty50():
    missing = set(NIFTY50_COMPANIES.keys()) - set(NSE500_COMPANIES.keys())
    assert not missing, f"Nifty 50 stocks missing from NSE 500: {missing}"


def test_nse500_symbols_matches_companies():
    assert set(NSE500_SYMBOLS) == set(NSE500_COMPANIES.keys())


def test_nse500_no_empty_names():
    empty = [sym for sym, name in NSE500_COMPANIES.items() if not name.strip()]
    assert not empty, f"Symbols with empty names: {empty}"


def test_nse500_key_stocks_present():
    key_stocks = ["TCS", "RELIANCE", "INFY", "HDFCBANK", "ICICIBANK"]
    for sym in key_stocks:
        assert sym in NSE500_COMPANIES, f"{sym} missing from NSE 500"
