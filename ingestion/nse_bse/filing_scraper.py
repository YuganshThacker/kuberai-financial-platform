import httpx
from dataclasses import dataclass
from typing import List, Optional

NSE_BASE = "https://www.nseindia.com"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com",
}

DESCRIPTION_TO_DOC_TYPE = {
    "annual report": "annual_report",
    "quarterly financial results": "quarterly_result",
    "financial results": "quarterly_result",
    "investor presentation": "investor_presentation",
    "concall": "concall_transcript",
    "conference call": "concall_transcript",
}

@dataclass
class FilingRecord:
    symbol: str
    doc_type: str
    title: str
    pdf_url: Optional[str]
    filing_date: Optional[str]

def _infer_doc_type(description: str) -> str:
    desc_lower = description.lower()
    for keyword, doc_type in DESCRIPTION_TO_DOC_TYPE.items():
        if keyword in desc_lower:
            return doc_type
    return "filing"

def fetch_nse_filings(symbol: str) -> List[FilingRecord]:
    url = f"{NSE_BASE}/api/corp-info?symbol={symbol}&type=announcements"
    try:
        with httpx.Client(headers=NSE_HEADERS, timeout=15, follow_redirects=True) as client:
            client.get(NSE_BASE)
            resp = client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError:
        return []

    records = []
    for item in resp.json().get("data", []):
        desc = item.get("description", "")
        pdf_url = item.get("attachments") or None
        records.append(FilingRecord(
            symbol=symbol,
            doc_type=_infer_doc_type(desc),
            title=desc,
            pdf_url=pdf_url,
            filing_date=item.get("filingDate"),
        ))
    return records


def download_pdf(url: str) -> bytes:
    with httpx.Client(headers=NSE_HEADERS, timeout=60, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content
