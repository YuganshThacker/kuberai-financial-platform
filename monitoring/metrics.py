"""
Ingestion cost dashboard and run metrics.

Usage:
    metrics = IngestionMetrics("transcripts")
    # ... ingestion work ...
    metrics.record_pdf(chunks=142, embeddings=142)
    metrics.record_error()
    metrics.finish(client)  # writes to ingestion_runs table

Cost model (as of June 2026):
    text-embedding-3-small: $0.020 / 1M tokens
    Assumed avg tokens per chunk: 80 words × 1.3 tokens/word ≈ 104 tokens
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Optional

from supabase import Client

# text-embedding-3-small pricing: $0.02 per 1M tokens
_EMBEDDING_COST_PER_TOKEN = 0.020 / 1_000_000
# Rough average: 80-word chunk → ~104 tokens
_AVG_TOKENS_PER_CHUNK = 104


@dataclass
class IngestionMetrics:
    run_type: str
    _started_at: float = field(default_factory=time.time, init=False, repr=False)
    symbols_processed: int = 0
    pdfs_processed: int = 0
    chunks_created: int = 0
    embeddings_generated: int = 0
    errors: int = 0

    # Fetch-stage counters (tracked without OpenAI)
    letters_processed: int = 0      # NSE letters attempted
    url_found_text: int = 0         # URL via text parsing
    url_found_pymupdf: int = 0      # URL via PyMuPDF text fallback
    url_found_hyperlink: int = 0    # URL via PDF annotation hyperlink
    url_found_webpage: int = 0      # URL via IR webpage scraping
    pdf_download_ok: int = 0        # Company PDF downloaded successfully
    pdf_download_fail: int = 0      # Company PDF download failed
    webpages_scraped: int = 0       # IR page scraping attempts
    transcripts_recovered: int = 0  # Letters → full transcript successfully recovered

    def record_symbol(self) -> None:
        self.symbols_processed += 1

    def record_pdf(self, chunks: int = 0, embeddings: int = 0) -> None:
        self.pdfs_processed += 1
        self.chunks_created += chunks
        self.embeddings_generated += embeddings

    def record_error(self) -> None:
        self.errors += 1

    def record_fetch(self, method: str, *, recovered: bool = False) -> None:
        """Record how a company URL was found in the fallback chain."""
        self.letters_processed += 1
        if method == "text":
            self.url_found_text += 1
        elif method == "pymupdf":
            self.url_found_pymupdf += 1
        elif method == "hyperlink":
            self.url_found_hyperlink += 1
        elif method == "webpage":
            self.url_found_webpage += 1
        if recovered:
            self.transcripts_recovered += 1

    @property
    def cost_usd_estimate(self) -> float:
        return self.embeddings_generated * _AVG_TOKENS_PER_CHUNK * _EMBEDDING_COST_PER_TOKEN

    @property
    def duration_seconds(self) -> int:
        return int(time.time() - self._started_at)

    def summary(self) -> dict:
        url_total = (
            self.url_found_text + self.url_found_pymupdf
            + self.url_found_hyperlink + self.url_found_webpage
        )
        return {
            "run_type": self.run_type,
            "symbols_processed": self.symbols_processed,
            "pdfs_processed": self.pdfs_processed,
            "chunks_created": self.chunks_created,
            "embeddings_generated": self.embeddings_generated,
            "errors": self.errors,
            "cost_usd_estimate": round(self.cost_usd_estimate, 6),
            "duration_seconds": self.duration_seconds,
            "cost_per_company_usd": (
                round(self.cost_usd_estimate / self.symbols_processed, 6)
                if self.symbols_processed > 0 else 0.0
            ),
            # Fetch-stage breakdown
            "letters_processed": self.letters_processed,
            "url_found_total": url_total,
            "url_found_text": self.url_found_text,
            "url_found_pymupdf": self.url_found_pymupdf,
            "url_found_hyperlink": self.url_found_hyperlink,
            "url_found_webpage": self.url_found_webpage,
            "pdf_download_ok": self.pdf_download_ok,
            "pdf_download_fail": self.pdf_download_fail,
            "webpages_scraped": self.webpages_scraped,
            "transcripts_recovered": self.transcripts_recovered,
        }

    def print_summary(self) -> None:
        s = self.summary()
        print(
            f"[metrics] {s['run_type']} | "
            f"{s['symbols_processed']} stocks | "
            f"{s['pdfs_processed']} PDFs | "
            f"{s['chunks_created']} chunks | "
            f"{s['embeddings_generated']} embeddings | "
            f"${s['cost_usd_estimate']:.4f} (~${s['cost_per_company_usd']:.6f}/co) | "
            f"{s['errors']} errors | "
            f"{s['duration_seconds']}s"
        )
        if self.letters_processed:
            url_total = s["url_found_total"]
            print(
                f"[metrics] fetch-stage | "
                f"{self.letters_processed} letters | "
                f"{url_total} URLs found "
                f"(text={self.url_found_text} pymupdf={self.url_found_pymupdf} "
                f"hyperlink={self.url_found_hyperlink} webpage={self.url_found_webpage}) | "
                f"{self.pdf_download_ok} downloads OK | "
                f"{self.pdf_download_fail} download fail | "
                f"{self.webpages_scraped} pages scraped | "
                f"{self.transcripts_recovered} recovered"
            )

    def finish(self, client: Optional[Client] = None, metadata: Optional[dict] = None) -> dict:
        """Print summary and optionally write to ingestion_runs table."""
        self.print_summary()
        row = {
            "run_type": self.run_type,
            "symbols_processed": self.symbols_processed,
            "pdfs_processed": self.pdfs_processed,
            "chunks_created": self.chunks_created,
            "embeddings_generated": self.embeddings_generated,
            "errors": self.errors,
            "cost_usd_estimate": round(self.cost_usd_estimate, 6),
            "duration_seconds": self.duration_seconds,
            "metadata": json.dumps(metadata or {}),
        }
        if client:
            try:
                client.table("ingestion_runs").insert(row).execute()
            except Exception as exc:
                print(f"[metrics] Failed to write ingestion_runs: {exc}")
        return self.summary()
