import pytest
from ingestion.official_filings.nse_fetcher import (
    parse_filing_date,
    infer_quarter,
    get_transcript_entries,
    get_presentation_entries,
    get_quarterly_results_entries,
    get_annual_report_entries,
)


# ── parse_filing_date ────────────────────────────────────────────────────────

def test_parse_filing_date_standard():
    assert parse_filing_date("14-Apr-2026 20:02:19") == "2026-04-14"


def test_parse_filing_date_short():
    assert parse_filing_date("01-Jan-2025") == "2025-01-01"


def test_parse_filing_date_bad_input():
    result = parse_filing_date("garbage")
    assert isinstance(result, str)


# ── infer_quarter ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("date,expected_q,expected_fy", [
    ("2026-04-14", "Q4FY26", "2026"),   # April → Q4 of current year
    ("2026-07-20", "Q1FY27", "2027"),   # July → Q1 of next FY
    ("2026-10-15", "Q2FY27", "2027"),   # October → Q2 of next FY
    ("2026-01-25", "Q3FY26", "2026"),   # January → Q3 of current year
    ("2026-06-10", "Q4FY26", "2026"),   # June → Q4 (late Q4 filing)
    ("2026-09-05", "Q1FY27", "2027"),   # September → Q1
    ("2025-12-20", "Q2FY26", "2026"),   # December → Q2
    ("2026-03-10", "Q3FY26", "2026"),   # March → Q3
])
def test_infer_quarter(date, expected_q, expected_fy):
    q, fy = infer_quarter(date)
    assert q == expected_q, f"For {date}: got {q}, expected {expected_q}"
    assert fy == expected_fy


def test_infer_quarter_bad_date():
    q, fy = infer_quarter("not-a-date")
    assert q == ""
    assert fy == ""


# ── Filing filters ───────────────────────────────────────────────────────────

def _make_announcement(**kwargs):
    defaults = {
        "an_dt": "14-Apr-2026 10:00:00",
        "desc": "General",
        "attchmntText": "",
        "attchmntFile": "",
    }
    return {**defaults, **kwargs}


_TRANSCRIPT_ANN = _make_announcement(
    attchmntText="Transcript of Earnings Call Q4FY26",
    attchmntFile="https://nsearchives.nseindia.com/corp/TCS/transcript.pdf",
)

_PRESENTATION_ANN = _make_announcement(
    attchmntText="Investor Presentation Q4FY26",
    attchmntFile="https://nsearchives.nseindia.com/corp/TCS/presentation.pdf",
)

_RESULTS_ANN = _make_announcement(
    desc="Financial Result Updates",
    attchmntText="Quarterly financial results",
    attchmntFile="https://nsearchives.nseindia.com/corp/TCS/results.pdf",
)

_ANNUAL_ANN = _make_announcement(
    attchmntText="Annual Report FY2026",
    attchmntFile="https://nsearchives.nseindia.com/corp/TCS/annual.pdf",
)


def test_get_transcript_entries_filters_correctly():
    entries = get_transcript_entries([_TRANSCRIPT_ANN, _PRESENTATION_ANN, _RESULTS_ANN])
    assert len(entries) == 1
    assert entries[0]["quarter"] == "Q4FY26"
    assert entries[0]["fiscal_year"] == "2026"


def test_get_presentation_entries_filters_correctly():
    entries = get_presentation_entries([_TRANSCRIPT_ANN, _PRESENTATION_ANN, _RESULTS_ANN])
    assert len(entries) == 1
    assert "Investor Presentation" in entries[0]["title"]


def test_get_quarterly_results_entries():
    entries = get_quarterly_results_entries([_TRANSCRIPT_ANN, _PRESENTATION_ANN, _RESULTS_ANN])
    assert len(entries) == 1
    assert entries[0]["quarter"] == "Q4FY26"


def test_get_annual_report_entries():
    entries = get_annual_report_entries([_ANNUAL_ANN, _RESULTS_ANN])
    assert len(entries) == 1
    assert "Annual Report" in entries[0]["title"]


def test_filters_skip_non_nsearchives_urls():
    bad_ann = _make_announcement(
        attchmntText="Transcript of Earnings Call",
        attchmntFile="https://www.example.com/not-nse.pdf",
    )
    entries = get_transcript_entries([bad_ann])
    assert entries == []


def test_max_recent_respected():
    announcements = [_TRANSCRIPT_ANN] * 10
    entries = get_transcript_entries(announcements, max_recent=3)
    assert len(entries) == 3
