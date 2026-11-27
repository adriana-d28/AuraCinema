"""add MovieLens rating statistics to movies

Adds the MovieLens community rating of each catalogue movie, shown in the UI
next to the other movie information:
- movies.movielens_average_rating: mean MovieLens rating (0.5-5.0);
- movies.movielens_rating_count: number of MovieLens ratings behind that mean.

Both values are taken from the popularity baseline output
(ml/data/models/popularity_baseline.csv, MovieLens training ratings) by
scripts/seed_movies.py. The columns are nullable: existing rows stay NULL
until the seed script is run again, and the two values are either both set
or both NULL. The downgrade drops the columns, which only loses data that
the seed script can import again.

Revision ID: a3f5c8e2d917
Revises: 7c2e9a41d5b3
Create Date: 2026-11-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f5c8e2d917'
down_revision: Union[str, Sequence[str], None] = '7c2e9a41d5b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('movies', sa.Column('movielens_average_rating', sa.Float(), nullable=True))
    op.add_column('movies', sa.Column('movielens_rating_count', sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f('ck_movies_movielens_average_rating_in_scale'),
        'movies',
        'movielens_average_rating BETWEEN 0.5 AND 5.0',
    )
    op.create_check_constraint(
        op.f('ck_movies_movielens_rating_count_positive'), 'movies', 'movielens_rating_count > 0'
    )
    op.create_check_constraint(
        op.f('ck_movies_movielens_rating_statistics_together'),
        'movies',
        '(movielens_average_rating IS NULL) = (movielens_rating_count IS NULL)',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('ck_movies_movielens_rating_statistics_together'), 'movies', type_='check')
    op.drop_constraint(op.f('ck_movies_movielens_rating_count_positive'), 'movies', type_='check')
    op.drop_constraint(op.f('ck_movies_movielens_average_rating_in_scale'), 'movies', type_='check')
    op.drop_column('movies', 'movielens_rating_count')
    op.drop_column('movies', 'movielens_average_rating')
