import os
from typing import List
from openai import OpenAI

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

MODEL = "text-embedding-3-small"

def embed_texts(texts: List[str], batch_size: int = 100) -> List[List[float]]:
    vectors = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = openai_client.embeddings.create(input=batch, model=MODEL)
        vectors.extend([d.embedding for d in response.data])
    return vectors
