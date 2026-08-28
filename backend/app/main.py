from fastapi import FastAPI
from app.api.webhooks import router as webhooks_router

app = FastAPI(title="Vasooli API")

app.include_router(webhooks_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "vasooli backend"}