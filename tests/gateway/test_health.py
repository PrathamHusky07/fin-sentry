"""GET /health -- includes gateway_instance_id (Day 8 Gate D failover
evidence: a minimal, non-business identifier for which replica answered)."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from finsentry.gateway.main import app


async def test_health_includes_gateway_instance_id() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["gateway_instance_id"], str)
    assert body["gateway_instance_id"] != ""
