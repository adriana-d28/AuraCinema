"""Endpoints for the authenticated user's own account ("me").

There is no endpoint that reads or changes another user's account: the user
is always the one identified by the access token. The profile is therefore
private to its owner (student decision, intermediate backend phase).
"""

from fastapi import APIRouter, HTTPException, Response, UploadFile, status

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


@router.put(
    "/me/picture",
    response_model=UserRead,
    summary="Upload or replace my profile picture (JPEG, PNG or WebP, at most 2 MB)",
    responses={
        413: {"description": "The file is larger than 2 MB"},
        422: {"description": "The file is not a JPEG, PNG or WebP image"},
    },
)
def upload_my_picture(picture: UploadFile, current_user: CurrentUser, db: DbSession) -> UserRead:
    """Multipart form with one file field, `picture`. The server stores a new
    512x512 JPEG made from it, never the uploaded file itself."""
    # Read one byte more than allowed: enough to know the file is too large.
    data = picture.file.read(user_service.PICTURE_MAX_BYTES + 1)
    try:
        user = user_service.set_picture(db, current_user, data)
    except user_service.PictureTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="The picture must be 2 MB or smaller",
        ) from None
    except user_service.InvalidPictureError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The picture must be a JPEG, PNG or WebP image",
        ) from None
    return UserRead.model_validate(user)


@router.get(
    "/me/picture",
    summary="Get my profile picture",
    response_class=Response,
    responses={
        200: {"content": {"image/jpeg": {}}, "description": "The picture"},
        404: {"description": "No picture uploaded"},
    },
)
def read_my_picture(current_user: CurrentUser, db: DbSession) -> Response:
    picture = user_service.get_picture(db, current_user.id)
    if picture is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile picture")
    return Response(
        content=picture.content,
        # The stored type, set by the server, never the type the client sent.
        media_type=picture.content_type,
        headers={
            # Personal data: the browser must not keep a copy on disk.
            "Cache-Control": "private, no-store",
            # The browser must not guess another type from the content.
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/me/picture",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove my profile picture",
)
def delete_my_picture(current_user: CurrentUser, db: DbSession) -> None:
    user_service.delete_picture(db, current_user)


@router.get(
    "/me/stats",
    response_model=UserStatistics,
    summary="Summarise my ratings overall and per genre (Profile page)",
)
def read_my_statistics(current_user: CurrentUser, db: DbSession) -> UserStatistics:
    """Counts and average ratings of the user's own ratings, per genre. It is
    descriptive only: no recommendation model and no time dimension."""
    return user_service.rating_statistics(db, current_user.id)
