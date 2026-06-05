from unittest.mock import MagicMock, patch
from query.retriever import retrieve_similar_chunks, RetrievedChunk

def test_retrieve_similar_chunks_returns_chunks():
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value.data = [
        {
            "chunk_text": "TCS reported revenue of 62,613 crore",
            "symbol": "TCS",
            "source": "documents",
            "title": "TCS Q4 FY26 Results",
            "source_url": "https://example.com",
            "similarity": 0.92,
        }
    ]
    with patch("query.retriever.embed_texts", return_value=[[0.1] * 1536]):
        chunks = retrieve_similar_chunks(mock_client, "TCS revenue Q4", top_k=5)
    assert len(chunks) == 1
    assert isinstance(chunks[0], RetrievedChunk)
    assert chunks[0].similarity == 0.92

def test_retrieve_similar_chunks_filters_by_symbol():
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value.data = []
    with patch("query.retriever.embed_texts", return_value=[[0.1] * 1536]):
        retrieve_similar_chunks(mock_client, "quarterly results", symbol="INFY", top_k=5)
    call_kwargs = mock_client.rpc.call_args[1]
    assert call_kwargs["params"]["symbol_filter"] == "INFY"
