"""
Shared NSE API utilities for all official_filings ingesters.

All official filing PDFs for NSE-listed companies are publicly accessible at
nsearchives.nseindia.com, provided you include the correct Referer header.
SEBI Listing Obligations require companies to submit filings to NSE within 24h
of any board decision, so the corpus is comprehensive and near-real-time.

Some companies (e.g. Adani Group, Axis Bank, BPCL) file a one-page SEBI Reg 30
"intimation letter" to NSE instead of uploading the transcript PDF directly.
The letter contains a URL pointing to the actual PDF on their IR website.
`download_and_extract_with_fallback` detects this pattern and follows the URL.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import NamedTuple, Optional
from urllib.parse import urlparse, parse_qs, unquote, quote

import httpx

from ingestion.nse_bse.pdf_processor import extract_text_from_pdf, extract_text_from_pdf_pymupdf

try:
    import fitz as _fitz
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

_NSE_API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com/",
    "Accept": "application/json",
}

_PDF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com/",
}

# Generic headers for company IR websites (no NSE Referer)
_COMPANY_PDF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
}

# Phrases that appear in SEBI Reg 30 intimation letters (not real transcripts).
# Companies use many variations — keep the list broad so new letter styles are caught.
_INTIMATION_SIGNALS = (
    "please find below",               # ADANIENT/ADANIPORTS: "please find below web link / weblink"
    "find below the link",
    "find below web link",
    "is available on the company",     # APOLLOHOSP: "is available on the Company's website"
    "is available on our website",
    "is available on the website",
    "has been made available",         # AXISBANK: "has been made available on the website"
    "has been uploaded on the website",
    "has been uploaded on the company", # MARUTI: "uploaded on the Company's website at the below link"
    "has been uploaded at the website", # ONGC: "uploaded at the website of the Company"
    "can be accessed on the following", # KOTAKBANK: "can be accessed on the following link"
    "may be accessed at",              # ONGC: "may be accessed at https://..."
    "we give below the link",          # BPCL: "we give below the link of Transcripts"
    "link of transcript",              # generic
    "weblink of transcript",
    "pursuant to regulation 30",       # appears in many SEBI disclosures
    "the link to access",              # APOLLOHOSP: "The link to access the said transcript is:"
)

_ANNOUNCEMENTS_URL = (
    "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={symbol}"
)


# ── Date / quarter helpers ──────────────────────────────────────────────────

def parse_filing_date(an_dt: str) -> str:
    """'14-Apr-2026 20:02:19' → '2026-04-14'."""
    try:
        dt = datetime.strptime(an_dt[:11].strip(), "%d-%b-%Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return an_dt[:10]


def infer_quarter(filing_date: str) -> tuple[str, str]:
    """Return (quarter, fiscal_year) e.g. ('Q4FY26', '2026').

    Indian fiscal year runs April–March. Earnings transcripts are filed ~24-48h
    after the call, which happens 3-6 weeks after quarter end:
      Jan–Mar  → Q3 results  (quarter ends Dec, FY = current year)
      Apr–Jun  → Q4 results  (quarter ends Mar, FY = current year)
      Jul–Sep  → Q1 results  (quarter ends Jun, FY = current year + 1)
      Oct–Dec  → Q2 results  (quarter ends Sep, FY = current year + 1)
    """
    try:
        dt = datetime.strptime(filing_date, "%Y-%m-%d")
    except Exception:
        return ("", "")

    month, year = dt.month, dt.year
    if month in (1, 2, 3):
        quarter, fy = "Q3", year
    elif month in (4, 5, 6):
        quarter, fy = "Q4", year
    elif month in (7, 8, 9):
        quarter, fy = "Q1", year + 1
    else:
        quarter, fy = "Q2", year + 1

    fy_short = fy % 100
    return f"{quarter}FY{fy_short:02d}", str(fy)


# ── NSE API ─────────────────────────────────────────────────────────────────

def fetch_announcements(symbol: str) -> list[dict]:
    """Fetch full corporate announcement list from NSE for a symbol.

    Routed through the warmed, cookie-bearing NSE session (nse_session) so the
    API's bot-detection doesn't block us at scale. Falls back to a bare request
    only if the session import is unavailable (keeps unit tests hermetic).
    """
    # quote() encodes & in symbols like M&M → M%26M so it isn't parsed as a
    # URL parameter separator by the NSE API server.
    url = _ANNOUNCEMENTS_URL.format(symbol=quote(symbol, safe=""))
    try:
        from ingestion.official_filings.nse_session import get_session
        return get_session().get_json(url)
    except ImportError:
        r = httpx.get(url, headers=_NSE_API_HEADERS, follow_redirects=True, timeout=20)
        r.raise_for_status()
        return r.json()


def get_new_filings_since(symbol: str, from_date: str) -> list[dict]:
    """Return raw NSE announcements for *symbol* with filing_date > from_date.

    The NSE API has no server-side date filter, so we fetch all announcements
    and filter client-side. Because the API returns newest-first, we stop early
    once we hit an announcement older than from_date.

    Args:
        symbol:    NSE equity symbol, e.g. "RELIANCE"
        from_date: ISO date string "YYYY-MM-DD" (exclusive lower bound)

    Returns:
        List of raw announcement dicts, newest-first, all with filing_date > from_date.
        Empty list if symbol has no new filings or API call fails.
    """
    try:
        all_announcements = fetch_announcements(symbol)
    except Exception as exc:
        print(f"[nse_fetcher] {symbol}: API error in get_new_filings_since: {exc}")
        return []

    result = []
    for ann in all_announcements:
        filing_date = parse_filing_date(ann.get("an_dt", ""))
        if filing_date <= from_date:
            # Announcements are newest-first; once we pass from_date we're done
            break
        if _is_nsearchives_pdf(ann.get("attchmntFile", "")):
            result.append(ann)
    return result


# ── Filing filters ───────────────────────────────────────────────────────────

def _is_nsearchives_pdf(url: str) -> bool:
    return url.startswith("https://nsearchives") and url.endswith(".pdf")


def get_transcript_entries(announcements: list[dict], max_recent: int = 8) -> list[dict]:
    """Filter announcements for earnings call transcript PDFs."""
    matches = [
        d for d in announcements
        if "Transcript" in d.get("attchmntText", "")
        and _is_nsearchives_pdf(d.get("attchmntFile", ""))
    ]
    result = []
    for d in matches[:max_recent]:
        filing_date = parse_filing_date(d["an_dt"])
        quarter, fiscal_year = infer_quarter(filing_date)
        result.append({
            "url": d["attchmntFile"],
            "title": f"Earnings Call Transcript {quarter}" if quarter else "Earnings Call Transcript",
            "filing_date": filing_date,
            "quarter": quarter,
            "fiscal_year": fiscal_year,
            "description": d.get("attchmntText", ""),
        })
    return result


def get_presentation_entries(announcements: list[dict], max_recent: int = 6) -> list[dict]:
    """Filter for investor/analyst presentation PDFs."""
    _KEYWORDS = ("Investor Presentation", "Analyst Presentation", "Investor Meet",
                 "Capital Markets Day", "Analyst Meet")
    matches = [
        d for d in announcements
        if any(kw in d.get("attchmntText", "") for kw in _KEYWORDS)
        and _is_nsearchives_pdf(d.get("attchmntFile", ""))
    ]
    result = []
    for d in matches[:max_recent]:
        filing_date = parse_filing_date(d["an_dt"])
        quarter, fiscal_year = infer_quarter(filing_date)
        result.append({
            "url": d["attchmntFile"],
            "title": f"Investor Presentation {quarter or filing_date}",
            "filing_date": filing_date,
            "quarter": quarter,
            "fiscal_year": fiscal_year,
            "description": d.get("attchmntText", ""),
        })
    return result


def get_quarterly_results_entries(announcements: list[dict], max_recent: int = 8) -> list[dict]:
    """Filter for quarterly financial result PDFs."""
    matches = [
        d for d in announcements
        if d.get("desc") == "Financial Result Updates"
        and _is_nsearchives_pdf(d.get("attchmntFile", ""))
    ]
    result = []
    for d in matches[:max_recent]:
        filing_date = parse_filing_date(d["an_dt"])
        quarter, fiscal_year = infer_quarter(filing_date)
        result.append({
            "url": d["attchmntFile"],
            "title": f"Quarterly Financial Results {quarter or filing_date}",
            "filing_date": filing_date,
            "quarter": quarter,
            "fiscal_year": fiscal_year,
            "description": d.get("attchmntText", ""),
        })
    return result


def get_annual_report_entries(announcements: list[dict], max_recent: int = 5) -> list[dict]:
    """Filter for annual report PDFs filed via NSE announcements.

    Annual reports are sometimes filed via NSE but more commonly via company IR pages.
    This catches the ones filed through the official announcements channel.
    """
    _KEYWORDS = ("Annual Report", "Annual General Meeting", "Integrated Annual Report")
    matches = [
        d for d in announcements
        if any(kw in d.get("attchmntText", "") for kw in _KEYWORDS)
        and _is_nsearchives_pdf(d.get("attchmntFile", ""))
    ]
    result = []
    for d in matches[:max_recent]:
        filing_date = parse_filing_date(d["an_dt"])
        _, fiscal_year = infer_quarter(filing_date)
        result.append({
            "url": d["attchmntFile"],
            "title": f"Annual Report FY{fiscal_year}",
            "filing_date": filing_date,
            "quarter": None,
            "fiscal_year": fiscal_year,
            "description": d.get("attchmntText", ""),
        })
    return result


# ── Intimation letter detection ──────────────────────────────────────────────

def is_intimation_letter(text: str) -> bool:
    """Return True if text is a SEBI Reg 30 cover letter, not an actual transcript.

    These one-page letters say "transcript available at [company website URL]"
    rather than containing the call recording itself.
    """
    # Normalize whitespace so mid-word line breaks (e.g. "can\nbe accessed") still match
    lower = re.sub(r"\s+", " ", text.lower())
    return any(re.search(signal, lower) for signal in _INTIMATION_SIGNALS)


def extract_company_url(text: str) -> Optional[str]:
    """Extract the company IR website PDF URL from an intimation letter.

    NSE PDFs rendered in columns wrap URLs across lines. Removing newlines
    reconstructs the full URL before applying the regex.

    For digitally-signed PDFs (e.g. Apollo Hospitals), font encoding inserts
    space characters mid-URL. The fallback strips all whitespace from the URL
    candidate and applies known ArialMT encoding fixes.
    """
    # Standard path: collapse newlines only (handles column-wrapped URLs)
    collapsed = text.replace("\n", "")
    match = re.search(r"https?://[^\s\"'<>]+\.pdf", collapsed, re.IGNORECASE)
    if match:
        return match.group(0)

    # Fallback: for digitally-signed PDFs where spaces are injected mid-URL,
    # locate the https:// anchor and collect text until .pdf (or end of URL-like run)
    # then strip ALL whitespace and apply font encoding corrections.
    start = collapsed.lower().find("https://")
    if start == -1:
        return None
    # Grab candidate: https:// onwards, up to 300 chars (generous for long CDN paths)
    candidate = collapsed[start : start + 300]
    # Find .pdf marker (possibly corrupted as .... pdf or . pdf)
    pdf_end = re.search(r"\.{1,4}\s*pdf\b", candidate, re.IGNORECASE)
    if not pdf_end:
        return None
    raw = candidate[: pdf_end.end()]
    # Strip all whitespace
    url = re.sub(r"\s+", "", raw)
    # Fix ArialMT encoding: digit 0 → capital O in CDN subdomains (e.g. .aO1. → .a01.)
    url = re.sub(r"\.([a-zA-Z])[Oo](\d)\.", lambda m: f".{m.group(1)}0{m.group(2)}.", url)
    # Fix: 't/' ligature appears as capital U (e.g. defaulUfiles → default/files)
    url = re.sub(r"([a-z]{5})U([a-z])", lambda m: f"{m.group(1)}t/{m.group(2)}", url)
    # Fix: 'q' in quarter label appears as 'g' (e.g. ---g1-fy → ---q1-fy)
    url = re.sub(r"---g(\d)-fy", r"---q\1-fy", url)
    # Fix: multiple trailing dots before pdf (....pdf → .pdf)
    url = re.sub(r"\.{2,}pdf$", ".pdf", url, flags=re.IGNORECASE)
    # Validate it still looks like a URL
    if re.match(r"https?://\S+\.pdf$", url, re.IGNORECASE):
        return url
    return None


def extract_any_url(text: str) -> Optional[str]:
    """Extract any https URL from letter text (PDF or webpage).

    Used to distinguish 'transcript_on_webpage' (company links to IR page instead
    of direct PDF) from 'text_too_short' (plain cover letter with no URL at all).
    """
    # Search original text — newlines act as natural URL word-boundaries,
    # preventing next-sentence text (e.g. "Kindly") from being concatenated into the URL.
    match = re.search(r"https?://[^\s\"'<>]{10,}", text)
    if match:
        return match.group(0).rstrip(".,;)")
    return None


def _decode_safelinks(url: str) -> str:
    """Unwrap Microsoft SafeLinks to the real destination URL.

    Companies that send their NSE intimation letters via Outlook often have
    URLs wrapped in SafeLinks: https://...safelinks.protection.outlook.com/?url=ENCODED_URL&...
    """
    if "safelinks.protection.outlook.com" in url:
        try:
            qs = parse_qs(urlparse(url).query)
            if "url" in qs:
                return unquote(qs["url"][0])
        except Exception:
            pass
    return url


def extract_pdf_url_from_hyperlinks(pdf_bytes: bytes) -> Optional[str]:
    """Extract a PDF URL from hyperlink annotations embedded in the letter PDF.

    Some companies (e.g. JSW Steel) embed the transcript URL as a clickable
    hyperlink in their intimation letter rather than writing it as visible text.
    PyMuPDF can extract these annotation URIs; SafeLinks wrappers are decoded.
    """
    if not _FITZ_AVAILABLE:
        return None
    try:
        doc = _fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in doc:
            for link in page.get_links():
                uri = link.get("uri", "")
                if not uri:
                    continue
                uri = _decode_safelinks(uri)
                if uri.lower().endswith(".pdf"):
                    return uri
    except Exception:
        pass
    return None


def _download_company_pdf(url: str) -> bytes:
    """Download a transcript PDF from a company IR website. Raises on failure.

    Handles Liferay-style paths (/file.pdf/UUID) where the Content-Type may differ
    but the content is still a valid PDF.
    """
    from ingestion.official_filings.url_guard import safe_get
    # SSRF guard: url is extracted from filing text / scraped HTML, so validate
    # the host (and every redirect hop) before fetching — blocks metadata/private targets.
    r = safe_get(url, headers=_COMPANY_PDF_HEADERS, timeout=45)
    r.raise_for_status()
    if r.content[:4] != b"%PDF":
        raise ValueError(f"Non-PDF response ({len(r.content)} bytes) from {url}")
    return r.content


# ── PDF download + extraction ────────────────────────────────────────────────

def download_pdf(pdf_url: str) -> bytes:
    """Download a PDF from NSEArchives via the warmed NSE session. Raises on failure."""
    try:
        from ingestion.official_filings.nse_session import get_session
        content = get_session().get_bytes(pdf_url)
    except ImportError:
        r = httpx.get(pdf_url, headers=_PDF_HEADERS, follow_redirects=True, timeout=45)
        r.raise_for_status()
        content = r.content
    if content[:4] != b"%PDF":
        raise ValueError(f"Non-PDF response from {pdf_url} ({len(content)} bytes)")
    return content


def download_and_extract(pdf_url: str) -> str:
    """Download PDF and extract text; returns '' on any failure (never raises)."""
    try:
        content = download_pdf(pdf_url)
    except Exception as exc:
        print(f"[nse_fetcher] PDF download failed {pdf_url}: {exc}")
        return ""
    try:
        return extract_text_from_pdf(content)
    except Exception as exc:
        print(f"[nse_fetcher] PDF extraction failed {pdf_url}: {exc}")
        return ""


class FetchResult(NamedTuple):
    """Result from download_and_extract_with_fallback.

    Fields:
        text        — extracted transcript text (may be the short letter text on failure)
        url         — canonical URL (company IR URL when recovery succeeded; NSE URL otherwise)
        is_letter   — True if the NSE file was an intimation letter
        url_method  — how the company PDF URL was found:
                      "text", "pymupdf", "hyperlink", "webpage" — URL found + download OK
                      "text_fail", "pymupdf_fail", "hyperlink_fail", "webpage_fail" — found but 404
                      None — no URL found (letter without any pointer)
        recovered   — True if company PDF text is larger than the letter text
    """
    text: str
    url: str
    is_letter: bool
    url_method: Optional[str]
    recovered: bool


def download_and_extract_with_fallback(
    nse_url: str,
    filing_date: str = "",
) -> FetchResult:
    """Download transcript PDF; follow company IR URL if NSE file is an intimation letter.

    Fallback chain (each step tried only when the previous finds nothing):
      1. Text parsing: collapse newlines, regex for .pdf URL
      2. PyMuPDF text: re-extract using fitz; handles ArialMT font encoding
      3. PDF hyperlink annotation: fitz link objects (JSW Steel SafeLinks pattern)
      4. IR webpage scraping: fetch the company investor relations page, scan for
         transcript PDF links matching the filing_date quarter (KOTAKBANK, MARUTI, ONGC…)

    Args:
        nse_url:     URL of the NSE-hosted PDF
        filing_date: ISO date "YYYY-MM-DD" used to match the right quarter on IR pages

    Returns:
        FetchResult named tuple — see class docstring.
    """
    try:
        nse_bytes = download_pdf(nse_url)
    except Exception as exc:
        print(f"[nse_fetcher] PDF download failed {nse_url}: {exc}")
        return FetchResult("", nse_url, False, None, False)

    nse_text = ""
    try:
        nse_text = extract_text_from_pdf(nse_bytes)
    except Exception as exc:
        print(f"[nse_fetcher] PDF extraction failed {nse_url}: {exc}")

    if not nse_text or not is_intimation_letter(nse_text):
        return FetchResult(nse_text, nse_url, False, None, False)

    company_url: Optional[str] = None
    url_method: Optional[str] = None

    # Step 1 — text parsing (standard: collapse newlines, regex .pdf URL)
    company_url = extract_company_url(nse_text)
    if company_url:
        url_method = "text"

    # Step 2 — PyMuPDF text (digitally-signed PDFs: pdfplumber misses URL)
    if not company_url:
        pymupdf_text = extract_text_from_pdf_pymupdf(nse_bytes)
        if pymupdf_text:
            company_url = extract_company_url(pymupdf_text)
            if company_url:
                url_method = "pymupdf"
                print(f"[nse_fetcher] URL found via PyMuPDF text in {nse_url}")

    # Step 3 — PDF hyperlink annotation (JSW Steel-style SafeLinks)
    if not company_url:
        company_url = extract_pdf_url_from_hyperlinks(nse_bytes)
        if company_url:
            url_method = "hyperlink"
            print(f"[nse_fetcher] URL found via PDF hyperlink annotation in {nse_url}")

    # Step 4 — IR webpage scraping (company links to investor portal, not PDF)
    if not company_url:
        webpage_url = extract_any_url(nse_text)
        if webpage_url and not webpage_url.lower().endswith(".pdf"):
            from ingestion.official_filings.webpage_scraper import find_transcript_pdf
            print(f"[nse_fetcher] Scraping IR page: {webpage_url}")
            scraped_pdf = find_transcript_pdf(webpage_url, filing_date=filing_date)
            if scraped_pdf:
                company_url = scraped_pdf
                url_method = "webpage"
                print(f"[nse_fetcher] IR page yielded PDF: {company_url}")

    if not company_url:
        print(f"[nse_fetcher] Intimation letter but no PDF URL found in {nse_url}")
        return FetchResult(nse_text, nse_url, True, None, False)

    # Download the company PDF
    print(f"[nse_fetcher] Following company URL ({url_method}): {company_url}")
    try:
        content = _download_company_pdf(company_url)
        company_text = extract_text_from_pdf(content)
        if len(company_text) > len(nse_text):
            return FetchResult(company_text, company_url, True, url_method, True)
        print(
            f"[nse_fetcher] Company PDF shorter than letter "
            f"({len(company_text)} vs {len(nse_text)}), keeping NSE text"
        )
        return FetchResult(nse_text, nse_url, True, f"{url_method}_short", False)
    except Exception as exc:
        print(f"[nse_fetcher] Company URL download failed {company_url}: {exc}")
        return FetchResult(nse_text, nse_url, True, f"{url_method}_fail", False)
