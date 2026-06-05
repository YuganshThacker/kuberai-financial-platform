from unittest.mock import MagicMock, patch
from query.pipeline import run_query, QueryResult

def test_run_query_returns_result_with_sources():
    mock_client = MagicMock()
    mock_chunks = [
        MagicMock(chunk_text="TCS revenue grew 10%", title="TCS Q4", source="documents",
                  source_url="https://example.com", similarity=0.9, symbol="TCS")
    ]
    mock_metrics = MagicMock()
    mock_metrics.price = 3920.5

    with patch("query.pipeline.retrieve_similar_chunks", return_value=mock_chunks), \
         patch("query.pipeline.get_latest_metrics", return_value=mock_metrics), \
         patch("query.pipeline.format_metrics_as_context", return_value="Price: ₹3920.50"), \
         patch("query.pipeline.serper_search", return_value=[]), \
         patch("query.pipeline.openai_client") as mock_openai:
        mock_openai.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content="TCS had strong Q4."))
        ]
        result = run_query(mock_client, "How is TCS doing?", symbol="TCS")

    assert isinstance(result, QueryResult)
    assert len(result.sources) >= 1
    assert result.answer == "TCS had strong Q4."

def test_run_query_triggers_fallback_on_low_confidence():
    mock_client = MagicMock()
    mock_chunks = [
        MagicMock(chunk_text="irrelevant", title="other", source="documents",
                  source_url=None, similarity=0.3, symbol=None)
    ]
    mock_fallback = [MagicMock(title="Fresh news", url="https://x.com", snippet="TCS news", source="web")]

    with patch("query.pipeline.retrieve_similar_chunks", return_value=mock_chunks), \
         patch("query.pipeline.get_latest_metrics", return_value=None), \
         patch("query.pipeline.serper_search", return_value=mock_fallback) as mock_serper, \
         patch("query.pipeline.openai_client") as mock_openai:
        mock_openai.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content="answer"))
        ]
        run_query(mock_client, "latest TCS news")

    mock_serper.assert_called_once()
