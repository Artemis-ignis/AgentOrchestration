from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware import AuthMiddleware, RateLimitMiddleware
from src.api.server import create_app


ORIGIN = "https://console.example"


def test_cors_preflight_succeeds_without_bearer_token():
    client = TestClient(create_app())

    response = client.options(
        "/api/v2/agents",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "authorization" in response.headers["access-control-allow-headers"]
    assert "Unauthorized" not in response.text


def test_real_options_request_still_requires_authentication():
    client = TestClient(create_app())

    response = client.options("/api/v2/agents", headers={"Origin": ORIGIN})

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.text == "Unauthorized"


def test_real_api_request_still_requires_authentication():
    client = TestClient(create_app())

    response = client.get("/api/v2/agents", headers={"Origin": ORIGIN})

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.text == "Unauthorized"


def test_rejected_request_does_not_consume_rate_limit_capacity():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, max_requests=1, window=60)
    app.add_middleware(AuthMiddleware)

    @app.get("/api/v2/protected")
    async def protected():
        return {"ok": True}

    client = TestClient(app)

    assert client.get("/api/v2/protected").status_code == 401
    assert client.get("/api/v2/protected").status_code == 401
    assert (
        client.get(
            "/api/v2/protected",
            headers={"Authorization": "Bearer valid-local-token"},
        ).status_code
        == 200
    )
