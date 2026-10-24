from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserRead(BaseModel):
    """Public account data. The password hash is intentionally not a field,
    so it can never be serialised into an API response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime
