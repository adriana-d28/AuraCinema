from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.auth import CurrentPassword, NewPassword, NormalisedEmail
from app.schemas.common import ProfileBio, ProfileLocation, ProfileName


class UserRead(BaseModel):
    """The account data returned to its owner. The password hash is
    intentionally not a field, so it can never be serialised into a response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime
    # Profile fields. `name` is null only for accounts created before names
    # were introduced; location and bio are optional.
    name: str | None
    location: str | None
    bio: str | None


class UserProfileUpdate(BaseModel):
    """Body of PATCH /users/me: change any of the profile fields.

    Only the fields present in the body are changed; omitted fields keep their
    value. For location and bio, null or an empty string removes the value.
    The name can be changed but not removed, because it is required.
    Email and password are changed through their own endpoints, which ask for
    the current password.
    """

    model_config = ConfigDict(extra="forbid")

    name: ProfileName | None = None
    location: ProfileLocation | None = None
    bio: ProfileBio | None = None

    @field_validator("name", mode="after")
    @classmethod
    def _name_cannot_be_removed(cls, value: str | None) -> str | None:
        # An omitted name never reaches this validator (defaults are not
        # validated); only an explicit null does.
        if value is None:
            raise ValueError("Name cannot be removed")
        return value

    @field_validator("location", "bio", mode="after")
    @classmethod
    def _empty_text_means_no_value(cls, value: str | None) -> str | None:
        # The text was already trimmed, so "   " arrives here as "".
        return value or None


class EmailChangeRequest(BaseModel):
    """Body of PUT /users/me/email. The current password is required, so a
    stolen access token alone cannot take over the account."""

    model_config = ConfigDict(extra="forbid")

    new_email: NormalisedEmail
    current_password: CurrentPassword


class PasswordChangeRequest(BaseModel):
    """Body of PUT /users/me/password. The new password follows the same
    rules as at registration (15-128 characters)."""

    model_config = ConfigDict(extra="forbid")

    current_password: CurrentPassword
    new_password: NewPassword


class GenreStatistics(BaseModel):
    """How the user rated the movies of one genre."""

    genre: str
    rating_count: int = Field(ge=1, description="Rated movies that have this genre")
    average_rating: float = Field(description="Mean of those ratings (0.5-5.0), 2 decimals")


class UserStatistics(BaseModel):
    """Descriptive summary of the user's own ratings (Profile page).

    It only counts and averages stored ratings: no prediction, no model and
    no time dimension. A movie with several genres counts once in EACH of its
    genres, so the genre counts can add up to more than rating_count. Movies
    without genres are counted in rating_count but in no genre.
    """

    rating_count: int = Field(ge=0)
    average_rating: float | None = Field(description="Null when there are no ratings")
    genres: list[GenreStatistics] = Field(
        description="Most rated genre first; ties by higher average, then by name"
    )
