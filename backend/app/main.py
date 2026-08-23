from fastapi import FastAPI

app = FastAPI(title="Vasooli API")

@app.get("/health")
def health():
    return {"status": "ok", "service": "vasooli backend"}