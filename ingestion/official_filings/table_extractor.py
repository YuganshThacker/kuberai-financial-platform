"""
Free, CPU-only table extraction for investor presentations (and any tabular PDF).

Investor-presentation decks are chart/table heavy — the value (revenue, segment,
guidance, margin numbers) lives in tables that PyMuPDF's plain text layer turns
into an unreadable jumble. pdfplumber recovers the row/column structure so the
LLM can read e.g. "Total Revenue | Q2FY26 37,403 | Q2FY25 33,704 | +11%".

This module extracts tables, filters out noise (contact/dial-in lists, agendas),
and renders the financial ones as compact pipe-delimited text blocks suitable for
embedding as standalone retrieval chunks.

Zero API cost. Prototype on real decks showed BAJAJFINSV alone yielding ~1,600
structured numeric cells the text layer had scrambled.
"""
from __future__ import annotations

import io
import re

_NUM = re.compile(r"-?\d[\d,]*\.?\d*%?")

# A table is kept only if it looks like financial/quantitative data, not a
# contact sheet, dial-in list, or agenda.
_NOISE_HINTS = (
    "dial", "phone", "tel:", "tel.", "host", "moderator", "email", "e-mail",
    "@", "password", "passcode", "webcast link", "conference id", "pin",
)
_FIN_HINTS = (
    "revenue", "profit", "ebitda", "margin", "growth", "yoy", "q1", "q2", "q3", "q4",
    "fy", "income", "assets", "net worth", "aum", "nim", "roe", "roce", "eps",
    "₹", "cr", "crore", "%", "segment", "guidance", "capex", "pat", "pbt",
)

MAX_PAGES = 80          # bound runtime on very large decks
MIN_ROWS = 2
MIN_NUMERIC_FRACTION = 0.20   # ≥20% of cells must be numeric
MAX_TABLES = 40         # cap chunks per deck


def _clean(cell) -> str:
    return (cell or "").strip().replace("\n", " ")


def _is_financial(rows: list[list[str]]) -> bool:
    cells = [_clean(c) for row in rows for c in row if _clean(c)]
    if not cells:
        return False
    blob = " ".join(cells).lower()
    if any(h in blob for h in _NOISE_HINTS):
        return False
    numeric = sum(1 for c in cells if _NUM.search(c))
    if numeric / len(cells) < MIN_NUMERIC_FRACTION:
        return False
    # require at least one financial keyword so we don't keep random numeric grids
    return any(h in blob for h in _FIN_HINTS)


def _render(rows: list[list[str]]) -> str:
    """Pipe-delimited text block; keeps header + row labels with their numbers."""
    out = []
    for row in rows:
        cleaned = [_clean(c) for c in row]
        if any(cleaned):
            out.append(" | ".join(c for c in cleaned))
    return "\n".join(out)


def extract_tables_as_text(pdf_bytes: bytes) -> list[str]:
    """Return a list of formatted financial-table text blocks from a PDF.

    Empty list if pdfplumber is unavailable, the PDF has no usable tables, or all
    tables are noise. Never raises.
    """
    try:
        import pdfplumber
    except ImportError:
        return []

    blocks: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages[:MAX_PAGES]:
                try:
                    tables = page.extract_tables() or []
                except Exception:
                    continue
                for tbl in tables:
                    rows = [r for r in tbl if any(_clean(c) for c in r)]
                    if len(rows) < MIN_ROWS:
                        continue
                    if not _is_financial(rows):
                        continue
                    block = _render(rows)
                    if len(block) >= 40:
                        blocks.append(block)
                    if len(blocks) >= MAX_TABLES:
                        return blocks
    except Exception:
        return blocks
    return blocks
