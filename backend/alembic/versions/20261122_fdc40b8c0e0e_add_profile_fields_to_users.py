"""add profile fields to users

Adds three profile columns to users: name, location and bio (intermediate
backend phase). They are shown on the Profile page and edited in Settings.

All three are nullable at database level:
- location and bio are optional for every account;
- name is required by the API for NEW accounts (registration), but accounts
  created before this migration have no name, and the migration does not
  invent one. Those rows keep NULL until the user sets a name in Settings.

Existing rows and the other tables are not changed. The downgrade drops the
three columns, which only loses the values typed into them.

Revision ID: fdc40b8c0e0e
Revises: 4b9b12262d50
Create Date: 2026-11-22 20:00:39.374173

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fdc40b8c0e0e'
down_revision: Union[str, Sequence[str], None] = '4b9b12262d50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('name', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('location', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('bio', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'bio')
    op.drop_column('users', 'location')
    op.drop_column('users', 'name')
