import os
import tempfile
from db.client import get_client
from ingestion.youtube.concall_finder import search_concalls
from ingestion.youtube.transcriber import transcribe_video
from ingestion.nse_bse.pdf_processor import chunk_text
from embeddings.embedder import embed_texts
from embeddings.upserter import upsert_transcript_chunks

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

NIFTY_500_SYMBOLS = [
    "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM",
    "RELIANCE", "HDFCBANK", "ICICIBANK", "AXISBANK",
    "BAJFINANCE", "SBIN", "TATASTEEL", "MARUTI",
]

def process_symbol_youtube(symbol: str, client) -> int:
    videos = search_concalls(symbol, api_key=YOUTUBE_API_KEY, max_results=5)
    processed = 0

    for video in videos:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = f"{tmpdir}/{video.video_id}"
            transcript = transcribe_video(video.video_id, audio_path=audio_path)
            if not transcript or len(transcript) < 200:
                continue

            chunks = chunk_text(transcript, chunk_size=400, overlap=40)
            vectors = embed_texts(chunks)
            upsert_transcript_chunks(
                client=client,
                symbol=symbol,
                source_type="youtube",
                title=video.title,
                video_id=video.video_id,
                channel=video.channel,
                published_at=video.published_at,
                fiscal_quarter=None,
                fiscal_year=None,
                chunks=chunks,
                vectors=vectors,
            )
            processed += 1

    return processed


def lambda_handler(event: dict, context) -> dict:
    """Triggered by EventBridge weekly (concalls happen quarterly)."""
    client = get_client()
    symbols = event.get("symbols", NIFTY_500_SYMBOLS)
    total = sum(process_symbol_youtube(s, client) for s in symbols)
    return {"statusCode": 200, "transcripts_ingested": total}
