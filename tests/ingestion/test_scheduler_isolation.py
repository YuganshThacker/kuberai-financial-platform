"""
Isolation tests for the per-symbol scheduler high-water mark.

Guarantees verified:
  1. Processing ITC cannot advance WIPRO's mark.
  2. Processing WIPRO cannot advance TECHM's mark.
  3. A failed ingestion for symbol A does not advance symbol B's mark.
  4. A new symbol with no per-symbol row inherits the global fallback date,
     NOT the mark of whatever symbol ran most recently.
  5. After a multi-symbol run, each symbol has its own independent mark.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, call, patch

import pytest

from ingestion.scheduler import (
    _GLOBAL_SYMBOL,
    _NSE_SOURCE,
    _load_symbol_mark,
    _update_symbol_mark,
    run,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_client(rows_by_symbol: dict[str, str]) -> MagicMock:
    """Build a mock Supabase client whose discovery_state returns per-symbol rows.

    rows_by_symbol maps symbol → last_filing_date string.
    Use '' as the key for the global fallback row.
    """
    client = MagicMock()

    def _select_execute(source, symbol):
        row = rows_by_symbol.get(symbol)
        resp = MagicMock()
        resp.data = [{"last_filing_date": row}] if row else []
        return resp

    def _table_chain(table_name):
        tbl = MagicMock()
        select = MagicMock()
        tbl.select.return_value = select
        select.eq.return_value = select
        select.limit.return_value = select
        select.in_.return_value = select
        # Capture which symbol was requested on the second .eq() call
        eq_calls: list = []

        def _eq(col, val):
            eq_calls.append((col, val))
            sub = MagicMock()
            sub.eq = _eq
            sub.limit = lambda n: sub
            sub.in_ = lambda c, v: sub

            def _exec():
                # The second eq call is the symbol filter
                symbol_val = next(
                    (v for c, v in eq_calls if c == "symbol"), None
                )
                return _select_execute(source=_NSE_SOURCE, symbol=symbol_val or "")

            sub.execute = _exec
            return sub

        select.eq = _eq
        return tbl

    client.table.side_effect = lambda name: _table_chain(name)
    return client


def _filing(an_dt: str, subject: str = "Transcript of Earnings Call", url: str = "https://nsearchives.nseindia.com/test.pdf") -> dict:
    return {"an_dt": an_dt, "desc": subject, "attchmntFile": url, "smIndustry": ""}


# ── Unit: _load_symbol_mark ───────────────────────────────────────────────────

class TestLoadSymbolMark:
    def test_returns_per_symbol_row_when_present(self):
        client = _make_client({"WIPRO": "2026-04-17", "": "2024-01-01"})
        mark = _load_symbol_mark(client, "WIPRO")
        assert mark == "2026-04-17"

    def test_falls_back_to_global_when_no_per_symbol_row(self):
        client = _make_client({"": "2024-01-01"})
        mark = _load_symbol_mark(client, "TRENT")
        assert mark == "2024-01-01"

    def test_global_fallback_is_not_contaminated_by_other_symbol(self):
        # ITC was processed and advanced to 2026-06-12.
        # WIPRO has no per-symbol row.
        # WIPRO must get the GLOBAL row (2024-01-01), NOT ITC's mark.
        client = _make_client({"ITC": "2026-06-12", "": "2024-01-01"})
        wipro_mark = _load_symbol_mark(client, "WIPRO")
        assert wipro_mark == "2024-01-01", (
            "WIPRO should inherit the global fallback, not ITC's mark"
        )

    def test_default_lookback_when_no_rows_exist(self):
        client = _make_client({})
        mark = _load_symbol_mark(client, "NEWSTOCK")
        expected = (date.today() - timedelta(days=30)).isoformat()
        assert mark == expected


# ── Unit: _update_symbol_mark ─────────────────────────────────────────────────

class TestUpdateSymbolMark:
    def test_upsert_targets_correct_symbol(self):
        client = MagicMock()
        upsert_mock = MagicMock()
        client.table.return_value.upsert.return_value = upsert_mock
        upsert_mock.execute.return_value = MagicMock()

        _update_symbol_mark(client, "WIPRO", "2026-04-17")

        upsert_call = client.table.return_value.upsert.call_args
        data = upsert_call[0][0]
        assert data["symbol"] == "WIPRO"
        assert data["source"] == _NSE_SOURCE
        assert data["last_filing_date"] == "2026-04-17"

    def test_wipro_update_does_not_touch_techm(self):
        client = MagicMock()
        upsert_mock = MagicMock()
        client.table.return_value.upsert.return_value = upsert_mock
        upsert_mock.execute.return_value = MagicMock()

        _update_symbol_mark(client, "WIPRO", "2026-04-17")

        # Only one upsert call, and it's for WIPRO
        assert client.table.return_value.upsert.call_count == 1
        data = client.table.return_value.upsert.call_args[0][0]
        assert data["symbol"] == "WIPRO"
        assert data["symbol"] != "TECHM"

    def test_on_conflict_uses_source_and_symbol(self):
        client = MagicMock()
        upsert_mock = MagicMock()
        client.table.return_value.upsert.return_value = upsert_mock
        upsert_mock.execute.return_value = MagicMock()

        _update_symbol_mark(client, "TITAN", "2026-05-14")

        kwargs = client.table.return_value.upsert.call_args[1]
        assert kwargs.get("on_conflict") == "source,symbol"


# ── Integration: run() isolation ─────────────────────────────────────────────

_WIPRO_FILING_DATE = "2026-04-17"
_ITC_FILING_DATE = "2026-06-12"
_TECHM_FILING_DATE = "2026-04-28"


@patch("ingestion.scheduler._refresh_coverage")
@patch("ingestion.scheduler.ingest_transcripts", return_value=1)
@patch("ingestion.scheduler._update_symbol_mark")
@patch("ingestion.scheduler._known_pdf_urls", return_value=set())
@patch("ingestion.scheduler.get_new_filings_since")
@patch("ingestion.scheduler._load_symbol_mark")
@patch("ingestion.scheduler._get_client")
def test_itc_processing_cannot_affect_wipro_mark(
    mock_get_client, mock_load_mark, mock_get_filings,
    mock_known, mock_update, mock_ingest, mock_refresh
):
    """Processing ITC must never advance WIPRO's high-water mark."""
    mock_get_client.return_value = MagicMock()

    # ITC: 1 transcript filing on Jun-12; WIPRO: 1 transcript filing on Apr-17
    def _filings(symbol, from_date):
        if symbol == "ITC":
            return [_filing(f"12-Jun-2026 10:00:00", url="https://nsearchives.nseindia.com/itc.pdf")]
        if symbol == "WIPRO":
            return [_filing(f"17-Apr-2026 10:00:00", url="https://nsearchives.nseindia.com/wipro.pdf")]
        return []

    def _mark(client, symbol):
        return "2025-06-01"  # both symbols start from same date

    mock_get_filings.side_effect = _filings
    mock_load_mark.side_effect = _mark

    run(["ITC", "WIPRO"], dry_run=False, max_recent=1)

    # Verify _update_symbol_mark was called separately for each symbol
    update_calls = mock_update.call_args_list
    symbols_updated = [c[0][1] for c in update_calls]  # positional arg index 1 = symbol
    dates_updated = {c[0][1]: c[0][2] for c in update_calls}

    assert "ITC" in symbols_updated, "ITC mark must be updated"
    assert "WIPRO" in symbols_updated, "WIPRO mark must be updated"

    # Each symbol gets its OWN date
    assert dates_updated["ITC"] == "2026-06-12", f"ITC got {dates_updated['ITC']}"
    assert dates_updated["WIPRO"] == "2026-04-17", f"WIPRO got {dates_updated['WIPRO']}"

    # WIPRO must NOT have gotten ITC's date
    assert dates_updated["WIPRO"] != "2026-06-12", (
        "ITC's filing date must not contaminate WIPRO's mark"
    )


