from unittest.mock import MagicMock
from embeddings.upserter import upsert_document_chunks, upsert_news_chunks

def test_upsert_document_chunks_calls_supabase():
    mock_client = MagicMock()
    mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock()
    chunks = ["text one", "text two"]
    vectors = [[0.1] * 1536, [0.2] * 1536]
    upsert_document_chunks(
        client=mock_client,
        symbol="TCS",
        doc_type="annual_report",
        title="TCS AR FY26",
        source_url="https://example.com",
        filing_date="2026-05-01",
        fiscal_year="FY26",
        fiscal_quarter=None,
        chunks=chunks,
        vectors=vectors,
    )
    mock_client.table.assert_called_with("documents")
    call_args = mock_client.table.return_value.upsert.call_args[0][0]
    assert len(call_args) == 2
    assert call_args[0]["chunk_index"] == 0
    assert call_args[1]["chunk_index"] == 1
    assert call_args[0]["symbol"] == "TCS"

def test_upsert_news_chunks_calls_supabase():
    mock_client = MagicMock()
    mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock()
    upsert_news_chunks(
        client=mock_client,
        title="TCS Q4 results",
        url="https://news.com/tcs",
        source="economic_times",
        published_at="2026-05-15T10:00:00Z",
        symbols=["TCS"],
        chunks=["chunk a"],
        vectors=[[0.3] * 1536],
    )
    mock_client.table.assert_called_with("news_articles")
