from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.webhooks import router as webhooks_router
from app.api.metrics import router as metrics_router

app = FastAPI(title="Vasooli API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://vasooli-dashboard.vercel.app",
        "https://vasooli-dashboard-6j1io8ovy-akaash-s-projects.vercel.app",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(webhooks_router)
app.include_router(metrics_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "vasooli backend"}