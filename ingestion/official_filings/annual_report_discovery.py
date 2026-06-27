"""
Annual report discovery from the NSE corporate announcement feed.

Strategy:
  1. Fetch all announcements for a symbol.
  2. Filter for annual-report-tagged filings.
  3. For each fiscal year (most recent first), attempt to find a document
     with sufficient text (≥ 50,000 chars).
  4. Use download_and_extract_with_fallback so intimation letters that
     point to company IR sites are automatically resolved.
  5. Return one candidate per fiscal year, capped at max_years.

Design notes:
  - NSE sometimes files the AGM Notice (which contains the annual report)
    as one large PDF.  These are perfectly valid; we accept any PDF whose
    extracted text exceeds MIN_ANNUAL_REPORT_CHARS regardless of whether
    the document is formally titled "Annual Report" or "AGM Notice".
  - The is_intimation_letter flag is ignored here (annual-report-sized
    AGM filings often contain the Reg-30 boilerplate that triggers the
    flag, but they ARE the report content we want).
  - One report per fiscal year: if NSE files the same report in parts
    (consolidated + standalone), we take the larger one.
"""

from __future__ import annotations

from supabase import Client

from ingestion.official_filings.nse_fetcher import (
    download_and_extract_with_fallback,
    fetch_announcements,
    get_annual_report_entries,
)

# Smallest real annual report we'll accept (AGM notices alone are < 5 K chars)
MIN_ANNUAL_REPORT_CHARS = 50_000

# How many NSE entries to probe per symbol (annual reports can be deep in the feed)
_MAX_PROBE = 15


def _already_ingested_for_year(client: Client, symbol: str, fiscal_year: str) -> bool:
    resp = (
        client.table("corporate_documents")
        .select("id")
        .eq("symbol", symbol)
        .eq("document_type", "annual_report")
        .eq("fiscal_year", fiscal_year)
        .limit(1)
        .execute()
    )
    return bool(resp.data)


def discover_annual_reports(
    symbol: str,
    client: Client,
    max_years: int = 3,
) -> list[dict]:
    """Return new annual report candidates for *symbol*, up to *max_years* fiscal years.

    Each item in the returned list is a dict ready for ``ingest_annual_report``:
        url          — canonical PDF URL (company IR URL when recovered)
        fiscal_year  — "2026" etc.
        filing_date  — ISO date string "YYYY-MM-DD"
        title        — display title
        text         — pre-fetched extracted text
        text_len     — len(text)
    """
    try:
        announcements = fetch_announcements(symbol)
    except Exception as exc:
        print(f"[ar_discovery] {symbol}: NSE API failed: {exc}")
        return []

    nse_entries = get_annual_report_entries(announcements, max_recent=_MAX_PROBE)
    if not nse_entries:
        print(f"[ar_discovery] {symbol}: no annual report entries in NSE feed")
        return []

    found_by_fy: dict[str, dict] = {}

    for entry in nse_entries:
        fy = entry["fiscal_year"]
        if not fy:
            continue
        if fy in found_by_fy:
            # Already have a candidate for this year; try to beat it with a larger one
            if found_by_fy[fy]["text_len"] >= 500_000:
                continue  # large enough, stop probing this FY
        if _already_ingested_for_year(client, symbol, fy):
            print(f"[ar_discovery] {symbol} FY{fy}: already ingested")
            continue

        result = download_and_extract_with_fallback(
            entry["url"], filing_date=entry["filing_date"]
        )
        text = result.text
        if not text:
            continue

        if len(text) < MIN_ANNUAL_REPORT_CHARS:
            print(
                f"[ar_discovery] {symbol} FY{fy}: {len(text):,} chars — too short; "
                f"descr='{entry['description'][:50]}'"
            )
            continue

        candidate = {
            "url": result.url,
            "fiscal_year": fy,
            "filing_date": entry["filing_date"],
            "title": f"{symbol} Annual Report FY{fy}",
            "text": text,
            "text_len": len(text),
        }

        if fy not in found_by_fy or len(text) > found_by_fy[fy]["text_len"]:
            found_by_fy[fy] = candidate
            print(
                f"[ar_discovery] {symbol} FY{fy}: {len(text):,} chars via "
                f"{result.url[:70]}"
            )

    results = sorted(found_by_fy.values(), key=lambda x: x["fiscal_year"], reverse=True)
    return results[:max_years]
