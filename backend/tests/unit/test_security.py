"""Unit tests for password hashing and JWT handling (no database required)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from tests.helpers import TEST_JWT_SECRET

PASSWORD = "S3cure-Password!"


class TestPasswordHashing:
    def test_hash_is_not_the_plaintext_password(self):
        hashed = hash_password(PASSWORD)
        assert hashed != PASSWORD
        assert PASSWORD not in hashed

    def test_hash_uses_argon2id(self):
        assert hash_password(PASSWORD).startswith("$argon2id$")

    def test_same_password_produces_different_hashes(self):
        # A random salt per hash prevents identical passwords being detectable.
        assert hash_password(PASSWORD) != hash_password(PASSWORD)

    def test_correct_password_verifies(self):
        assert verify_password(PASSWORD, hash_password(PASSWORD)) is True

    def test_wrong_password_does_not_verify(self):
        assert verify_password("wrong-password", hash_password(PASSWORD)) is False


class TestAccessTokens:
    def test_token_round_trip_returns_user_id(self):
        token = create_access_token(42)
        assert decode_access_token(token) == 42

    def test_token_contains_expected_claims(self):
        token = create_access_token(7)
        payload = jwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])
        assert payload["sub"] == "7"
        assert payload["exp"] > payload["iat"]
        assert payload["exp"] - payload["iat"] == 60 * 60

    def test_expired_token_is_rejected(self):
        token = create_access_token(1, expires_delta=timedelta(seconds=-1))
        with pytest.raises(InvalidTokenError):
            decode_access_token(token)

    def test_tampered_token_is_rejected(self):
        token = create_access_token(1)
        header, payload, signature = token.split(".")
        tampered = f"{header}.{payload}.{signature[:-4]}AAAA"
        with pytest.raises(InvalidTokenError):
            decode_access_token(tampered)

    def test_token_signed_with_another_secret_is_rejected(self):
        now = datetime.now(UTC)
        forged = jwt.encode(
            {"sub": "1", "iat": now, "exp": now + timedelta(minutes=5)},
            "attacker-controlled-secret-key-with-enough-length",
            algorithm="HS256",
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(forged)

    def test_unsigned_alg_none_token_is_rejected(self):
        now = datetime.now(UTC)
        unsigned = jwt.encode(
            {"sub": "1", "iat": now, "exp": now + timedelta(minutes=5)}, None, algorithm="none"
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(unsigned)

    @pytest.mark.parametrize(
        "case",
        ["missing_sub", "missing_exp", "missing_iat", "non_integer_sub"],
    )
    def test_token_with_missing_or_invalid_claims_is_rejected(self, case):
        now = datetime.now(UTC)
        payload = {"sub": "1", "iat": now, "exp": now + timedelta(minutes=5)}
        if case == "non_integer_sub":
            payload["sub"] = "not-a-number"
        else:
            del payload[case.removeprefix("missing_")]
        token = jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")
        with pytest.raises(InvalidTokenError):
            decode_access_token(token)

    @pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "Bearer xyz"])
    def test_malformed_token_is_rejected(self, garbage):
        with pytest.raises(InvalidTokenError):
            decode_access_token(garbage)
