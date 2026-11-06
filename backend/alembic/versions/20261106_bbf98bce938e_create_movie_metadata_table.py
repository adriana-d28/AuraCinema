"""create movie_metadata table

Creates the table that stores supplementary TMDB metadata locally, one row
per catalogue movie at most. movie_id is both the primary key and a foreign
key to movies.movie_id (ON DELETE CASCADE: the rows are derived data only).

The table is created empty. It is filled by the maintenance scripts
(python -m scripts.refresh_movie_metadata and python -m scripts.validate_tmdb_ids),
never by this migration, so upgrading does not contact TMDB. Existing movies,
ratings and watchlist entries are not modified.

Revision ID: bbf98bce938e
Revises: 6bfe976fc037
Create Date: 2026-11-06 18:28:12.952312

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bbf98bce938e'
down_revision: Union[str, Sequence[str], None] = '6bfe976fc037'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Values fixed at the time of this migration (see app/models/movie_metadata.py).
REFRESH_STATUSES = ("ok", "not_found", "rate_limited", "timeout", "unavailable", "invalid_response")
VALIDATION_STATUSES = (
    "not_checked", "valid", "not_found", "title_mismatch",
    "year_mismatch", "ambiguous", "temporary_error",
)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('movie_metadata',
    sa.Column('movie_id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('overview', sa.Text(), nullable=True),
    sa.Column('release_date', sa.Date(), nullable=True),
    sa.Column('runtime', sa.Integer(), nullable=True),
    sa.Column('poster_path', sa.String(length=255), nullable=True),
    sa.Column('metadata_source', sa.String(length=20), nullable=True),
    sa.Column('metadata_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('refresh_status', sa.String(length=20), nullable=True),
    sa.Column('refresh_attempted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tmdb_validation_status', sa.String(length=20), server_default='not_checked', nullable=False),
    sa.Column('tmdb_validated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tmdb_validation_note', sa.String(length=255), nullable=True),
    sa.Column('tmdb_validation_http_status', sa.SmallInteger(), nullable=True),
    sa.CheckConstraint('runtime > 0', name=op.f('ck_movie_metadata_runtime_positive')),
    sa.CheckConstraint(
        f'refresh_status IN ({_in_list(REFRESH_STATUSES)})',
        name=op.f('ck_movie_metadata_refresh_status_valid'),
    ),
    sa.CheckConstraint(
        f'tmdb_validation_status IN ({_in_list(VALIDATION_STATUSES)})',
        name=op.f('ck_movie_metadata_tmdb_validation_status_valid'),
    ),
    sa.ForeignKeyConstraint(['movie_id'], ['movies.movie_id'], name=op.f('fk_movie_metadata_movie_id_movies'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('movie_id', name=op.f('pk_movie_metadata'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Only derived TMDB data is lost; it can be fetched again with the scripts.
    op.drop_table('movie_metadata')
