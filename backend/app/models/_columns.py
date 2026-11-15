"""Shared column helpers."""

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


def enum_col(enum_cls: type[StrEnum], length: int = 20) -> SAEnum:
    """Store the enum *value* as VARCHAR with a CHECK constraint (portable, readable in SQLite)."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        length=length,
        values_callable=lambda e: [m.value for m in e],
        name=enum_cls.__name__.lower(),
        validate_strings=True,
    )