@patch("ingestion.scheduler._refresh_coverage")
@patch("ingestion.scheduler.ingest_transcripts", return_value=1)
@patch("ingestion.scheduler._update_symbol_mark")
@patch("ingestion.scheduler._known_pdf_urls", return_value=set())
@patch("ingestion.scheduler.get_new_filings_since")
@patch("ingestion.scheduler._load_symbol_mark")
@patch("ingestion.scheduler._get_client")
def test_wipro_processing_cannot_affect_techm_mark(
    mock_get_client, mock_load_mark, mock_get_filings,
    mock_known, mock_update, mock_ingest, mock_refresh
):
    """Processing WIPRO must never advance TECHM's high-water mark."""
    mock_get_client.return_value = MagicMock()

    def _filings(symbol, from_date):
        if symbol == "WIPRO":
            return [_filing("17-Apr-2026 10:00:00", url="https://nsearchives.nseindia.com/wipro.pdf")]
        if symbol == "TECHM":
            return [_filing("28-Apr-2026 10:00:00", url="https://nsearchives.nseindia.com/techm.pdf")]
        return []

    mock_get_filings.side_effect = _filings
    mock_load_mark.return_value = "2025-06-01"

    run(["WIPRO", "TECHM"], dry_run=False, max_recent=1)

    dates_updated = {c[0][1]: c[0][2] for c in mock_update.call_args_list}

    assert dates_updated.get("WIPRO") == "2026-04-17"
    assert dates_updated.get("TECHM") == "2026-04-28"
    assert dates_updated.get("TECHM") != "2026-04-17", (
        "WIPRO's filing date must not contaminate TECHM's mark"
    )


@patch("ingestion.scheduler._refresh_coverage")
@patch("ingestion.scheduler._update_symbol_mark")
@patch("ingestion.scheduler._known_pdf_urls", return_value=set())
@patch("ingestion.scheduler.get_new_filings_since")
@patch("ingestion.scheduler._load_symbol_mark")
@patch("ingestion.scheduler._get_client")
def test_failed_ingestion_does_not_advance_other_symbol_mark(
    mock_get_client, mock_load_mark, mock_get_filings,
    mock_known, mock_update, mock_refresh
):
    """Symbol A ingestion failure must not corrupt symbol B's mark."""
    mock_get_client.return_value = MagicMock()

    def _filings(symbol, from_date):
        if symbol == "ITC":
            return [_filing("12-Jun-2026 10:00:00", url="https://nsearchives.nseindia.com/itc.pdf")]
        if symbol == "WIPRO":
            return [_filing("17-Apr-2026 10:00:00", url="https://nsearchives.nseindia.com/wipro.pdf")]
        return []

    mock_get_filings.side_effect = _filings
    mock_load_mark.return_value = "2025-06-01"

    # ITC ingestion throws; WIPRO ingestion succeeds
    def _ingest(symbol, client, metrics, max_recent):
        if symbol == "ITC":
            metrics.record_error()
            raise RuntimeError("embedding quota exceeded")
        return 1

    with patch("ingestion.scheduler.ingest_transcripts", side_effect=_ingest):
        run(["ITC", "WIPRO"], dry_run=False, max_recent=1)

    dates_updated = {c[0][1]: c[0][2] for c in mock_update.call_args_list}

    # WIPRO must still get its own correct date despite ITC failure
    assert "WIPRO" in dates_updated, "WIPRO mark must be updated even when ITC failed"
    assert dates_updated["WIPRO"] == "2026-04-17"

    # ITC's mark MAY be updated (to its newest filing date with status=partial)
    # but crucially it must not have WIPRO's date
    if "ITC" in dates_updated:
        assert dates_updated["ITC"] != "2026-04-17", (
            "ITC must not get WIPRO's filing date"
        )


