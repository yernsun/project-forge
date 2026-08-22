from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.domain.base import StrictDomainModel


class ItemStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class Item(StrictDomainModel):
    item_id: UUID = Field(description="Stable item ID")
    workspace_id: UUID | None = Field(
        default=None, description="Owning workspace when auth is enabled"
    )
    name: str = Field(min_length=1, max_length=200, description="Display name")
    description: str | None = Field(default=None, max_length=2000, description="Optional details")
    status: ItemStatus = Field(description="Lifecycle status")
    version: int = Field(ge=1, description="Optimistic-lock version")
    created_at: datetime = Field(description="UTC creation timestamp")
    updated_at: datetime = Field(description="UTC last-update timestamp")


class ItemSort(StrEnum):
    CREATED_DESC = "createdAtDesc"
    CREATED_ASC = "createdAtAsc"
    NAME_ASC = "nameAsc"
    NAME_DESC = "nameDesc"


class _Unset:
    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


@dataclass(frozen=True, slots=True)
class ItemFilter:
    """Repository-local search input; `None` means SQL NULL and UNSET means omitted."""

    name: str | _Unset | None = UNSET
    description: str | _Unset | None = UNSET
    status: ItemStatus | _Unset = UNSET
    created_after: datetime | _Unset = UNSET
    sort: ItemSort = ItemSort.CREATED_DESC
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        if self.offset < 0:
            raise ValueError("offset must be non-negative")
