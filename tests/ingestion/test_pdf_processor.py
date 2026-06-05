import pytest
from ingestion.nse_bse.pdf_processor import extract_text_from_pdf, chunk_text

def test_chunk_text_basic():
    text = "word " * 600
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c.split()) <= 550

def test_chunk_text_single_chunk():
    text = "hello world"
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    assert chunks == ["hello world"]

def test_chunk_text_overlap():
    words = [f"w{i}" for i in range(100)]
    text = " ".join(words)
    chunks = chunk_text(text, chunk_size=60, overlap=10)
    second_chunk_words = chunks[1].split()
    assert second_chunk_words[0].startswith("w")
    first_idx = int(second_chunk_words[0][1:])
    assert first_idx < 60

def test_extract_text_from_pdf_invalid_bytes():
    with pytest.raises(Exception):
        extract_text_from_pdf(b"not a pdf")
