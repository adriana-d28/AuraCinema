"""Security-oriented tests: injection attempts and sensitive-data exposure.

These are targeted automated checks, not a penetration test.
"""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User
from tests.helpers import TEST_JWT_SECRET, TEST_PASSWORD, login, register_user

pytestmark = pytest.mark.db

SQL_INJECTION_PAYLOADS = [
    "' OR '1'='1",
    "admin@example.com'--",
    "x@example.com'; DROP TABLE users; --",
]


@pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
def test_sql_injection_in_login_does_not_authenticate(
    client: TestClient, db_session: Session, payload
):
    register_user(client, "victim@example.com")
    response = login(client, payload, "' OR '1'='1")
    assert response.status_code == 401
    # The users table still exists and still contains the victim.
    assert db_session.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
def test_sql_injection_in_registration_email_is_rejected(client: TestClient, payload):
    assert register_user(client, payload).status_code == 422


def test_responses_never_contain_password_hash_or_secrets(client: TestClient, db_session: Session):
    register_response = register_user(client, "exposed@example.com")
    token = login(client, "exposed@example.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me_response = client.get("/api/v1/users/me", headers=headers)
    failed_login = login(client, "exposed@example.com", "wrong-password")

    stored_hash = db_session.scalar(select(User.password_hash))
    for response in (register_response, me_response, failed_login):
        assert stored_hash not in response.text
        assert '"password' not in response.text  # no "password"/"password_hash" JSON key
        assert TEST_PASSWORD not in response.text
        assert TEST_JWT_SECRET not in response.text
        assert "auracinema_test" not in response.text


def test_logs_do_not_contain_passwords_tokens_or_secrets(client: TestClient, caplog):
    caplog.set_level(logging.DEBUG)
    register_user(client, "logs@example.com")
    token = login(client, "logs@example.com").json()["access_token"]
    client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    login(client, "logs@example.com", "wrong-password-in-logs")

    assert "New user account created" in caplog.text  # logging actually ran
    for sensitive in (
        TEST_PASSWORD,
        "wrong-password-in-logs",
        token,
        TEST_JWT_SECRET,
        "logs@example.com",
    ):
        assert sensitive not in caplog.text


def test_oversized_password_is_rejected_before_hashing(client: TestClient):
    response = client.post(
        "/api/v1/auth/register", json={"email": "big@example.com", "password": "x" * 100_000}
    )
    assert response.status_code == 422
