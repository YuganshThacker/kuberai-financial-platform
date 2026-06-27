import io
from typing import List
import pdfplumber

# PyMuPDF (fitz) is optional but preferred for digitally-signed PDFs where
# pdfplumber returns sparse text due to font encoding (e.g. Apollo Hospitals).
try:
    import fitz as _fitz
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

_PDFPLUMBER_MIN_CHARS = 500  # if pdfplumber extracts fewer than this, try PyMuPDF


def extract_text_from_pdf_pymupdf(pdf_bytes: bytes) -> str:
    """Extract text using PyMuPDF. Returns '' if PyMuPDF is unavailable."""
    if not _FITZ_AVAILABLE:
        return ""
    doc = _fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = [page.get_text() or "" for page in doc]
    return "\n".join(pages).strip()


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    text = "\n".join(pages).strip()

    if len(text) < _PDFPLUMBER_MIN_CHARS and _FITZ_AVAILABLE:
        fitz_text = extract_text_from_pdf_pymupdf(pdf_bytes)
        if len(fitz_text) > len(text):
            return fitz_text

    return text

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    words = text.split()
    if len(words) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap
    return chunks
