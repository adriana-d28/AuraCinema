"""Helper functions shared by the API tests."""

# Fixed, test-only values. They are not secrets and are never used outside tests.
TEST_JWT_SECRET = "test-only-jwt-secret-key-never-used-in-real-environments"
TEST_PASSWORD = "CorrectHorse-42"


def register_user(client, email: str, password: str = TEST_PASSWORD):
    return client.post("/api/v1/auth/register", json={"email": email, "password": password})


def login(client, email: str, password: str = TEST_PASSWORD):
    # OAuth2 password flow: form-encoded body with "username" and "password".
    return client.post("/api/v1/auth/login", data={"username": email, "password": password})


def auth_headers(client, email: str, password: str = TEST_PASSWORD) -> dict[str, str]:
    """Register a user, log in, and return the Authorization header."""
    assert register_user(client, email, password).status_code == 201
    response = login(client, email, password)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
