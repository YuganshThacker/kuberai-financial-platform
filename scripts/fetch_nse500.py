#!/usr/bin/env python3
"""
Fetch the current Nifty 500 constituent list from NSE archives and regenerate
config/nse500.py.

NSE publishes a monthly CSV of index constituents at:
  https://archives.nseindia.com/content/indices/ind_nifty500list.csv

This URL does not require cookies or browser sessions — it's a static file.

Usage:
  python3 scripts/fetch_nse500.py

Run monthly (or whenever NSE reconstitutes the index) to keep the list accurate.
"""

import csv
import io
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx

NSE_CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
OUTPUT_PATH = Path(__file__).parent.parent / "config" / "nse500.py"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com/",
}

FILE_HEADER = '''\
# NSE 500 (Nifty 500) stock list — auto-generated on {date}.
# Source: {url}
# Refresh: python3 scripts/fetch_nse500.py

NSE500_COMPANIES: dict[str, str] = {{
{entries}
}}

NSE500_SYMBOLS: list[str] = list(NSE500_COMPANIES.keys())
'''


def fetch_csv() -> str:
    print(f"Fetching {NSE_CSV_URL} ...")
    r = httpx.get(NSE_CSV_URL, headers=HEADERS, follow_redirects=True, timeout=30)
    r.raise_for_status()
    return r.text


def parse_csv(text: str) -> dict[str, str]:
    reader = csv.DictReader(io.StringIO(text))
    companies: dict[str, str] = {}
    for row in reader:
        symbol = (row.get("Symbol") or row.get("symbol") or "").strip()
        name = (row.get("Company Name") or row.get("company_name") or "").strip()
        if symbol and name:
            # Normalize: remove extra whitespace
            companies[symbol] = re.sub(r"\s+", " ", name)
    return companies


def write_config(companies: dict[str, str]) -> None:
    max_sym_len = max(len(s) for s in companies)
    entries = "\n".join(
        f'    "{sym}":{" " * (max_sym_len - len(sym) + 3)}"{name}",'
        for sym, name in sorted(companies.items())
    )
    content = FILE_HEADER.format(
        date=datetime.now().strftime("%Y-%m-%d"),
        url=NSE_CSV_URL,
        entries=entries,
    )
    OUTPUT_PATH.write_text(content)
    print(f"Wrote {len(companies)} stocks to {OUTPUT_PATH}")


def main() -> None:
    try:
        text = fetch_csv()
    except Exception as exc:
        print(f"ERROR: Could not fetch CSV: {exc}", file=sys.stderr)
        sys.exit(1)

    companies = parse_csv(text)
    if len(companies) < 400:
        print(
            f"WARNING: Only {len(companies)} stocks parsed — CSV format may have changed. "
            "Inspect the raw CSV before overwriting config.",
            file=sys.stderr,
        )
        sys.exit(1)

    write_config(companies)


if __name__ == "__main__":
    main()
