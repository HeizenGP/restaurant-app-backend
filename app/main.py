from fastapi import FastAPI

app = FastAPI(
    title="Restaurante API",
    version="1.0.0",
)

@app.get("/")
async def root():
    return {
        "message": "Restaurante API",
        "status": "running"
    }

@app.get("/health")
async def health():
    return {
        "status": "ok"
    }