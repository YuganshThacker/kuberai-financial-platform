from unittest.mock import patch
from query.retriever import RetrievedChunk
from query.reranker import rerank


def _make_chunk(text: str, similarity: float = 0.8) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_text=text,
        symbol="TCS",
        source="official_transcript",
        title="TCS Q4FY26 Transcript",
        source_url="https://example.com",
        similarity=similarity,
    )


def test_rerank_fallback_returns_top_k():
    chunks = [_make_chunk(f"chunk {i}", similarity=1.0 - i * 0.05) for i in range(20)]
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("COHERE_API_KEY", None)
        result = rerank("TCS Q4 guidance", chunks, top_k=5)
    assert len(result) == 5
    assert result[0].similarity >= result[-1].similarity


def test_rerank_returns_all_if_fewer_than_top_k():
    chunks = [_make_chunk("only chunk")]
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("COHERE_API_KEY", None)
        result = rerank("TCS revenue", chunks, top_k=10)
    assert len(result) == 1


def test_rerank_empty_input():
    result = rerank("TCS guidance", [], top_k=8)
    assert result == []


def test_rerank_cohere_fallback_on_error():
    chunks = [_make_chunk(f"chunk {i}") for i in range(10)]
    with patch.dict("os.environ", {"COHERE_API_KEY": "fake-key"}), \
         patch("query.reranker._cohere_rerank", side_effect=Exception("API error")):
        result = rerank("TCS revenue", chunks, top_k=5)
    assert len(result) == 5
