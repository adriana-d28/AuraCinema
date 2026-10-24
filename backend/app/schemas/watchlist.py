from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WatchlistItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    movie_id: int
    added_at: datetime
