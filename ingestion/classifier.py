"""
Document type classifier for NSE/BSE corporate filings.

Maps a filing's subject line and category to a DocumentType.
Rules are data — adding a new document type means adding one entry to _RULES.

Phase 1: only TRANSCRIPT is actively ingested. All other types are classified
as OTHER and skipped (logged to discovery_state for Phase 2 visibility).
"""

from __future__ import annotations

import re
from enum import Enum


class DocumentType(str, Enum):
    TRANSCRIPT           = "transcript"
    INVESTOR_PRESENTATION = "investor_presentation"
    ANNUAL_REPORT        = "annual_report"
    EARNINGS_RELEASE     = "earnings_release"
    CORPORATE_ANNOUNCEMENT = "corporate_announcement"
    OTHER                = "other"


# (pattern, document_type, confidence)
# Evaluated in order; first match wins.
_RULES: list[tuple[re.Pattern, DocumentType, float]] = [
    (
        re.compile(
            r"transcript|conference call|concall|con\.?\s*call|earnings call|analyst call|investor call",
            re.IGNORECASE,
        ),
        DocumentType.TRANSCRIPT,
        0.95,
    ),
    (
        re.compile(
            r"investor presentation|earnings presentation|results presentation|"
            r"analyst presentation|quarterly presentation",
            re.IGNORECASE,
        ),
        DocumentType.INVESTOR_PRESENTATION,
        0.90,
    ),
    (
        re.compile(r"annual report|annual general meeting|agm", re.IGNORECASE),
        DocumentType.ANNUAL_REPORT,
        0.92,
    ),
    (
        re.compile(
            r"financial results|quarterly results|half.?year.?results|"
            r"press release.*result|result.*press release",
            re.IGNORECASE,
        ),
        DocumentType.EARNINGS_RELEASE,
        0.85,
    ),
]


class FilingClassifier:
    """Classify an NSE/BSE filing subject into a DocumentType."""

    def classify(
        self,
        subject: str,
        category: str = "",
    ) -> tuple[DocumentType, float]:
        """
        Returns (DocumentType, confidence).

        Checks subject first, then category. Returns OTHER with confidence 0.5
        if no rule matches — callers should log these for visibility.
        """
        combined = f"{subject} {category}"
        for pattern, doc_type, confidence in _RULES:
            if pattern.search(combined):
                return doc_type, confidence
        return DocumentType.OTHER, 0.50

    def is_transcript(self, subject: str, category: str = "") -> bool:
        doc_type, _ = self.classify(subject, category)
        return doc_type == DocumentType.TRANSCRIPT


# Module-level singleton — avoids re-compiling patterns on every call
classifier = FilingClassifier()
