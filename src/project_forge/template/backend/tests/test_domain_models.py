from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.items import Item, ItemStatus


def payload() -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "itemId": str(uuid4()),
        "workspaceId": None,
        "name": "Example",
        "description": None,
        "status": "ACTIVE",
        "version": 1,
        "createdAt": now.isoformat(),
        "updatedAt": now.isoformat(),
    }


def test_domain_model_accepts_camel_case_and_dumps_aliases() -> None:
    item = Item.model_validate(payload())
    dumped = item.model_dump(by_alias=True, mode="json")
    assert item.status is ItemStatus.ACTIVE
    assert "itemId" in dumped
    assert "item_id" not in dumped


def test_domain_model_rejects_unknown_fields() -> None:
    data = payload()
    data["surprise"] = True
    with pytest.raises(ValidationError):
        Item.model_validate(data)


def test_domain_model_rejects_naive_timestamps() -> None:
    data = payload()
    data["createdAt"] = "2026-01-01T00:00:00"
    with pytest.raises(ValidationError):
        Item.model_validate(data)
