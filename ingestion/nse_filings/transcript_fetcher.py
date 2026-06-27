"""
NSE concall transcript ingester.

SEBI Listing Obligations require all listed companies to submit earnings call
transcripts to NSE within 24 hours. They're publicly available at nsearchives.nseindia.com.

This module:
  1. Queries the NSE corporate announcements API
  2. Filters for announcements containing "Transcript"
  3. Downloads the PDF from nsearchives.nseindia.com
  4. Extracts text via pdfplumber
  5. Returns structured transcript data for chunking + embedding

Free alternative to Quartr — covers every NSE-listed company automatically.
"""

import httpx
from dataclasses import dataclass
from typing import Optional

from ingestion.nse_bse.pdf_processor import extract_text_from_pdf

_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com/",
    "Accept": "application/json",
}

_NSEARCHIVES_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com/",
}

NSE_ANNOUNCEMENTS_API = (
    "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={symbol}"
)


@dataclass
class TranscriptResult:
    symbol: str
    url: str
    title: str
    filing_date: str
    text: str
    source_domain: str = "nsearchives.nseindia.com"


def _parse_filing_date(an_dt: str) -> str:
    """Parse NSE date string like '14-Apr-2026 20:02:19' → '2026-04-14'."""
    try:
        from datetime import datetime
        dt = datetime.strptime(an_dt[:11].strip(), "%d-%b-%Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return an_dt[:10]


def fetch_nse_announcements(symbol: str) -> list[dict]:
    """Return full NSE corporate announcements list for a symbol."""
    url = NSE_ANNOUNCEMENTS_API.format(symbol=symbol)
    r = httpx.get(url, headers=_NSE_HEADERS, follow_redirects=True, timeout=20)
    r.raise_for_status()
    return r.json()


def get_transcript_urls(symbol: str, max_recent: int = 5) -> list[dict]:
    """Return the most recent NSE concall transcript PDF entries for a stock.

    Filters announcements where attchmntText contains "Transcript" — these are the
    actual earnings call transcripts that companies must file with NSE within 24h.
    """
    try:
        data = fetch_nse_announcements(symbol)
    except Exception:
        return []

    transcripts = [
        d for d in data
        if "Transcript" in d.get("attchmntText", "")
        and d.get("attchmntFile", "").startswith("https://nsearchives")
    ]

    return [
        {
            "url": t["attchmntFile"],
            "title": f"{symbol} - Earnings Call Transcript ({_parse_filing_date(t['an_dt'])})",
            "filing_date": _parse_filing_date(t["an_dt"]),
            "description": t.get("attchmntText", ""),
        }
        for t in transcripts[:max_recent]
    ]


def get_financial_result_urls(symbol: str, max_recent: int = 8) -> list[dict]:
    """Return recent quarterly financial results PDF entries from NSE filings."""
    try:
        data = fetch_nse_announcements(symbol)
    except Exception:
        return []

    results = [
        d for d in data
        if d.get("desc") == "Financial Result Updates"
        and d.get("attchmntFile", "").startswith("https://nsearchives")
    ]

    return [
        {
            "url": r["attchmntFile"],
            "title": f"{symbol} - Quarterly Financial Results ({_parse_filing_date(r['an_dt'])})",
            "filing_date": _parse_filing_date(r["an_dt"]),
            "description": r.get("attchmntText", ""),
        }
        for r in results[:max_recent]
    ]


def download_and_extract_pdf(pdf_url: str) -> str:
    """Download a PDF from NSEArchives and extract plain text via pdfplumber.

    Returns empty string for network errors, non-PDF responses, encrypted PDFs,
    or any pdfplumber extraction failure — never raises.
    """
    try:
        r = httpx.get(
            pdf_url,
            headers=_NSEARCHIVES_HEADERS,
            follow_redirects=True,
            timeout=30,
        )
        r.raise_for_status()
    except Exception as exc:
        print(f"[transcript_fetcher] PDF download failed {pdf_url}: {exc}")
        return ""

    if r.content[:4] != b"%PDF":
        print(f"[transcript_fetcher] Non-PDF response from {pdf_url} ({len(r.content)} bytes)")
        return ""

    try:
        return extract_text_from_pdf(r.content)
    except Exception as exc:
        print(f"[transcript_fetcher] PDF text extraction failed {pdf_url}: {exc}")
        return ""


def fetch_transcript(symbol: str, entry: dict) -> Optional[TranscriptResult]:
    """Download one NSE transcript PDF and return a TranscriptResult."""
    try:
        text = download_and_extract_pdf(entry["url"])
        if len(text) < 200:
            return None
        return TranscriptResult(
            symbol=symbol,
            url=entry["url"],
            title=entry["title"],
            filing_date=entry["filing_date"],
            text=text,
        )
    except Exception:
        return None


def get_press_release_urls(symbol: str, max_recent: int = 8) -> list[dict]:
    """Return recent NSE Press Release PDF entries — investor presentations, earnings highlights.

    Companies file press releases with NSE covering:
    - Quarterly earnings highlights / investor presentations
    - Strategic announcements
    - Key management updates

    These are often richer than the transcript alone.
    """
    try:
        data = fetch_nse_announcements(symbol)
    except Exception:
        return []

    releases = [
        d for d in data
        if d.get("desc") == "Press Release"
        and d.get("attchmntFile", "").startswith("https://nsearchives")
        and d.get("attchmntFile", "").endswith(".pdf")
    ]

    return [
        {
            "url": r["attchmntFile"],
            "title": f"{symbol} - NSE Press Release ({_parse_filing_date(r['an_dt'])}): {r.get('attchmntText','')[:80]}",
            "filing_date": _parse_filing_date(r["an_dt"]),
            "description": r.get("attchmntText", ""),
        }
        for r in releases[:max_recent]
    ]


def fetch_all_transcripts(symbol: str, max_transcripts: int = 3) -> list[TranscriptResult]:
    """Fetch the most recent earnings call transcripts for a stock.

    Returns up to max_transcripts TranscriptResult objects with full PDF text.
    For Nifty 50 stocks, this typically covers the last 3-4 quarterly earnings calls.
    """
    entries = get_transcript_urls(symbol, max_recent=max_transcripts)
    results = []
    for entry in entries:
        result = fetch_transcript(symbol, entry)
        if result:
            results.append(result)
    return results
