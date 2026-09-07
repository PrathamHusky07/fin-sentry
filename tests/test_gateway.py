from httpx import ASGITransport, AsyncClient

from finsentry.gateway.main import app


async def test_health_returns_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_chat_completions_without_downstream_returns_503() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "test", "messages": [{"role": "user", "content": "hello"}]},
        )
    assert response.status_code == 503
    assert "DOWNSTREAM_URL" in response.json()["error"]
