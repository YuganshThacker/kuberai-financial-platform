from unittest.mock import MagicMock, patch
from ingestion.official_filings.transcript_ingester import ingest_transcripts
from ingestion.official_filings.nse_fetcher import FetchResult
from monitoring.metrics import IngestionMetrics


_MOCK_ENTRY = {
    "url": "https://nsearchives.nseindia.com/corp/TCS/transcript.pdf",
    "title": "Earnings Call Transcript Q4FY26",
    "filing_date": "2026-04-14",
    "quarter": "Q4FY26",
    "fiscal_year": "2026",
    "description": "Transcript of Earnings Call",
}

_LONG_TEXT = (
    "Operator: Good morning, participants. Welcome to the TCS Q4 FY2026 earnings call. "
    "Management: Thank you. TCS reported strong Q4 results with revenue of 63,973 crore. "
    "Analyst question: What is your guidance for next quarter? "
    "Management: We see continued momentum across verticals. "
) * 100


def _fetch_result(text: str) -> FetchResult:
    """Build a minimal FetchResult for testing."""
    return FetchResult(
        text=text,
        url="https://nsearchives.nseindia.com/corp/TCS/transcript.pdf",
        is_letter=False,
        url_method=None,
        recovered=False,
    )


def test_ingest_transcripts_success():
    client = MagicMock()
    client.table.return_value.upsert.return_value.execute.return_value = MagicMock()
    metrics = IngestionMetrics("test")

    with patch("ingestion.official_filings.transcript_ingester.fetch_announcements", return_value=[
            {
                "an_dt": "14-Apr-2026 10:00:00",
                "attchmntText": "Transcript of Earnings Call",
                "attchmntFile": "https://nsearchives.nseindia.com/corp/TCS/transcript.pdf",
            }
        ]), \
         patch("ingestion.official_filings.transcript_ingester.download_and_extract_with_fallback",
               return_value=_fetch_result(_LONG_TEXT)), \
         patch("ingestion.official_filings.transcript_ingester.embed_texts", return_value=[[0.1] * 1536] * 3), \
         patch("ingestion.official_filings.transcript_ingester.extract_and_store_insights", return_value=True):
        result = ingest_transcripts("TCS", client, metrics)

    assert result == 1
    assert metrics.pdfs_processed == 1
    assert metrics.chunks_created > 0


def test_ingest_transcripts_skips_short_text():
    client = MagicMock()
    metrics = IngestionMetrics("test")

    with patch("ingestion.official_filings.transcript_ingester.fetch_announcements", return_value=[
            {
                "an_dt": "14-Apr-2026 10:00:00",
                "attchmntText": "Transcript of Earnings Call",
                "attchmntFile": "https://nsearchives.nseindia.com/corp/TCS/transcript.pdf",
            }
        ]), \
         patch("ingestion.official_filings.transcript_ingester.download_and_extract_with_fallback",
               return_value=_fetch_result("Too short")):
        result = ingest_transcripts("TCS", client, metrics)

    assert result == 0
    assert metrics.errors == 1


def test_ingest_transcripts_handles_api_failure():
    client = MagicMock()
    metrics = IngestionMetrics("test")

    with patch("ingestion.official_filings.transcript_ingester.fetch_announcements",
               side_effect=Exception("NSE timeout")):
        result = ingest_transcripts("TCS", client, metrics)

    assert result == 0
    assert metrics.errors == 1
