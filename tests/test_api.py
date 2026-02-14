from fastapi.testclient import TestClient

from backend_api import app


def test_health_route():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_investigate_route_offline():
    client = TestClient(app)
    response = client.post("/api/investigate", json={"query": "Investigate Illinois providers in ZIP 60612", "offline": True})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "complete"
    assert data["mode"] == "offline"


def test_frontend_root_contains_inputs():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "Surelock Homes" in html
    assert "runBtn" in html