@patch("ingestion.scheduler._refresh_coverage")
@patch("ingestion.scheduler.ingest_transcripts", return_value=0)
@patch("ingestion.scheduler._update_symbol_mark")
@patch("ingestion.scheduler._known_pdf_urls", return_value=set())
@patch("ingestion.scheduler.get_new_filings_since")
@patch("ingestion.scheduler._get_client")
def test_new_symbol_inherits_global_fallback_not_prior_symbol_mark(
    mock_get_client, mock_get_filings, mock_known,
    mock_update, mock_ingest, mock_refresh
):
    """A new symbol with no row must use the global fallback, not any other symbol's mark."""
    mock_get_client.return_value = MagicMock()
    mock_get_filings.return_value = []

    # Simulate: ITC was processed and its mark is 2026-06-12.
    # TRENT is new — no per-symbol row, global fallback is 2024-01-01.
    def _load(client, symbol):
        if symbol == "TRENT":
            return _load_symbol_mark.__wrapped__(client, symbol) if hasattr(_load_symbol_mark, '__wrapped__') else "2024-01-01"
        return "2026-06-12"  # ITC's mark

    with patch("ingestion.scheduler._load_symbol_mark") as mock_load:
        mock_load.side_effect = lambda client, sym: (
            "2024-01-01" if sym == "TRENT" else "2026-06-12"
        )
        run(["TRENT"], dry_run=False)

    # Verify _load_symbol_mark was called with TRENT
    mock_load.assert_called_with(mock_get_client.return_value, "TRENT")

    # get_new_filings_since must have been called with TRENT's OWN date (2024-01-01)
    mock_get_filings.assert_called_with("TRENT", "2024-01-01")


@patch("ingestion.scheduler._refresh_coverage")
@patch("ingestion.scheduler.ingest_transcripts", return_value=1)
@patch("ingestion.scheduler._update_symbol_mark")
@patch("ingestion.scheduler._known_pdf_urls", return_value=set())
@patch("ingestion.scheduler.get_new_filings_since")
@patch("ingestion.scheduler._load_symbol_mark")
@patch("ingestion.scheduler._get_client")
def test_all_symbols_get_independent_marks_after_multi_run(
    mock_get_client, mock_load_mark, mock_get_filings,
    mock_known, mock_update, mock_ingest, mock_refresh
):
    """After running 4 symbols, each must have its own independent mark."""
    mock_get_client.return_value = MagicMock()

    filing_dates = {
        "WIPRO":      "2026-04-17",
        "TECHM":      "2026-04-28",
        "TITAN":      "2026-05-14",
        "ULTRACEMCO": "2026-05-01",
    }

    def _filings(symbol, from_date):
        dt = filing_dates.get(symbol)
        if not dt:
            return []
        day, mon, year = dt.split("-")[2], _month_abbr(dt.split("-")[1]), dt.split("-")[0]
        return [_filing(
            f"{int(dt.split('-')[2]):02d}-{_month_abbr(dt.split('-')[1])}-{dt.split('-')[0]} 10:00:00",
            url=f"https://nsearchives.nseindia.com/{symbol.lower()}.pdf",
        )]

    mock_get_filings.side_effect = _filings
    mock_load_mark.return_value = "2024-01-01"

    run(list(filing_dates.keys()), dry_run=False, max_recent=1)

    dates_updated = {c[0][1]: c[0][2] for c in mock_update.call_args_list}

    for symbol, expected_date in filing_dates.items():
        assert symbol in dates_updated, f"{symbol} mark was never updated"
        assert dates_updated[symbol] == expected_date, (
            f"{symbol}: expected mark={expected_date}, got {dates_updated[symbol]}"
        )

    # No symbol has another symbol's date
    for sym_a, date_a in dates_updated.items():
        for sym_b, date_b in filing_dates.items():
            if sym_a != sym_b:
                assert dates_updated[sym_a] != filing_dates[sym_b] or filing_dates[sym_a] == filing_dates[sym_b], (
                    f"{sym_a}'s mark equals {sym_b}'s date — possible contamination"
                )


# ── Task 1: Mark advancement safety ──────────────────────────────────────────

