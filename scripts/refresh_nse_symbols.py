#!/usr/bin/env python3
"""
Downloads the latest NSE equity list and regenerates config/nse_all_stocks.py.
Run monthly (or when new listings happen):
  python3 scripts/refresh_nse_symbols.py
"""
import csv
import io
import os
import sys
import httpx

NSE_CSV_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "config", "nse_all_stocks.py")

def fetch_symbols() -> dict[str, str]:
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    resp = httpx.get(NSE_CSV_URL, headers=headers, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    return {
        row["SYMBOL"].strip(): row["NAME OF COMPANY"].strip()
        for row in reader
        if row.get(" SERIES", "").strip() == "EQ"
    }

def write_config(companies: dict[str, str]) -> None:
    from datetime import date
    today = date.today().strftime("%B %Y")
    lines = [
        f"# Auto-generated from NSE EQUITY_L.csv — {len(companies)} EQ-series stocks as of {today}.",
        "# Refresh: python3 scripts/refresh_nse_symbols.py",
        "",
        "NSE_ALL_COMPANIES: dict[str, str] = {",
    ]
    for sym, name in sorted(companies.items()):
        lines.append(f"    {repr(sym)}: {repr(name)},")
    lines += [
        "}",
        "",
        "NSE_ALL_SYMBOLS: list[str] = list(NSE_ALL_COMPANIES.keys())",
    ]
    with open(OUTPUT_PATH, "w") as f:
        f.write("\n".join(lines))

def main():
    print("Downloading NSE equity list...")
    companies = fetch_symbols()
    print(f"Found {len(companies)} EQ symbols")
    write_config(companies)
    print(f"Written to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
