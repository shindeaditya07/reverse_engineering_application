"""FastAPI application. Only liveness exists so far; readiness arrives with the database layer."""

from fastapi import FastAPI

app = FastAPI(title="Strata API", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. Never touches the database (AGENTS.md section 4)."""
    return {"status": "ok"}
