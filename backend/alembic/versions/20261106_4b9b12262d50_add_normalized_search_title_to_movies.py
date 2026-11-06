"""add normalized search_title to movies

Adds movies.search_title, a normalized copy of the MovieLens title used only
for searching (lower case, no accents or punctuation, trailing articles moved
back: "Matrix, The (1999)" -> "matrix the 1999|the matrix"). The original
title column is not changed.

Existing rows are filled in by this migration using the application's own
normalization function (app.core.titles.build_search_title), so search works
immediately after upgrading. The column is first added with an empty default
so the NOT NULL constraint can be applied to a table that already has rows;
the default is removed afterwards. In offline mode (--sql) the backfill
cannot run: rows keep '' until `python -m scripts.seed_movies` is run, which
recomputes search_title for every movie.

Revision ID: 4b9b12262d50
Revises: bbf98bce938e
Create Date: 2026-11-06 18:28:13.786411

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

from app.core.titles import build_search_title


# revision identifiers, used by Alembic.
revision: str = '4b9b12262d50'
down_revision: Union[str, Sequence[str], None] = 'bbf98bce938e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'movies', sa.Column('search_title', sa.Text(), server_default='', nullable=False)
    )
    if not context.is_offline_mode():
        connection = op.get_bind()
        rows = connection.execute(sa.text('SELECT movie_id, title FROM movies')).all()
        if rows:
            connection.execute(
                sa.text('UPDATE movies SET search_title = :search_title WHERE movie_id = :movie_id'),
                [
                    {'movie_id': movie_id, 'search_title': build_search_title(title)}
                    for movie_id, title in rows
                ],
            )
    # New rows always receive a value from the application (Movie model).
    op.alter_column('movies', 'search_title', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('movies', 'search_title')
