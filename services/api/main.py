"""API entry point. Starts without the database; /healthz never touches it (AGENTS.md section 4)."""

from fastapi import FastAPI

from services.api.settings import get_settings

app = FastAPI(title="Legacy Reverse-Engineering Platform")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness only: the process is up. No database, no model.

    `version` is the commit baked into the image, so a deploy can prove which build is running.
    """
    return {"status": "ok", "version": get_settings().git_sha}
