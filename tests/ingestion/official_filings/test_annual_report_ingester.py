"""
Unit tests for annual report ingestion: section detection, quality gates, chunking.

All tests are offline (no NSE API, no Supabase, no OpenAI).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ingestion.official_filings.annual_report_ingester import (
    MIN_ANNUAL_REPORT_CHUNKS,
    MIN_ANNUAL_REPORT_CHARS,
    _build_section_map,
    _estimate_chunk_positions,
    _keyword_score,
    _section_at,
    ingest_annual_report,
)


# ── Section detection ─────────────────────────────────────────────────────────

class TestBuildSectionMap:
    def test_empty_text_returns_other_origin(self):
        bmap = _build_section_map("")
        assert bmap[0] == (0, "other")

    def test_detects_mda_heading(self):
        text = "some preamble\n\nManagement Discussion and Analysis\nrevenue grew 12%"
        bmap = _build_section_map(text)
        sections_found = {s for _, s in bmap}
        assert "mda" in sections_found

    def test_detects_auditor_report(self):
        text = "INDEPENDENT AUDITORS' REPORT\nTo the Members of Reliance Industries"
        bmap = _build_section_map(text)
        assert any(s == "auditor_report" for _, s in bmap)

    def test_detects_financial_statements(self):
        text = "Consolidated Balance Sheet as at March 31, 2026"
        bmap = _build_section_map(text)
        assert any(s == "financial_statements" for _, s in bmap)

    def test_detects_notes(self):
        text = "Notes to the Consolidated Financial Statements\nNote 1: Accounting Policies"
        bmap = _build_section_map(text)
        assert any(s == "notes" for _, s in bmap)

    def test_detects_directors_report(self):
        text = "\nDirectors' Report\nTo the Members"
        bmap = _build_section_map(text)
        assert any(s == "directors_report" for _, s in bmap)

    def test_boundaries_are_sorted(self):
        text = (
            "Directors' Report\n" * 1 +
            "Management Discussion and Analysis\n" * 1 +
            "Independent Auditors' Report\n" * 1
        )
        bmap = _build_section_map(text)
        positions = [p for p, _ in bmap]
        assert positions == sorted(positions)

    def test_section_at_uses_last_boundary_before_pos(self):
        # Simulate a document: other → directors_report → mda
        bmap = [
            (0, "other"),
            (100, "directors_report"),
            (500, "mda"),
        ]
        assert _section_at(0, bmap) == "other"
        assert _section_at(50, bmap) == "other"
        assert _section_at(100, bmap) == "directors_report"
        assert _section_at(300, bmap) == "directors_report"
        assert _section_at(500, bmap) == "mda"
        assert _section_at(9999, bmap) == "mda"


class TestEstimateChunkPositions:
    def test_zero_chunks_returns_empty(self):
        assert _estimate_chunk_positions(0, 10000) == []

    def test_single_chunk_starts_at_zero(self):
        assert _estimate_chunk_positions(1, 10000) == [0]

    def test_positions_are_increasing(self):
        positions = _estimate_chunk_positions(10, 100000)
        assert positions == sorted(positions)
        assert positions[0] == 0

    def test_last_position_is_less_than_text_len(self):
        positions = _estimate_chunk_positions(100, 500000)
        assert all(p < 500000 for p in positions)


# ── Keyword score ─────────────────────────────────────────────────────────────

class TestKeywordScore:
    def test_real_annual_report_text_passes(self):
        text = """
        Directors' Report. The auditors' report is attached.
        Financial statements show profit and loss.
        Balance sheet as at March 31.
        Shareholders approved the dividend.
        Management discussion of performance.
        """
        assert _keyword_score(text) >= 3

    def test_unrelated_text_fails(self):
        text = "The quick brown fox jumps over the lazy dog. Lorem ipsum dolor sit amet."
        assert _keyword_score(text) < 3

    def test_transcript_text_partially_scores(self):
        # Transcripts mention management but not auditors, balance sheet, etc.
        text = (
            "Operator: Good morning everyone. "
            "Management: Revenue grew 12% this quarter. "
            "Analyst: What is your guidance for next quarter? "
            "Q&A session continues. Earnings per share increased."
        )
        # Should score lower than a real annual report
        score = _keyword_score(text)
        assert score < 5  # some hits but not a full annual report


# ── ingest_annual_report ──────────────────────────────────────────────────────

def _make_report(text: str, fy: str = "2026") -> dict:
    return {
        "url": f"https://nsearchives.nseindia.com/test_{fy}.pdf",
        "fiscal_year": fy,
        "filing_date": f"{fy}-06-01",
        "title": f"TEST Annual Report FY{fy}",
        "text": text,
        "text_len": len(text),
    }


def _real_report_text(n_chars: int = 900_000) -> str:
    """Generate synthetic annual report text that passes all quality gates."""
    section_headers = (
        "\nDirectors' Report\nTo the Members\n"
        "\nManagement Discussion and Analysis\n"
        "\nConsolidated Balance Sheet as at March 31, 2026\n"
        "\nProfit and Loss Statement\n"
        "\nIndependent Auditors' Report\n"
        "\nNotes to the Consolidated Financial Statements\n"
        "\nDividend declared. Shareholders approved. Earnings per share 42.5\n"
        "\nBoard of Directors met four times during the year.\n"
    )
    filler = "Revenue grew significantly. Financial statements prepared under Ind AS. " * 200
    combined = section_headers + filler
    # Stretch or trim to n_chars
    while len(combined) < n_chars:
        combined += filler
    return combined[:n_chars]


@patch("ingestion.official_filings.annual_report_ingester.embed_texts")
def test_ingest_annual_report_success(mock_embed):
    """Happy-path: returns chunk count, upserts to corporate_documents."""
    text = _real_report_text(900_000)
    report = _make_report(text)
    client = MagicMock()
    client.table.return_value.upsert.return_value.execute.return_value = MagicMock()
    metrics = MagicMock()

    # Fake embedding vectors (length = however many chunks are produced)
    from ingestion.nse_bse.pdf_processor import chunk_text as _ct
    chunks = _ct(text, chunk_size=500, overlap=50)
    mock_embed.return_value = [[0.1] * 1536] * len(chunks)

    result = ingest_annual_report("TEST", report, client, metrics)

    assert result == len(chunks)
    assert client.table.call_args[0][0] == "corporate_documents"
    metrics.record_pdf.assert_called_once()
    metrics.record_error.assert_not_called()


@patch("ingestion.official_filings.annual_report_ingester.embed_texts")
def test_ingest_rejects_short_text(mock_embed):
    """Text below MIN_ANNUAL_REPORT_CHARS must be rejected without embedding."""
    report = _make_report("x" * (MIN_ANNUAL_REPORT_CHARS - 1))
    client = MagicMock()
    metrics = MagicMock()

    result = ingest_annual_report("TEST", report, client, metrics)

    assert result == 0
    mock_embed.assert_not_called()
    metrics.record_error.assert_called_once()


@patch("ingestion.official_filings.annual_report_ingester.embed_texts")
def test_ingest_rejects_non_annual_report_text(mock_embed):
    """Text long enough but without annual report keywords must be rejected."""
    # Generic long text — no annual-report-specific keywords
    text = "lorem ipsum dolor sit amet consectetur adipiscing elit " * 2000
    report = _make_report(text)
    client = MagicMock()
    metrics = MagicMock()

    result = ingest_annual_report("TEST", report, client, metrics)

    assert result == 0
    mock_embed.assert_not_called()
    metrics.record_error.assert_called_once()


@patch("ingestion.official_filings.annual_report_ingester.embed_texts")
def test_ingest_sets_section_type_on_rows(mock_embed):
    """Every upserted row must have a non-None section_type."""
    text = _real_report_text(900_000)
    report = _make_report(text)
    client = MagicMock()
    upserted_rows: list[dict] = []

    def _capture_upsert(rows, **kwargs):
        upserted_rows.extend(rows)
        m = MagicMock()
        m.execute.return_value = MagicMock()
        return m

    client.table.return_value.upsert.side_effect = _capture_upsert
    metrics = MagicMock()

    from ingestion.nse_bse.pdf_processor import chunk_text as _ct
    chunks = _ct(text, chunk_size=500, overlap=50)
    mock_embed.return_value = [[0.0] * 1536] * len(chunks)

    ingest_annual_report("TEST", report, client, metrics)

    assert len(upserted_rows) > 0
    assert all(r["section_type"] is not None for r in upserted_rows)
    assert all(r["document_type"] == "annual_report" for r in upserted_rows)
    assert all(r["quarter"] is None for r in upserted_rows)


@patch("ingestion.official_filings.annual_report_ingester.embed_texts")
def test_ingest_idempotent_document_type(mock_embed):
    """Upsert must target corporate_documents, not official_filings or any other table."""
    text = _real_report_text(900_000)
    report = _make_report(text)
    client = MagicMock()
    client.table.return_value.upsert.return_value.execute.return_value = MagicMock()
    metrics = MagicMock()

    from ingestion.nse_bse.pdf_processor import chunk_text as _ct
    chunks = _ct(text, chunk_size=500, overlap=50)
    mock_embed.return_value = [[0.0] * 1536] * len(chunks)

    ingest_annual_report("TEST", report, client, metrics)

    # All table() calls must reference corporate_documents
    for call_args in client.table.call_args_list:
        assert call_args[0][0] == "corporate_documents", (
            f"Expected 'corporate_documents', got '{call_args[0][0]}'"
        )


@patch("ingestion.official_filings.annual_report_ingester.embed_texts",
       side_effect=Exception("OpenAI quota exceeded"))
def test_ingest_handles_embedding_failure(mock_embed):
    """Embedding failure must record error and return 0 without raising."""
    text = _real_report_text(900_000)
    report = _make_report(text)
    client = MagicMock()
    metrics = MagicMock()

    result = ingest_annual_report("TEST", report, client, metrics)

    assert result == 0
    metrics.record_error.assert_called_once()
    client.table.return_value.upsert.assert_not_called()
