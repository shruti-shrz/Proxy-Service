from fastapi import FastAPI


app = FastAPI(title="Backend Service B", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "service-b"}


@app.get("/admin-data")
def admin_data() -> dict:
    return {
        "service": "service-b",
        "message": "Sensitive internal data. Intended for admin role only.",
    }
