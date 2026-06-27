import json
from unittest.mock import MagicMock, patch
from ingestion.official_filings.insight_extractor import (
    extract_and_store_insights,
    get_insights_context,
)

_ENTRY = {
    "url": "https://nsearchives.nseindia.com/corp/TCS/transcript.pdf",
    "quarter": "Q4FY26",
    "fiscal_year": "2026",
    "filing_date": "2026-04-14",
}

_MOCK_INSIGHTS = {
    "management_commentary": "TCS expects strong demand in BFSI vertical.",
    "guidance": "Revenue growth guidance of 8-10% in constant currency for FY27.",
    "capex": "Capex of ₹4,500 crore planned for FY27, primarily data centers.",
    "demand_outlook": "Strong pipeline in North America; Europe remains cautious.",
    "margins": "EBIT margin at 24.5%, guidance for 26-28% band in FY27.",
    "risks": "Currency headwinds and client budget scrutiny in Europe.",
    "qa_highlights": "Analysts asked about deal ramp timelines; management confident on H2.",
}


def test_extract_and_store_insights_success():
    client = MagicMock()
    client.table.return_value.upsert.return_value.execute.return_value = MagicMock()

    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(_MOCK_INSIGHTS)

    with patch("ingestion.official_filings.insight_extractor._get_openai") as mock_openai:
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        result = extract_and_store_insights(client, "TCS", _ENTRY, "transcript text " * 100)

    assert result is True
    client.table.assert_called_with("transcript_insights")


def test_extract_and_store_insights_llm_failure():
    client = MagicMock()

    with patch("ingestion.official_filings.insight_extractor._get_openai") as mock_openai:
        mock_openai.return_value.chat.completions.create.side_effect = Exception("API error")
        result = extract_and_store_insights(client, "TCS", _ENTRY, "some text")

    assert result is False


def test_get_insights_context_formats_output():
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {
            "quarter": "Q4FY26",
            "fiscal_year": "2026",
            "guidance": "8-10% growth",
            "capex": "₹4,500 crore",
            "demand_outlook": "Strong BFSI demand",
            "margins": "24.5% EBIT",
            "risks": "Currency risk",
            "management_commentary": "Positive outlook.",
        }
    ]
    ctx = get_insights_context(client, "TCS", max_quarters=1)
    assert "TCS" in ctx
    assert "Q4FY26" in ctx
    assert "8-10% growth" in ctx
    assert "₹4,500 crore" in ctx


def test_get_insights_context_empty_db():
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
    ctx = get_insights_context(client, "UNKNOWN", max_quarters=4)
    assert ctx == ""
