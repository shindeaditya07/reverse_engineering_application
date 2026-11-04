from fastapi.testclient import TestClient

from services.api.main import app


def test_healthz_does_not_need_a_database() -> None:
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
