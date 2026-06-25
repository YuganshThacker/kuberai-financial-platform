"""
Official Filings Lambda handler.

Triggered weekly (Sunday 01:00 IST) — separate Lambda from web_search because
filings are published quarterly and don't need 30-minute polling.

Modes (set via event["mode"]):
  "transcripts"    — earnings call transcripts (last 8 per stock) + insights extraction
  "presentations"  — investor presentations (last 6 per stock)
  "quarterly"      — quarterly financial result PDFs (last 8 per stock)
  "annual"         — annual reports via NSE announcements (last 5 per stock)
  "announcements"  — NSE corporate announcement text (last 50 per stock, no PDF needed)
  "all"            — all of the above (default)

Default stock universe: NSE 500 (~200 stocks in config; run scripts/fetch_nse500.py
for full 500). Override via event["symbols"] for targeted re-ingestion.

Cost estimate for full NSE 500 × all modes:
  Transcripts:    500 × 8 × ~140 chunks × $0.02/1M tokens ≈ $0.12
  Presentations:  500 × 4 × ~100 chunks             ≈ $0.04
  Quarterly:      500 × 8 × ~80 chunks               ≈ $0.07
  Insight LLM:    500 × 8 × 1500 tokens × $0.60/1M  ≈ $3.60
  Total per full run: ~$4/week
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from config.nifty50 import NIFTY50_SYMBOLS   # Phase 1: Nifty 50 only
from db.client import get_client
from monitoring.metrics import IngestionMetrics
from ingestion.official_filings.transcript_ingester import ingest_transcripts
from ingestion.official_filings.presentation_ingester import ingest_presentations
from ingestion.official_filings.quarterly_results_ingester import ingest_quarterly_results
from ingestion.official_filings.annual_report_discovery import discover_annual_reports
from ingestion.official_filings.annual_report_ingester import ingest_annual_report
from ingestion.official_filings.announcement_ingester import ingest_announcements

MAX_WORKERS = 1   # serial upserts — avoids [Errno 35] socket contention on Supabase


def _process_symbol(symbol: str, mode: str, client, metrics: IngestionMetrics) -> dict:
    result = {"symbol": symbol, "transcripts": 0, "presentations": 0, "quarterly": 0, "annual": 0, "announcements": 0}

    if mode in ("transcripts", "all"):
        result["transcripts"] = ingest_transcripts(symbol, client, metrics)

    if mode in ("presentations", "all"):
        result["presentations"] = ingest_presentations(symbol, client, metrics)

    if mode in ("quarterly", "all"):
        result["quarterly"] = ingest_quarterly_results(symbol, client, metrics)

    if mode in ("annual", "all"):
        try:
            reports = discover_annual_reports(symbol, client, max_years=3)
            for report in reports:
                result["annual"] += ingest_annual_report(symbol, report, client, metrics)
        except Exception as exc:
            print(f"[handler] {symbol} annual report discovery failed: {exc}")
            metrics.record_error()

    if mode in ("announcements", "all"):
        result["announcements"] = ingest_announcements(symbol, client, metrics)

    metrics.record_symbol()
    return result


def lambda_handler(event: dict, context) -> dict:
    """Official filings ingester — Phase 1: transcripts for Nifty 50.

    Default mode="transcripts", symbols=NIFTY50_SYMBOLS.
    Pass event["symbols"] to target specific stocks.
    Pass event["mode"] in ("transcripts","presentations","quarterly","annual","all").
    """
    symbols = event.get("symbols", NIFTY50_SYMBOLS)
    mode = event.get("mode", "transcripts")   # Phase 1: transcripts only
    client = get_client()
    metrics = IngestionMetrics(run_type=f"official_filings_{mode}")

    print(f"[official_filings] Starting {mode} run for {len(symbols)} stocks")

    per_symbol_results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_process_symbol, sym, mode, client, metrics): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            sym = futures[future]
            try:
                per_symbol_results.append(future.result())
            except Exception as exc:
                print(f"[official_filings] {sym}: {exc}")
                metrics.record_error()

    summary = metrics.finish(client=client, metadata={"mode": mode, "symbols_count": len(symbols)})
    summary["statusCode"] = 200
    print(json.dumps(summary))
    return summary
