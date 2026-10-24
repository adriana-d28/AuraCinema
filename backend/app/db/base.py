"""Declarative base class shared by all ORM models."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# A naming convention gives every constraint a predictable name. Alembic needs
# named constraints to generate reliable migrations (especially downgrades),
# and the names make database error messages easier to interpret.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
