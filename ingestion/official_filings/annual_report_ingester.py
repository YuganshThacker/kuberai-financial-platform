"""
Annual report ingestion: section detection, chunking, embedding, storage.

Pipeline:
  1. Receive pre-fetched text from annual_report_discovery.
  2. Build a section map by scanning for Indian annual-report heading patterns.
  3. Chunk the full text (500 words / chunk, 50-word overlap).
  4. Assign each chunk a section_type based on its estimated position.
  5. Batch-embed (text-embedding-3-small) and upsert to corporate_documents.

Section detection — coarse boundary scanning:
  Scan full text for section-heading regex patterns. Each match establishes
  a boundary: all subsequent text belongs to that section until the next
  heading is detected. Robust to page breaks, headers/footers, and the
  wide formatting variation across Indian annual reports.

Upsert key: (pdf_url, chunk_index) — same as transcripts, fully idempotent.
"""

from __future__ import annotations

import re

from supabase import Client

from embeddings.embedder import embed_texts
from ingestion.nse_bse.pdf_processor import chunk_text
from monitoring.metrics import IngestionMetrics

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

MIN_ANNUAL_REPORT_CHARS = 500_000
MIN_ANNUAL_REPORT_CHUNKS = 200

_UPSERT_BATCH = 5

# ── Section patterns ──────────────────────────────────────────────────────────
# Ordered most-specific first. First matching pattern at a given position wins.

_SECTION_PATTERNS: list[tuple[str, list[str]]] = [
    ("auditor_report", [
        r"independent\s+auditors?'?\s+report",
        r"statutory\s+auditors?'?\s+report",
        r"report\s+of\s+the\s+(?:statutory\s+)?auditors?",
    ]),
    ("financial_statements", [
        r"(?:standalone|consolidated)\s+(?:balance\s+sheet|financial\s+statements?)",
        r"statement\s+of\s+(?:assets\s+and\s+liabilities|profit\s+and\s+loss|cash\s+flows?)",
        r"profit\s+(?:and|&)\s+loss\s+(?:account|statement)",
        r"balance\s+sheet\s+as\s+at",
    ]),
    ("notes", [
        r"notes?\s+to\s+(?:the\s+)?(?:standalone|consolidated)\s+financial\s+statements?",
        r"notes?\s+to\s+(?:the\s+)?accounts?",
        r"significant\s+accounting\s+policies",
        r"note\s+\d+[:\s]",
    ]),
    ("mda", [
        r"management['\s]+(?:discussion|review)\s+(?:and|&)\s+analysis",
        r"management\s+commentary",
        r"business\s+overview\s+and\s+performance",
    ]),
    ("corporate_governance", [
        r"corporate\s+governance\s+report",
        r"report\s+on\s+corporate\s+governance",
    ]),
    ("esg", [
        r"business\s+responsibility\s+(?:and\s+sustainability\s+)?report",
        r"sustainability\s+report",
        r"environmental[,\s]+social\s+(?:and|&)\s+governance",
    ]),
    ("directors_report", [
        r"(?:^|\n)\s*directors['\s]?\s*report\b",
        r"(?:^|\n)\s*board['\s]?\s*report\b",
        r"(?:^|\n)\s*report\s+of\s+the\s+(?:board|directors)",
    ]),
]

_FALLBACK_SECTION = "other"


def _build_section_map(text: str) -> list[tuple[int, str]]:
    """Return sorted (position, section_type) pairs for all heading matches."""
    lower = text.lower()
    boundaries: list[tuple[int, str]] = [(0, _FALLBACK_SECTION)]
    for section_type, patterns in _SECTION_PATTERNS:
        for pat in patterns:
            for m in re.finditer(pat, lower, re.MULTILINE):
                boundaries.append((m.start(), section_type))
    boundaries.sort(key=lambda x: x[0])
    return boundaries


def _section_at(pos: int, boundaries: list[tuple[int, str]]) -> str:
    """Return the section_type active at character position *pos*."""
    result = _FALLBACK_SECTION
    for bnd_pos, bnd_type in boundaries:
        if bnd_pos <= pos:
            result = bnd_type
        else:
            break
    return result


def _estimate_chunk_positions(n_chunks: int, text_len: int) -> list[int]:
    """Uniform-distribution estimate of each chunk's start position.

    Annual report sections span tens-of-thousands of chars; the ±5% error
    from uniform estimation does not cross section boundaries in practice.
    """
    if n_chunks == 0:
        return []
    step = text_len / n_chunks
    return [int(i * step) for i in range(n_chunks)]


