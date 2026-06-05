import os
import json
import boto3
from db.client import get_client
from ingestion.nse_bse.filing_scraper import fetch_nse_filings, download_pdf, FilingRecord
from ingestion.nse_bse.pdf_processor import extract_text_from_pdf, chunk_text
from embeddings.embedder import embed_texts
from embeddings.upserter import upsert_document_chunks

s3 = boto3.client("s3")
BUCKET = os.environ.get("S3_BUCKET", "kuberai-raw-docs")

NIFTY_500_SYMBOLS = [
    "TCS", "INFY", "HDFCBANK", "RELIANCE", "ICICIBANK",
    "WIPRO", "HCLTECH", "LTI", "TECHM", "AXISBANK",
    "BAJFINANCE", "SBIN", "TATASTEEL", "MARUTI", "NESTLEIND",
    "HCLTECH", "POWERGRID", "NTPC", "ONGC", "COALINDIA",
]

def _backup_to_s3(symbol: str, filing: FilingRecord, pdf_bytes: bytes) -> str:
    key = f"filings/{symbol}/{filing.filing_date}_{filing.doc_type}.pdf"
    s3.put_object(Bucket=BUCKET, Key=key, Body=pdf_bytes, ContentType="application/pdf")
    return key

def process_symbol(symbol: str) -> dict:
    client = get_client()
    filings = fetch_nse_filings(symbol)
    processed = 0

    for filing in filings:
        if not filing.pdf_url:
            continue
        try:
            pdf_bytes = download_pdf(filing.pdf_url)
            _backup_to_s3(symbol, filing, pdf_bytes)
            text = extract_text_from_pdf(pdf_bytes)
            if not text.strip():
                continue
            chunks = chunk_text(text)
            vectors = embed_texts(chunks)
            upsert_document_chunks(
                client=client,
                symbol=symbol,
                doc_type=filing.doc_type,
                title=filing.title,
                source_url=filing.pdf_url,
                filing_date=filing.filing_date,
                fiscal_year=None,
                fiscal_quarter=None,
                chunks=chunks,
                vectors=vectors,
            )
            processed += 1
        except Exception as e:
            print(f"[{symbol}] Error processing {filing.pdf_url}: {e}")

    return {"symbol": symbol, "processed": processed}


def lambda_handler(event: dict, context) -> dict:
    symbols = event.get("symbols", NIFTY_500_SYMBOLS)
    results = [process_symbol(s) for s in symbols]
    print(json.dumps(results))
    return {"statusCode": 200, "results": results}
