"""API tests for application initialisation, health checks and error handling."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app, create_app

pytestmark = pytest.mark.db


def test_application_initialises_with_expected_routes():
    # The OpenAPI schema is the public description of every registered route.
    paths = set(create_app().openapi()["paths"])
    assert {
        "/health",
        "/health/ready",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/users/me",
        "/api/v1/ratings",
        "/api/v1/ratings/{movie_id}",
        "/api/v1/watchlist",
        "/api/v1/watchlist/{movie_id}",
    } <= paths


def test_liveness_check(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_check_with_database_available(client: TestClient):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_readiness_check_reports_database_failure_without_details(client: TestClient):
    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError(
                "SELECT 1", {}, Exception("connection to 10.0.0.5 failed for user secret_user")
            )

    app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unreachable"}
    assert "secret_user" not in response.text


def test_openapi_schema_is_available(client: TestClient):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "AuraCinema API"


def test_unknown_route_returns_json_404(client: TestClient):
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_unhandled_errors_return_generic_500_without_internal_details():
    test_app = create_app()

    @test_app.get("/boom")
    def boom():
        raise RuntimeError("internal detail: password=hunter2 host=db.internal")

    with TestClient(test_app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "hunter2" not in response.text


def test_cors_allows_configured_origin_only(client: TestClient):
    preflight = {
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "Authorization",
    }
    allowed = client.options(
        "/api/v1/ratings", headers={"Origin": "http://localhost:5173", **preflight}
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    blocked = client.options(
        "/api/v1/ratings", headers={"Origin": "https://evil.example", **preflight}
    )
    assert "access-control-allow-origin" not in blocked.headers
