"""add user profile pictures

Adds the profile picture (Profile and Settings pages, Phase 7.5):
- a new table user_pictures, holding the re-encoded image of at most one
  picture per account (user_id is the primary key). ON DELETE CASCADE
  removes the picture together with its account;
- a nullable column users.picture_updated_at, which tells the client
  whether a picture exists without reading the image.

Existing rows are not changed (no account has a picture yet). The downgrade
drops the table and the column, which only loses uploaded pictures.

Revision ID: 7c2e9a41d5b3
Revises: fdc40b8c0e0e
Create Date: 2026-11-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c2e9a41d5b3'
down_revision: Union[str, Sequence[str], None] = 'fdc40b8c0e0e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_pictures',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.Column('content_type', sa.String(length=50), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.add_column(
        'users', sa.Column('picture_updated_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'picture_updated_at')
    op.drop_table('user_pictures')