@patch("ingestion.scheduler._refresh_coverage")
@patch("ingestion.scheduler._update_symbol_mark")
@patch("ingestion.scheduler._known_pdf_urls", return_value=set())
@patch("ingestion.scheduler.get_new_filings_since")
@patch("ingestion.scheduler._load_symbol_mark")
@patch("ingestion.scheduler._get_client")
def test_mark_not_advanced_when_ingestion_has_errors(
    mock_get_client, mock_load_mark, mock_get_filings,
    mock_known, mock_update, mock_refresh,
):
    """Mark must NOT advance when ingest_transcripts records any error.

    Failure scenario: PDF download fails (transient). The mark must stay at
    from_date so the transcript is retried on the next scheduler run.
    """
    mock_get_client.return_value = MagicMock()
    mock_load_mark.return_value = "2025-01-01"
    mock_get_filings.return_value = [
        _filing("14-Apr-2026 10:00:00", url="https://nsearchives.nseindia.com/reliance.pdf")
    ]

    def _failing_ingest(symbol, client, metrics, max_recent):
        metrics.record_error()  # simulate PDF download failure
        return 0

    with patch("ingestion.scheduler.ingest_transcripts", side_effect=_failing_ingest):
        run(["RELIANCE"], dry_run=False, max_recent=1)

    # _update_symbol_mark must NOT have been called for RELIANCE
    for call_args in mock_update.call_args_list:
        called_symbol = call_args[0][1]
        assert called_symbol != "RELIANCE", (
            f"Mark must not advance for RELIANCE when ingestion had errors; "
            f"got _update_symbol_mark called with symbol={called_symbol}"
        )


@patch("ingestion.scheduler._refresh_coverage")
@patch("ingestion.scheduler._update_symbol_mark")
@patch("ingestion.scheduler._known_pdf_urls", return_value=set())
@patch("ingestion.scheduler.get_new_filings_since")
@patch("ingestion.scheduler._load_symbol_mark")
@patch("ingestion.scheduler._get_client")
def test_mark_advanced_when_ingestion_clean(
    mock_get_client, mock_load_mark, mock_get_filings,
    mock_known, mock_update, mock_refresh,
):
    """Mark advances normally when ingest_transcripts records zero errors."""
    mock_get_client.return_value = MagicMock()
    mock_load_mark.return_value = "2025-01-01"
    mock_get_filings.return_value = [
        _filing("14-Apr-2026 10:00:00", url="https://nsearchives.nseindia.com/reliance.pdf")
    ]

    with patch("ingestion.scheduler.ingest_transcripts", return_value=1):
        run(["RELIANCE"], dry_run=False, max_recent=1)

    update_symbols = [c[0][1] for c in mock_update.call_args_list]
    assert "RELIANCE" in update_symbols, "Mark must advance after clean ingestion"
    update_date = next(c[0][2] for c in mock_update.call_args_list if c[0][1] == "RELIANCE")
    assert update_date == "2026-04-14", f"Expected 2026-04-14, got {update_date}"


@patch("ingestion.scheduler._refresh_coverage")
@patch("ingestion.scheduler._update_symbol_mark")
@patch("ingestion.scheduler._known_pdf_urls", return_value=set())
@patch("ingestion.scheduler.get_new_filings_since")
@patch("ingestion.scheduler._load_symbol_mark")
@patch("ingestion.scheduler._get_client")
def test_partial_batch_error_holds_failing_symbol_not_clean_symbol(
    mock_get_client, mock_load_mark, mock_get_filings,
    mock_known, mock_update, mock_refresh,
):
    """Error in symbol A holds A's mark. Symbol B (clean) still advances normally."""
    mock_get_client.return_value = MagicMock()
    mock_load_mark.return_value = "2025-01-01"

    def _filings(symbol, from_date):
        if symbol == "RELIANCE":
            return [_filing("26-Apr-2026 10:00:00",
                            url="https://nsearchives.nseindia.com/reliance.pdf")]
        if symbol == "TCS":
            return [_filing("14-Apr-2026 10:00:00",
                            url="https://nsearchives.nseindia.com/tcs.pdf")]
        return []

    mock_get_filings.side_effect = _filings

    def _ingest(symbol, client, metrics, max_recent):
        if symbol == "RELIANCE":
            metrics.record_error()
            return 0
        return 1  # TCS succeeds

    with patch("ingestion.scheduler.ingest_transcripts", side_effect=_ingest):
        run(["RELIANCE", "TCS"], dry_run=False, max_recent=1)

    updated = {c[0][1]: c[0][2] for c in mock_update.call_args_list}
    assert "RELIANCE" not in updated, "RELIANCE mark must be held on error"
    assert "TCS" in updated, "TCS mark must advance despite RELIANCE failure"
    assert updated["TCS"] == "2026-04-14"


def _month_abbr(mm: str) -> str:
    months = {
        "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
        "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
        "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
    }
    return months.get(mm, mm)
