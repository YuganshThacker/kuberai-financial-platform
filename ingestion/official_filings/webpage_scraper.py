"""
IR webpage scraper for companies that link to their investor portal
rather than including a direct PDF URL in the NSE intimation letter.

Fallback chain per page:
  1. Static HTTP fetch → parse href attributes
  2. Playwright (headless Chromium) for JS-rendered pages

Once PDF links are found, we score them:
  - must contain a transcript keyword in the URL or surrounding link text
  - prefer links whose year/quarter matches the target filing_date
  - strip duplicate links and rank by relevance
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,*/*",
}

# Keywords that mark a URL or surrounding text as a transcript link
_TRANSCRIPT_KWDS = (
    "transcript", "concall", "earnings call", "conference call",
    "analyst call", "investor call",
)

# Keywords that disqualify a link (audio recordings, annual reports, etc.)
_EXCLUDE_KWDS = (".mp3", ".mp4", "audio", "recording", "annual report", "annual-report")


# ── Public API ────────────────────────────────────────────────────────────────

def find_transcript_pdf(
    webpage_url: str,
    filing_date: str = "",
) -> Optional[str]:
    """Return the absolute URL of the transcript PDF closest to `filing_date`.

    Tries static fetch first; falls back to Playwright for JS pages.
    Returns None if no matching PDF is found.
    """
    base = _base_url(webpage_url)

    html = _fetch_static(webpage_url)
    result = _best_pdf(html, base, filing_date)
    if result:
        return result

    html = _fetch_playwright(webpage_url)
    result = _best_pdf(html, base, filing_date)
    return result


# ── HTML fetch ────────────────────────────────────────────────────────────────

def _fetch_static(url: str) -> str:
    # SSRF guard: IR-page URLs come from scraped/extracted content — validate host first.
    from ingestion.official_filings.url_guard import safe_get
    try:
        r = safe_get(url, headers=_HEADERS, timeout=20)
        return r.text
    except Exception:
        return ""


def _fetch_playwright(url: str) -> str:
    # SSRF guard: reject non-public targets before the headless browser navigates.
    from ingestion.official_filings.url_guard import is_public_url
    if not is_public_url(url):
        return ""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30_000)
            page.wait_for_timeout(3_000)
            html = page.content()
            browser.close()
            return html
    except Exception:
        return ""


# ── Link extraction and scoring ───────────────────────────────────────────────

def _base_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _is_transcript(text: str) -> bool:
    lower = text.lower()
    if any(k in lower for k in _EXCLUDE_KWDS):
        return False
    return any(k in lower for k in _TRANSCRIPT_KWDS)


def _fiscal_quarter_label(filing_date: str) -> tuple[str, str]:
    """Return (quarter_label, fy_short) e.g. ('Q4', '26') from '2026-05-20'."""
    if not filing_date:
        return "", ""
    try:
        dt = datetime.strptime(filing_date, "%Y-%m-%d")
    except ValueError:
        return "", ""
    m, y = dt.month, dt.year
    if m in (1, 2, 3):
        return "Q3", str(y % 100).zfill(2)
    elif m in (4, 5, 6):
        return "Q4", str(y % 100).zfill(2)
    elif m in (7, 8, 9):
        return "Q1", str((y + 1) % 100).zfill(2)
    else:
        return "Q2", str((y + 1) % 100).zfill(2)


def _contains_pdf(href: str) -> bool:
    """True if href points to a PDF — including Liferay paths like /file.pdf/UUID."""
    lower = href.lower()
    return lower.endswith(".pdf") or ".pdf/" in lower


def _score_link(href: str, link_text: str, quarter: str, fy: str) -> int:
    """0 = not a transcript link; higher = better match."""
    combined = (href + " " + link_text).lower()
    if not _is_transcript(combined):
        return 0
    if not _contains_pdf(href):
        return 0
    score = 1
    if quarter and quarter.lower() in combined:
        score += 4
    if fy and f"fy{fy}" in combined.replace("-", "").replace(" ", ""):
        score += 3
    if fy and fy in combined:
        score += 2
    return score


def _best_pdf(html: str, base: str, filing_date: str) -> Optional[str]:
    """Find the highest-scoring transcript PDF link in an HTML page.

    When filing_date is known, the winning link must explicitly contain the
    target quarter label (e.g. 'q3', 'q4') in its href or surrounding text.
    This prevents returning the wrong quarter's transcript from IR pages that
    only surface the latest quarter (e.g. KOTAKBANK always shows Q4FY26).
    """
    if not html:
        return None

    quarter, fy = _fiscal_quarter_label(filing_date)

    # Extract href + surrounding text (link label)
    # Match: <a ... href="...">label</a>
    link_re = re.compile(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    best_score = 0
    best_url: Optional[str] = None
    best_has_quarter = False

    def _pick(href_raw: str, label: str) -> None:
        nonlocal best_score, best_url, best_has_quarter
        href = href_raw if href_raw.startswith("http") else urljoin(base, href_raw)
        score = _score_link(href, label, quarter, fy)
        if score > best_score:
            best_score = score
            best_url = href
            combined = (href + " " + label).lower()
            best_has_quarter = bool(quarter) and quarter.lower() in combined

    for m in link_re.finditer(html):
        _pick(m.group(1), re.sub(r"<[^>]+>", "", m.group(2)))

    # Fallback: bare href scan if the above finds nothing
    if not best_url:
        for href_raw in re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE):
            _pick(href_raw, "")

    if not best_url or best_score == 0:
        return None
    # When we know the target quarter, require an explicit quarter label match
    # to prevent FY-only substring matches from returning wrong-quarter content.
    if quarter and not best_has_quarter:
        return None
    return best_url
