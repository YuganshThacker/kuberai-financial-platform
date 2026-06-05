import pytest
import respx
import httpx
from ingestion.nse_bse.filing_scraper import fetch_nse_filings, FilingRecord

@respx.mock
def test_fetch_nse_filings_returns_records():
    symbol = "TCS"
    mock_data = {
        "data": [
            {
                "symbol": "TCS",
                "filingDate": "2026-05-15",
                "description": "Quarterly Financial Results",
                "attachments": "https://archives.nseindia.com/corporate/TCS_Q4FY26.pdf"
            }
        ]
    }
    # Mock home page hit (the implementation hits NSE_BASE first for cookies)
    # NSE_BASE without path redirects to NSE_BASE/ — mock the trailing-slash form
    respx.route(url__startswith="https://www.nseindia.com/api/corp-info").mock(
        return_value=httpx.Response(200, json=mock_data)
    )
    respx.route(url__startswith="https://www.nseindia.com").mock(
        return_value=httpx.Response(200, text="ok")
    )

    records = fetch_nse_filings(symbol)
    assert len(records) == 1
    assert isinstance(records[0], FilingRecord)
    assert records[0].symbol == "TCS"
    assert records[0].pdf_url is not None
    assert records[0].doc_type == "quarterly_result"

@respx.mock
def test_fetch_nse_filings_handles_http_error():
    # Mock home page and then the API returning 404
    respx.route(url__startswith="https://www.nseindia.com/api/corp-info").mock(
        return_value=httpx.Response(404)
    )
    respx.route(url__startswith="https://www.nseindia.com").mock(
        return_value=httpx.Response(200, text="ok")
    )
    records = fetch_nse_filings("FAKE")
    assert records == []
