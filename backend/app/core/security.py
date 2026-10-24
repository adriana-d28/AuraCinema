"""Password hashing and JWT access-token helpers.

No cryptography is implemented here: hashing is delegated to pwdlib (Argon2id)
and token signing/verification to PyJWT. This module only fixes the policy
(which algorithm, which claims, how long tokens live).
"""

from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import get_settings

# Argon2id is the password-hashing algorithm recommended by OWASP. The hasher
# generates a random salt per password and embeds the parameters in the hash,
# so parameters can be strengthened later without breaking existing hashes.
password_hash = PasswordHash((Argon2Hasher(),))

# Hash used to spend the same verification time when a login email does not
# exist, so response timing does not reveal which emails are registered.
_DUMMY_HASH = password_hash.hash("dummy-password-used-only-for-timing-protection")


class InvalidTokenError(Exception):
    """Raised when an access token is missing claims, expired, or tampered with."""


def hash_password(plain_password: str) -> str:
    return password_hash.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def verify_dummy_password(plain_password: str) -> None:
    """Perform a throwaway verification to equalise login timing."""
    password_hash.verify(plain_password, _DUMMY_HASH)


def create_access_token(user_id: int, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT whose subject is the user's database ID."""
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload = {
        # The JWT specification requires "sub" to be a string.
        "sub": str(user_id),
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> int:
    """Validate a JWT and return the user ID stored in its subject claim.

    The accepted algorithm list is pinned to the configured algorithm. This
    rejects tokens declaring "alg": "none" or any other algorithm, which is a
    classic JWT forgery technique.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat"]},
        )
        return int(payload["sub"])
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        # Callers only need to know the token is unusable; the specific reason
        # (expired, bad signature, malformed) is deliberately not exposed.
        raise InvalidTokenError from exc
