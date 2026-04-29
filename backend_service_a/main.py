from fastapi import FastAPI


app = FastAPI(title="Backend Service A", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "service-a"}


@app.get("/data")
def data() -> dict:
    return {
        "service": "service-a",
        "message": "General internal data. Intended for authenticated users.",
    }
