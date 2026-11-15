from datetime import datetime
from typing import Annotated, Generic, TypeVar

from fastapi import Path, Query
from pydantic import AfterValidator, AwareDatetime, BaseModel, Field, StringConstraints

T = TypeVar("T")

# SQLite INTEGER is 64-bit signed; larger values raise OverflowError deep in the driver (→ 500).
MAX_DB_ID = 2**63 - 1
MAX_OFFSET = 10**9
MIN_YEAR, MAX_YEAR = 2000, 2100

# Body fields
DbId = Annotated[int, Field(ge=1, le=MAX_DB_ID)]
# Path / query parameters
PathId = Annotated[int, Path(ge=1, le=MAX_DB_ID)]
QueryId = Annotated[int | None, Query(ge=1, le=MAX_DB_ID)]


def _sane_year(dt: datetime) -> datetime:
    # Extreme years overflow when converted to UTC or shifted by a duration.
    if not (MIN_YEAR <= dt.year <= MAX_YEAR):
        raise ValueError(f"El año debe estar entre {MIN_YEAR} y {MAX_YEAR}")
    return dt


SaneDatetime = Annotated[AwareDatetime, AfterValidator(_sane_year)]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class PageParams(BaseModel):
    limit: int = 50
    offset: int = 0


def page_params(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


# Trimmed, non-empty text helpers.
def Text(min_length: int = 1, max_length: int = 120):  # noqa: N802 (type factory)
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)]
