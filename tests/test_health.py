"""Health endpoint tests."""

import pytest


@pytest.mark.unit
async def test_health_returns_200(client) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200


@pytest.mark.unit
async def test_health_reports_status_and_version(client) -> None:
    response = await client.get("/api/v1/health")
    body = response.json()
    assert body["status"] in ("healthy", "degraded")
    assert body["version"] == "0.1.0"
    assert "timestamp" in body
