"""create movies table

Creates the movie catalogue table. The primary key is the original MovieLens
movieId (no sequence), and the TMDB and IMDb identifiers are nullable.

The table is created empty; it is filled by the import script
(python -m scripts.seed_movies), not by this migration, so the schema history
does not depend on a data file outside the backend.

Revision ID: 413ce2f03dd0
Revises: b31c04872662
Create Date: 2026-10-29 12:46:10.385925

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '413ce2f03dd0'
down_revision: Union[str, Sequence[str], None] = 'b31c04872662'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('movies',
    sa.Column('movie_id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('genres', sa.String(length=255), nullable=False),
    sa.Column('tmdb_id', sa.Integer(), nullable=True),
    sa.Column('imdb_id', sa.Integer(), nullable=True),
    sa.CheckConstraint('movie_id > 0', name=op.f('ck_movies_movie_id_positive')),
    sa.CheckConstraint('tmdb_id > 0', name=op.f('ck_movies_tmdb_id_positive')),
    sa.CheckConstraint('imdb_id > 0', name=op.f('ck_movies_imdb_id_positive')),
    sa.PrimaryKeyConstraint('movie_id', name=op.f('pk_movies'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    # The foreign keys that reference this table are removed by the next
    # revision's downgrade, which always runs first.
    op.drop_table('movies')
