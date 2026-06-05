from fastapi import FastAPI
from api.routes.query import router as query_router
from api.routes.sources import router as sources_router

app = FastAPI(title="KuberAI Financial Intelligence API", version="1.0.0")
app.include_router(query_router)
app.include_router(sources_router)

@app.get("/health")
def health():
    return {"status": "ok"}
