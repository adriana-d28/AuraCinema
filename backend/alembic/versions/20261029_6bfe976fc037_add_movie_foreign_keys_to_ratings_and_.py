"""add movie foreign keys to ratings and watchlist

Adds foreign keys ratings.movie_id -> movies.movie_id and
watchlist_items.movie_id -> movies.movie_id. No ON DELETE action is set, so
PostgreSQL refuses to delete a movie that is still rated or in a watchlist.

Safety check: before adding the keys, the migration looks for ratings or
watchlist rows whose movie_id is not in the movies table. If any exist, it
stops with an explanation instead of deleting user data. On a database that
already has user data, the catalogue must be imported first:

    alembic upgrade 413ce2f03dd0
    python -m scripts.seed_movies
    alembic upgrade head

Revision ID: 6bfe976fc037
Revises: 413ce2f03dd0
Create Date: 2026-10-29 12:46:11.043978

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6bfe976fc037'
down_revision: Union[str, Sequence[str], None] = '413ce2f03dd0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# movie_id values used by ratings or watchlist entries but missing from movies.
MISSING_MOVIES_SQL = sa.text(
    """
    SELECT DISTINCT referenced.movie_id
    FROM (
        SELECT movie_id FROM ratings
        UNION
        SELECT movie_id FROM watchlist_items
    ) AS referenced
    WHERE NOT EXISTS (
        SELECT 1 FROM movies WHERE movies.movie_id = referenced.movie_id
    )
    ORDER BY referenced.movie_id
    """
)


def upgrade() -> None:
    """Upgrade schema."""
    # In offline mode ("alembic upgrade head --sql") there is no connection to
    # query, so the check is skipped and only the SQL script is produced.
    missing = []
    if not context.is_offline_mode():
        missing = [row[0] for row in op.get_bind().execute(MISSING_MOVIES_SQL)]
    if missing:
        raise RuntimeError(
            f"Cannot add the movie foreign keys: {len(missing)} movie_id value(s) used in "
            f"ratings/watchlist_items are not in the movies table (first values: "
            f"{missing[:10]}). No data was changed. Import the catalogue first: "
            "'alembic upgrade 413ce2f03dd0', then 'python -m scripts.seed_movies', "
            "then 'alembic upgrade head'."
        )

    op.create_foreign_key(
        op.f('fk_ratings_movie_id_movies'), 'ratings', 'movies', ['movie_id'], ['movie_id']
    )
    op.create_foreign_key(
        op.f('fk_watchlist_items_movie_id_movies'),
        'watchlist_items', 'movies', ['movie_id'], ['movie_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('fk_watchlist_items_movie_id_movies'), 'watchlist_items', type_='foreignkey')
    op.drop_constraint(op.f('fk_ratings_movie_id_movies'), 'ratings', type_='foreignkey')
