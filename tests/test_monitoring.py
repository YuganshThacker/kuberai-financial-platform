from monitoring.metrics import IngestionMetrics


def test_metrics_initial_state():
    m = IngestionMetrics("transcripts")
    assert m.pdfs_processed == 0
    assert m.chunks_created == 0
    assert m.errors == 0
    assert m.symbols_processed == 0


def test_metrics_record_pdf():
    m = IngestionMetrics("transcripts")
    m.record_pdf(chunks=142, embeddings=142)
    assert m.pdfs_processed == 1
    assert m.chunks_created == 142
    assert m.embeddings_generated == 142


def test_metrics_cost_estimate():
    m = IngestionMetrics("transcripts")
    m.record_pdf(chunks=0, embeddings=1000)
    # 1000 embeddings × 104 tokens × $0.02/1M
    assert m.cost_usd_estimate > 0
    assert m.cost_usd_estimate < 0.01   # should be ~$0.00208


def test_metrics_summary_keys():
    m = IngestionMetrics("transcripts")
    m.record_symbol()
    m.record_pdf(chunks=10, embeddings=10)
    s = m.summary()
    assert s["run_type"] == "transcripts"
    assert s["symbols_processed"] == 1
    assert "cost_usd_estimate" in s
    assert "cost_per_company_usd" in s
    assert "duration_seconds" in s


def test_metrics_finish_without_client(capsys):
    m = IngestionMetrics("test_run")
    m.record_pdf(chunks=5, embeddings=5)
    result = m.finish(client=None)
    assert result["run_type"] == "test_run"
    captured = capsys.readouterr()
    assert "[metrics]" in captured.out


def test_metrics_finish_with_client_failure():
    from unittest.mock import MagicMock
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.side_effect = Exception("DB error")
    m = IngestionMetrics("test")
    result = m.finish(client=client)   # should not raise
    assert isinstance(result, dict)
