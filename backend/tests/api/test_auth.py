"""API tests for registration, login and the authenticated-user endpoint."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models import User
from tests.helpers import TEST_PASSWORD, auth_headers, login, register_user

pytestmark = pytest.mark.db

REGISTER_URL = "/api/v1/auth/register"
ME_URL = "/api/v1/users/me"


class TestRegistration:
    def test_successful_registration_returns_public_fields_only(self, client: TestClient):
        response = register_user(client, "new@example.com")
        assert response.status_code == 201
        body = response.json()
        assert set(body) == {"id", "email", "created_at"}
        assert body["email"] == "new@example.com"
        assert TEST_PASSWORD not in response.text

    def test_password_is_stored_hashed(self, client: TestClient, db_session: Session):
        register_user(client, "hash@example.com")
        user = db_session.scalar(select(User).where(User.email == "hash@example.com"))
        assert user.password_hash != TEST_PASSWORD
        assert TEST_PASSWORD not in user.password_hash
        assert user.password_hash.startswith("$argon2id$")

    def test_email_is_normalised_on_registration(self, client: TestClient):
        response = register_user(client, "Mixed.Case@Example.COM")
        assert response.status_code == 201
        assert response.json()["email"] == "mixed.case@example.com"

    def test_duplicate_email_is_rejected(self, client: TestClient):
        assert register_user(client, "dup@example.com").status_code == 201
        response = register_user(client, "dup@example.com")
        assert response.status_code == 409
        assert response.json() == {"detail": "Email already registered"}

    def test_duplicate_email_with_different_case_is_rejected(self, client: TestClient):
        register_user(client, "case@example.com")
        assert register_user(client, "CASE@Example.com").status_code == 409

    @pytest.mark.parametrize(
        "payload",
        [
            {"email": "not-an-email", "password": TEST_PASSWORD},
            {"email": "a@example.com", "password": "x" * 14},
            {"email": "a@example.com", "password": "x" * 129},
            {"email": "a@example.com"},
            {"password": TEST_PASSWORD},
            {},
            {"email": 123, "password": TEST_PASSWORD},
            {"email": "a@example.com", "password": TEST_PASSWORD, "id": 1},
        ],
    )
    def test_invalid_registration_payloads_are_rejected(self, client: TestClient, payload):
        assert client.post(REGISTER_URL, json=payload).status_code == 422

    def test_malformed_json_is_rejected(self, client: TestClient):
        response = client.post(
            REGISTER_URL,
            content='{"email": "a@example.com", "password": ',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_validation_errors_do_not_echo_the_password(self, client: TestClient):
        response = client.post(REGISTER_URL, json={"email": "a@example.com", "password": "secret7"})
        assert response.status_code == 422
        assert "secret7" not in response.text
        assert response.json()["detail"][0]["loc"] == ["body", "password"]


class TestLogin:
    def test_successful_login_returns_bearer_token(self, client: TestClient):
        register_user(client, "login@example.com")
        response = login(client, "login@example.com")
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 3600
        assert body["access_token"].count(".") == 2  # header.payload.signature

    def test_login_email_is_case_insensitive(self, client: TestClient):
        register_user(client, "login@example.com")
        assert login(client, "LOGIN@example.com").status_code == 200

    def test_wrong_password_and_unknown_email_get_identical_responses(self, client: TestClient):
        register_user(client, "login@example.com")
        wrong_password = login(client, "login@example.com", "wrong-password")
        unknown_email = login(client, "nobody@example.com")
        assert wrong_password.status_code == unknown_email.status_code == 401
        assert (
            wrong_password.json()
            == unknown_email.json()
            == {"detail": "Incorrect email or password"}
        )
        assert wrong_password.headers["www-authenticate"] == "Bearer"

    @pytest.mark.parametrize(
        "form", [{"username": "a@example.com"}, {"password": TEST_PASSWORD}, {}]
    )
    def test_missing_login_fields_are_rejected(self, client: TestClient, form):
        assert client.post("/api/v1/auth/login", data=form).status_code == 422

    def test_json_body_is_not_accepted_for_login(self, client: TestClient):
        register_user(client, "login@example.com")
        response = client.post(
            "/api/v1/auth/login", json={"username": "login@example.com", "password": TEST_PASSWORD}
        )
        assert response.status_code == 422


class TestCurrentUser:
    def test_valid_token_returns_current_user(self, client: TestClient):
        headers = auth_headers(client, "me@example.com")
        response = client.get(ME_URL, headers=headers)
        assert response.status_code == 200
        assert response.json()["email"] == "me@example.com"
        assert "password_hash" not in response.json()

    def test_missing_token_is_rejected(self, client: TestClient):
        response = client.get(ME_URL)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    @pytest.mark.parametrize(
        "header",
        ["Bearer not-a-jwt", "Bearer ", "Basic dXNlcjpwYXNz", "not-a-scheme", "Bearer a.b.c"],
    )
    def test_invalid_authorization_headers_are_rejected(self, client: TestClient, header):
        response = client.get(ME_URL, headers={"Authorization": header})
        assert response.status_code == 401

    def test_expired_token_is_rejected(self, client: TestClient):
        register_user(client, "exp@example.com")
        token = create_access_token(1, expires_delta=timedelta(seconds=-10))
        response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json() == {"detail": "Could not validate credentials"}

    def test_token_for_deleted_user_is_rejected(self, client: TestClient, db_session: Session):
        headers = auth_headers(client, "gone@example.com")
        db_session.delete(db_session.scalar(select(User).where(User.email == "gone@example.com")))
        db_session.commit()
        assert client.get(ME_URL, headers=headers).status_code == 401

    @pytest.mark.parametrize(
        ("method", "url"),
        [
            ("get", "/api/v1/users/me"),
            ("get", "/api/v1/ratings"),
            ("put", "/api/v1/ratings/1"),
            ("delete", "/api/v1/ratings/1"),
            ("get", "/api/v1/watchlist"),
            ("put", "/api/v1/watchlist/1"),
            ("delete", "/api/v1/watchlist/1"),
        ],
    )
    def test_protected_endpoints_reject_unauthenticated_requests(
        self, client: TestClient, method, url
    ):
        kwargs = (
            {"json": {"rating": 4.0}}
            if url.startswith("/api/v1/ratings/") and method == "put"
            else {}
        )
        response = getattr(client, method)(url, **kwargs)
        assert response.status_code == 401
