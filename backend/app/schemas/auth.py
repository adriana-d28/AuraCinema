from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

# Passwords: NIST SP 800-63B (revision 4) requires at least 15 characters when
# a password is the only authentication factor, as it is here, and asks that
# at least 64 characters be allowed. The 128 maximum bounds hashing cost and
# rejects absurdly large payloads. No composition rules (e.g. "must contain a
# digit") are imposed, also following NIST guidance.
PASSWORD_MIN_LENGTH = 15
PASSWORD_MAX_LENGTH = 128


def normalise_email(value: str) -> str:
    """Lower-case the whole address so the same mailbox maps to one account."""
    return value.strip().lower()


NormalisedEmail = Annotated[EmailStr, AfterValidator(normalise_email)]


class RegisterRequest(BaseModel):
    # extra="forbid" rejects unexpected fields (e.g. a client-supplied "id")
    # instead of silently ignoring them.
    model_config = ConfigDict(extra="forbid")

    email: NormalisedEmail
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class TokenResponse(BaseModel):
    """OAuth2-compatible bearer token response returned by the login endpoint."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds")
