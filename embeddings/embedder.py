import os
from typing import List
from openai import OpenAI

MODEL = "text-embedding-3-small"

# text-embedding-3-small allows 8192 tokens. At ~4 chars/token for English,
# 20000 chars ≈ 5000 tokens — conservative ceiling; financial tables can
# tokenize denser than prose, so we give extra headroom vs the 8192 limit.
_MAX_CHARS_PER_INPUT = 20_000

# OpenAI allows up to 300K tokens per request. At ~4 chars/token and 100-chunk
# batches, dense financial tables can hit this limit. Cap at 800K chars per
# batch (~200K tokens) to keep well under the limit.
_MAX_CHARS_PER_BATCH = 800_000

_openai_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable is not set."
            )
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def embed_texts(texts: List[str], batch_size: int = 100) -> List[List[float]]:
    client = _get_client()
    safe = [t[:_MAX_CHARS_PER_INPUT] for t in texts]
    vectors = []
    i = 0
    while i < len(safe):
        batch: List[str] = []
        total_chars = 0
        while i < len(safe) and len(batch) < batch_size:
            item = safe[i]
            if batch and total_chars + len(item) > _MAX_CHARS_PER_BATCH:
                break
            batch.append(item)
            total_chars += len(item)
            i += 1
        batch_start = i - len(batch)
        try:
            response = client.embeddings.create(input=batch, model=MODEL)
            vectors.extend([d.embedding for d in response.data])
        except Exception as exc:
            raise RuntimeError(f"OpenAI embedding failed for batch {batch_start}: {exc}") from exc
    return vectors
