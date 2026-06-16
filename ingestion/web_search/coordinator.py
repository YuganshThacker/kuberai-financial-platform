"""
Coordinator Lambda — splits all NSE symbols into batches and fans out to worker Lambdas.

Architecture:
  EventBridge (daily 07:30 IST + 17:00 IST)
    → coordinator Lambda  (this file, runs in <5 s)
      → N × worker Lambda invocations (async, each handles BATCH_SIZE stocks)

For 2107 stocks with BATCH_SIZE=50: 43 worker invocations, all run in parallel.
Each worker finishes in ~3–5 min. Total wall time ≈ 5 min for all 2107 stocks.
"""

import json
import os
import boto3

from config.nse_all_stocks import NSE_ALL_SYMBOLS

BATCH_SIZE = int(os.environ.get("WEB_SEARCH_BATCH_SIZE", "50"))
WORKER_FUNCTION = os.environ.get("WEB_SEARCH_WORKER_FUNCTION", "kuberai-web-search-worker")

lambda_client = boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "ap-south-1"))


def _batch(lst: list, size: int) -> list[list]:
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def lambda_handler(event: dict, context) -> dict:
    """
    Accepts optional overrides:
      event = {"symbols": [...], "batch_size": 50}
    Defaults to all 2107 NSE EQ symbols.
    """
    symbols = event.get("symbols", NSE_ALL_SYMBOLS)
    batch_size = event.get("batch_size", BATCH_SIZE)
    batches = _batch(symbols, batch_size)

    print(f"[coordinator] {len(symbols)} symbols → {len(batches)} batches of {batch_size}")

    for i, batch in enumerate(batches):
        lambda_client.invoke(
            FunctionName=WORKER_FUNCTION,
            InvocationType="Event",          # async — fire and forget
            Payload=json.dumps({"symbols": batch}),
        )
        if (i + 1) % 10 == 0:
            print(f"[coordinator] dispatched {i + 1}/{len(batches)} batches")

    return {
        "statusCode": 200,
        "total_symbols": len(symbols),
        "batches_dispatched": len(batches),
    }
