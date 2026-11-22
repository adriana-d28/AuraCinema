"""Endpoints for the authenticated user's own account ("me").

There is no endpoint that reads or changes another user's account: the user
is always the one identified by the access token. The profile is therefore
private to its owner (student decision, intermediate backend phase).
"""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.user import (
    EmailChangeRequest,
    PasswordChangeRequest,
    UserProfileUpdate,
    UserRead,
    UserStatistics,
)
from app.services import user_service
from app.services.auth_service import EmailAlreadyRegisteredError

router = APIRouter(prefix="/users", tags=["users"])

# A wrong current password is answered with 403 (the token is valid, but the
# confirmation failed), not 401, so clients do not mistake it for an expired
# session and log the user out.
INCORRECT_PASSWORD = {403: {"description": "Current password is incorrect"}}


def _incorrect_password() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Current password is incorrect"
    )


@router.get("/me", response_model=UserRead, summary="Get the authenticated user's account")
def read_current_user(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)


@router.patch("/me", response_model=UserRead, summary="Update my profile (name, location, bio)")
def update_my_profile(
    payload: UserProfileUpdate, current_user: CurrentUser, db: DbSession
) -> UserRead:
    """Send only the fields to change. For location and bio, null or an empty
    string removes the value; the name can be changed but not removed."""
    # exclude_unset: fields not present in the request body stay unchanged.
    changes = payload.model_dump(exclude_unset=True)
    user = user_service.update_profile(db, current_user, changes)
    return UserRead.model_validate(user)


@router.put(
    "/me/email",
    response_model=UserRead,
    summary="Change my login email",
    responses={**INCORRECT_PASSWORD, 409: {"description": "Email already registered"}},
)
def change_my_email(
    payload: EmailChangeRequest, current_user: CurrentUser, db: DbSession
) -> UserRead:
    try:
        user = user_service.change_email(
            db, current_user, payload.new_email, payload.current_password
        )
    except user_service.IncorrectPasswordError:
        raise _incorrect_password() from None
    except EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from None
    return UserRead.model_validate(user)


@router.put(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change my password",
    responses=INCORRECT_PASSWORD,
)
def change_my_password(
    payload: PasswordChangeRequest, current_user: CurrentUser, db: DbSession
) -> None:
    try:
        user_service.change_password(
            db, current_user, payload.current_password, payload.new_password
        )
    except user_service.IncorrectPasswordError:
        raise _incorrect_password() from None


@router.get(
    "/me/stats",
    response_model=UserStatistics,
    summary="Summarise my ratings overall and per genre (Profile page)",
)
def read_my_statistics(current_user: CurrentUser, db: DbSession) -> UserStatistics:
    """Counts and average ratings of the user's own ratings, per genre. It is
    descriptive only: no recommendation model and no time dimension."""
    return user_service.rating_statistics(db, current_user.id)
