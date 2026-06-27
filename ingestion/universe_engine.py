"""
Universe-scale ingestion engine for KuberAI.

Drives ingestion of the 4 research document types — earnings call transcripts,
annual reports, investor presentations, corporate announcements — across any
slice of the NSE universe, with the durability properties needed to crawl
thousands of symbols without losing work or re-doing it:

  • Per-(symbol, doc_type) state in discovery_state (source = 'nse_<doctype>').
    Each pair is tracked independently — processing one never touches another.
  • Resumable by default: a re-run skips pairs already marked 'complete'/'empty'
    and RETRIES pairs marked 'error' (transient NSE/network failures). This makes
    crash-recovery and outage-retry free — just run the same command again.
  • Quality-gated: each doc type's own ingester enforces its gates (min chars,
    keyword score, intimation-letter rejection, etc.); nothing garbage is embedded.
  • Cost/throughput accounting via IngestionMetrics → ingestion_runs.
  • Throttled + cookie-warmed NSE access via nse_session (set upstream).

The per-doc-type ingesters and quality gates are reused verbatim from the
Nifty50 pipeline — this engine only adds universe selection, state, and resume.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Iterable, Optional

from supabase import Client

from ingestion.official_filings.annual_report_discovery import discover_annual_reports
from ingestion.official_filings.annual_report_ingester import ingest_annual_report
from ingestion.official_filings.transcript_ingester import ingest_transcripts
from ingestion.official_filings.presentation_ingester import ingest_presentations
from ingestion.official_filings.announcement_ingester import ingest_announcements
from ingestion.official_filings.quarterly_results_ingester import ingest_quarterly_results
from monitoring.metrics import IngestionMetrics

# The 4 document types the platform serves, plus quarterly results (bonus).
DOC_TYPES = ("transcripts", "annual", "presentations", "announcements", "quarterly")
DEFAULT_DOC_TYPES = ("transcripts", "annual", "presentations", "announcements")

# discovery_state.source value per doc type
_SOURCE = {dt: f"nse_{dt}" for dt in DOC_TYPES}

# Statuses that mean "don't redo on resume". 'error' is intentionally absent so
# transient failures are retried automatically on the next run.
_SKIP_ON_RESUME = ("complete", "empty")


# ── per-(symbol, doc_type) state ─────────────────────────────────────────────

def _load_states(client: Client, symbol: str) -> dict[str, str]:
    """Return {doc_type: status} for a symbol across all doc types."""
    resp = (
        client.table("discovery_state")
        .select("source,status")
        .eq("symbol", symbol)
        .execute()
    )
    src_to_dt = {v: k for k, v in _SOURCE.items()}
    out: dict[str, str] = {}
    for row in resp.data or []:
        dt = src_to_dt.get(row["source"])
        if dt:
            out[dt] = row.get("status") or ""
    return out


def _save_state(client: Client, symbol: str, doc_type: str, status: str,
                error: Optional[str] = None) -> None:
    client.table("discovery_state").upsert({
        "source": _SOURCE[doc_type],
        "symbol": symbol,
        "status": status,
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "error_message": (error or "")[:500],
    }, on_conflict="source,symbol").execute()


# ── single doc-type ingest ───────────────────────────────────────────────────

def _ingest_one(symbol: str, doc_type: str, client: Client,
                metrics: IngestionMetrics, max_years: int) -> int:
    """Run the ingester for one doc type. Returns chunks added. Raises on failure."""
    if doc_type == "transcripts":
        return ingest_transcripts(symbol, client, metrics)
    if doc_type == "presentations":
        return ingest_presentations(symbol, client, metrics)
    if doc_type == "announcements":
        return ingest_announcements(symbol, client, metrics)
    if doc_type == "quarterly":
        return ingest_quarterly_results(symbol, client, metrics)
    if doc_type == "annual":
        total = 0
        reports = discover_annual_reports(symbol, client, max_years=max_years)
        for report in reports:
            total += ingest_annual_report(symbol, report, client, metrics)
        return total
    raise ValueError(f"unknown doc_type: {doc_type}")


# ── engine ───────────────────────────────────────────────────────────────────

def ingest_symbol(symbol: str, doc_types: Iterable[str], client: Client,
                  metrics: IngestionMetrics, *, resume: bool = True,
                  max_years: int = 5, retry_empty: bool = False) -> dict:
    """Ingest the requested doc types for one symbol, with resume + state.

    Returns a per-doc-type result dict: {doc_type: chunks|'skip'|'error'}.
    """
    states = _load_states(client, symbol) if resume else {}
    result: dict[str, object] = {"symbol": symbol}

    for dt in doc_types:
        prev = states.get(dt)
        skip_set = ("complete",) if retry_empty else _SKIP_ON_RESUME
        if resume and prev in skip_set:
            result[dt] = "skip"
            continue
        try:
            n = _ingest_one(symbol, dt, client, metrics, max_years)
            status = "complete" if n > 0 else "empty"
            _save_state(client, symbol, dt, status)
            result[dt] = n
        except Exception as exc:  # noqa: BLE001 — engine must never die on one pair
            metrics.record_error()
            _save_state(client, symbol, dt, "error", error=str(exc))
            result[dt] = "error"
            print(f"  [!] {symbol}/{dt}: {str(exc)[:120]}", flush=True)
    return result


def ingest_universe(symbols: list[str], doc_types: Iterable[str], client: Client,
                    metrics: IngestionMetrics, *, resume: bool = True,
                    max_years: int = 5, retry_empty: bool = False) -> list[dict]:
    """Ingest a list of symbols. Prints per-symbol progress; fully resumable."""
    doc_types = list(doc_types)
    total = len(symbols)
    results = []
    t0 = time.perf_counter()
    for i, symbol in enumerate(symbols, 1):
        st = time.perf_counter()
        res = ingest_symbol(symbol, doc_types, client, metrics,
                            resume=resume, max_years=max_years, retry_empty=retry_empty)
        results.append(res)
        added = sum(v for v in res.values() if isinstance(v, int))
        flags = " ".join(
            f"{dt}={res.get(dt)}" for dt in doc_types
        )
        elapsed = time.perf_counter() - st
        eta = (time.perf_counter() - t0) / i * (total - i)
        print(f"[{i:>4}/{total}] {symbol:<14} +{added:<5} chunks  {flags}"
              f"  ({elapsed:.0f}s, eta {eta/60:.0f}m)", flush=True)
    print(f"\nUniverse run complete — {total} symbols in {(time.perf_counter()-t0)/60:.1f}m", flush=True)
    return results
