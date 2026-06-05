import respx
import httpx
from ingestion.market_data.screener_scraper import fetch_screener_ratios, ScreenerData

MOCK_HTML = """
<html><body>
<li class="flex flex-space-between"><span class="name">P/E</span><span class="nowrap value">28.5</span></li>
<li class="flex flex-space-between"><span class="name">P/B</span><span class="nowrap value">11.2</span></li>
<li class="flex flex-space-between"><span class="name">ROE</span><span class="nowrap value">47.3%</span></li>
<li class="flex flex-space-between"><span class="name">ROCE</span><span class="nowrap value">63.1%</span></li>
<li class="flex flex-space-between"><span class="name">Debt to equity</span><span class="nowrap value">0.12</span></li>
</body></html>
"""

@respx.mock
def test_fetch_screener_ratios_parses_html():
    respx.get("https://www.screener.in/company/TCS/").mock(
        return_value=httpx.Response(200, text=MOCK_HTML)
    )
    result = fetch_screener_ratios("TCS")
    assert isinstance(result, ScreenerData)
    assert result.pe_ratio == 28.5
    assert result.roe == 47.3
    assert result.debt_to_equity == 0.12

@respx.mock
def test_fetch_screener_ratios_returns_none_on_error():
    respx.get("https://www.screener.in/company/FAKE/").mock(
        return_value=httpx.Response(404)
    )
    result = fetch_screener_ratios("FAKE")
    assert result is None
