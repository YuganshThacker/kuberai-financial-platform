from unittest.mock import MagicMock
from query.sql_lookup import get_latest_metrics, MetricSnapshot

def test_get_latest_metrics_returns_snapshot():
    mock_client = MagicMock()
    mock_client.table.return_value \
        .select.return_value \
        .eq.return_value \
        .order.return_value \
        .limit.return_value \
        .execute.return_value.data = [{
            "symbol": "TCS",
            "as_of_date": "2026-06-05",
            "price": 3920.5,
            "pe_ratio": 28.5,
            "market_cap_cr": 1425000.0,
            "roe": 47.3,
            "week_52_high": 4200.0,
            "week_52_low": 3100.0,
            "day_high": None,
            "day_low": None,
            "pb_ratio": None,
            "roce": None,
            "debt_to_equity": None,
            "promoter_holding": None,
            "fii_holding": None,
        }]
    result = get_latest_metrics(mock_client, "TCS")
    assert isinstance(result, MetricSnapshot)
    assert result.price == 3920.5
    assert result.pe_ratio == 28.5

def test_get_latest_metrics_returns_none_when_no_data():
    mock_client = MagicMock()
    mock_client.table.return_value \
        .select.return_value \
        .eq.return_value \
        .order.return_value \
        .limit.return_value \
        .execute.return_value.data = []
    result = get_latest_metrics(mock_client, "UNKNOWN")
    assert result is None
