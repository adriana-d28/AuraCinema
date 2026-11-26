from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.utils import utc_now

if TYPE_CHECKING:
    from app.models.user import User


class UserPicture(Base):
    """The profile picture of one account (at most one per user).

    The image itself is stored here (PostgreSQL BYTEA), not a link to a file,
    so it lives in the already persistent and backed-up database volume, is
    served only to its owner through an authenticated endpoint, and is deleted
    together with the account (ON DELETE CASCADE).

    It is a separate table, not a column of users, because every authenticated
    request loads the User row: the image bytes are read only when the picture
    itself is requested. Only images re-encoded by the server are stored
    (user_service.set_picture), never the uploaded file as it was sent.
    """

    __tablename__ = "user_pictures"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Always "image/jpeg" today (the server re-encodes every upload), stored so
    # the response type never depends on what the client claimed.
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    user: Mapped["User"] = relationship(back_populates="picture")
