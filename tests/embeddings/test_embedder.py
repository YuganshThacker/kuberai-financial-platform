from unittest.mock import patch, MagicMock
from embeddings.embedder import embed_texts


def test_embed_texts_returns_vectors():
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1] * 1536), MagicMock(embedding=[0.2] * 1536)]
    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = mock_response
    with patch("embeddings.embedder._get_client", return_value=mock_client):
        result = embed_texts(["chunk one", "chunk two"])
    assert len(result) == 2
    assert len(result[0]) == 1536


def test_embed_texts_batches_large_input():
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.0] * 1536) for _ in range(100)]
    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = mock_response
    with patch("embeddings.embedder._get_client", return_value=mock_client):
        texts = [f"chunk {i}" for i in range(250)]
        embed_texts(texts, batch_size=100)
    assert mock_client.embeddings.create.call_count == 3