# ── Quality gates ─────────────────────────────────────────────────────────────

_ANNUAL_REPORT_KEYWORDS = (
    r"\bdirectors?\s+report\b",
    r"\bauditor[s']?\s+report\b",
    r"\bfinancial\s+statements?\b",
    r"\bboard\s+of\s+directors\b",
    r"\bprofit\s+(?:and|&)\s+loss\b",
    r"\bbalance\s+sheet\b",
    r"\bshareholder[s']?\b",
    r"\bdividend\b",
    r"\bearnings\s+per\s+share\b",
    r"\bmanagement\s+discussion\b",
)
_MIN_KEYWORD_SCORE = 5


def _keyword_score(text: str) -> int:
    lower = text.lower()
    return sum(1 for kw in _ANNUAL_REPORT_KEYWORDS if re.search(kw, lower))


# ── Main ingestion function ───────────────────────────────────────────────────

def ingest_annual_report(
    symbol: str,
    report: dict,
    client: Client,
    metrics: IngestionMetrics,
) -> int:
    """Chunk, embed and store one annual report.

    Args:
        symbol:  NSE equity symbol
        report:  dict from ``discover_annual_reports`` — must include
                 keys: url, fiscal_year, filing_date, title, text
        client:  Supabase client
        metrics: shared IngestionMetrics tracker

    Returns number of chunks stored (0 on failure).
    """
    text = report["text"].replace("\x00", "")  # strip null bytes (Postgres 22P05)
    pdf_url = report["url"]
    fiscal_year = report["fiscal_year"]
    filing_date = report.get("filing_date") or None
    title = report["title"]

    prefix = f"[ar_ingester] {symbol} FY{fiscal_year}"

    # Gate 1 — minimum text length
    if len(text) < MIN_ANNUAL_REPORT_CHARS:
        print(f"{prefix}: too short ({len(text):,} chars < {MIN_ANNUAL_REPORT_CHARS:,})")
        metrics.record_error()
        return 0

    # Gate 2 — keyword validation
    score = _keyword_score(text)
    if score < _MIN_KEYWORD_SCORE:
        print(f"{prefix}: keyword score {score} < {_MIN_KEYWORD_SCORE} — not an annual report")
        metrics.record_error()
        return 0

    print(f"{prefix}: {len(text):,} chars, score={score} — detecting sections...")

    section_boundaries = _build_section_map(text)

    chunks = chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    if len(chunks) < MIN_ANNUAL_REPORT_CHUNKS:
        print(f"{prefix}: only {len(chunks)} chunks — too few")
        metrics.record_error()
        return 0

    positions = _estimate_chunk_positions(len(chunks), len(text))
    section_types = [_section_at(p, section_boundaries) for p in positions]

    section_counts: dict[str, int] = {}
    for st in section_types:
        section_counts[st] = section_counts.get(st, 0) + 1
    print(f"{prefix}: {len(chunks)} chunks — {section_counts}")

    # Embed
    print(f"{prefix}: embedding {len(chunks)} chunks...")
    try:
        vectors = embed_texts(chunks)
    except Exception as exc:
        print(f"{prefix}: embedding failed: {exc}")
        metrics.record_error()
        return 0

    rows = [
        {
            "symbol": symbol,
            "document_type": "annual_report",
            "quarter": None,
            "fiscal_year": fiscal_year,
            "filing_date": filing_date,
            "pdf_url": pdf_url,
            "title": title,
            "chunk_index": i,
            "chunk_text": chunk,
            "embedding": vector,
            "section_type": section_type,
            "discovery_source": "nse_filing",
            "retrieval_method": "direct",
        }
        for i, (chunk, vector, section_type) in enumerate(
            zip(chunks, vectors, section_types)
        )
    ]

    # Batch upsert (idempotent on pdf_url, chunk_index)
    try:
        for start in range(0, len(rows), _UPSERT_BATCH):
            client.table("corporate_documents").upsert(
                rows[start : start + _UPSERT_BATCH],
                on_conflict="pdf_url,chunk_index",
            ).execute()
    except Exception as exc:
        print(f"{prefix}: upsert failed: {exc}")
        metrics.record_error()
        return 0

    metrics.record_pdf(chunks=len(chunks), embeddings=len(chunks))
    print(f"{prefix}: stored {len(chunks)} chunks")
    return len(chunks)
