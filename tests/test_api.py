from fastapi.testclient import TestClient
from unittest.mock import patch

from backend_api import app


def test_health_route():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_coverage_route_lists_il_and_mn_counties():
    client = TestClient(app)
    response = client.get("/api/coverage")
    assert response.status_code == 200

    data = response.json()
    assert set(data["provider_states"]) == {"IL", "MN"}

    coverage = data["property_county_coverage"]
    assert "IL" in coverage
    assert "MN" in coverage

    il_counties = coverage["IL"]["counties"]
    mn_counties = coverage["MN"]["counties"]
    assert "Cook" in il_counties
    assert "DuPage" in il_counties
    assert "Hennepin" in mn_counties
    assert "Ramsey" in mn_counties


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


def test_stream_route_returns_error_event_on_generator_failure():
    with patch("backend_api.run_investigation_stream", side_effect=RuntimeError("stream exploded")):
        client = TestClient(app)
        response = client.post("/api/investigate/stream", json={"query": "Investigate Illinois providers in ZIP 60612"})
        assert response.status_code == 200
        body = response.text
        assert '"event": "error"' in body or '"event":"error"' in body
        assert "stream exploded" in body
