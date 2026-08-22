from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.base import to_camel


class StrictApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )
