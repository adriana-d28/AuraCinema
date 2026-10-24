"""ORM models.

Importing every model here registers it on Base.metadata, which Alembic uses
to compare the models with the database when generating migrations.
"""

from app.models.rating import Rating
from app.models.user import User
from app.models.watchlist import WatchlistItem

__all__ = ["Rating", "User", "WatchlistItem"]
