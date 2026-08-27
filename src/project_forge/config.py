from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from project_forge import __version__
from project_forge.identity import CURRENT_STATE_SCHEMA_VERSION, current_template_digest

_UNSAFE_PROJECT_NAME_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


def _reject_unsafe_project_name_characters(value: str) -> None:
    if any(
        unicodedata.category(character) in _UNSAFE_PROJECT_NAME_CATEGORIES
        for character in value
    ):
        raise ValueError("project name must not contain control or line-separator characters")


class Profile(StrEnum):
    FRONTEND = "frontend"
    BACKEND = "backend"
    FULLSTACK = "fullstack"


class Locale(StrEnum):
    ZH_CN = "zh-CN"
    EN_US = "en-US"


class Feature(StrEnum):
    AUTH = "auth"
    EVENTED = "evented"
    SAMPLE = "sample"


class Component(StrEnum):
    FRONTEND = "frontend"
    BACKEND = "backend"


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not normalized:
        raise ValueError("project name must contain at least one ASCII letter or digit")
    return normalized


class ProjectState(BaseModel):
    """Persisted generator answers and enabled capabilities."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=False)

    schema_version: int = Field(
        default=CURRENT_STATE_SCHEMA_VERSION,
        ge=1,
        le=CURRENT_STATE_SCHEMA_VERSION,
        description="State file schema version",
    )
    template_version: str = Field(
        default=__version__, min_length=1, description="Last successfully applied template version"
    )
    template_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
        description="Content identity of the last successfully applied packaged template",
    )
    project_name: str = Field(min_length=1, max_length=100, description="Human-facing name")
    project_slug: str = Field(
        min_length=1, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", description="Filesystem slug"
    )
    profile: Profile = Field(default=Profile.FULLSTACK, description="Generated component profile")
    auth: bool = Field(default=False, description="Enable database-backed session authentication")
    evented: bool = Field(default=False, description="Enable Redis Streams and outbox processing")
    sample: bool = Field(default=True, description="Generate the sample Items vertical slice")
    default_locale: Locale = Field(default=Locale.ZH_CN, description="Default UI locale")

    @field_validator("project_name")
    @classmethod
    def reject_unsafe_project_name_characters(cls, value: str) -> str:
        _reject_unsafe_project_name_characters(value)
        return value

    @model_validator(mode="before")
    @classmethod
    def resolve_profile_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("sample") is not None:
            return data
        resolved = dict(data)
        profile = Profile(resolved.get("profile", Profile.FULLSTACK))
        resolved["sample"] = profile is not Profile.FRONTEND
        return resolved

    @model_validator(mode="after")
    def validate_capabilities(self) -> Self:
        has_backend = self.profile in {Profile.BACKEND, Profile.FULLSTACK}
        if self.auth and not has_backend:
            raise ValueError("auth requires a backend; add backend first")
        if self.evented and not has_backend:
            raise ValueError("evented requires a backend; add backend first")
        return self

    @classmethod
    def create(
        cls,
        project_name: str,
        *,
        project_slug: str | None = None,
        profile: Profile = Profile.FULLSTACK,
        auth: bool = False,
        evented: bool = False,
        sample: bool | None = None,
        default_locale: Locale = Locale.ZH_CN,
    ) -> Self:
        _reject_unsafe_project_name_characters(project_name)
        resolved_sample = sample if sample is not None else profile is not Profile.FRONTEND
        return cls(
            schema_version=CURRENT_STATE_SCHEMA_VERSION,
            template_version=__version__,
            template_digest=current_template_digest(),
            project_name=project_name.strip(),
            project_slug=slugify(project_slug or project_name),
            profile=profile,
            auth=auth,
            evented=evented,
            sample=resolved_sample,
            default_locale=default_locale,
        )

    def copier_data(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def with_current_template_identity(self) -> Self:
        return self.model_copy(
            update={
                "schema_version": CURRENT_STATE_SCHEMA_VERSION,
                "template_version": __version__,
                "template_digest": current_template_digest(),
            }
        )

    @property
    def has_backend(self) -> bool:
        return self.profile in {Profile.BACKEND, Profile.FULLSTACK}

    @property
    def has_frontend(self) -> bool:
        return self.profile in {Profile.FRONTEND, Profile.FULLSTACK}


STATE_FILE = ".project-forge.yml"


def load_state(project_dir: Path) -> ProjectState:
    path = project_dir / STATE_FILE
    if not path.is_file():
        raise ValueError(f"{path} does not exist; this is not a Project Forge project")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ProjectState.model_validate(raw)


def dump_state(state: ProjectState) -> str:
    return yaml.safe_dump(
        state.model_dump(mode="json"), sort_keys=False, allow_unicode=True, default_flow_style=False
    )
