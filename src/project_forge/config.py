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
_COMMAND_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_COMMAND_NAME_LENGTH = 100


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


def normalize_command_name(value: str) -> str:
    """Normalize and validate a generated console command name."""

    normalized = slugify(value)
    if len(normalized) > MAX_COMMAND_NAME_LENGTH:
        raise ValueError(
            f"command name must be at most {MAX_COMMAND_NAME_LENGTH} characters"
        )
    if _COMMAND_NAME_PATTERN.fullmatch(normalized) is None:  # pragma: no cover - slugify invariant
        raise ValueError("command name must use lowercase ASCII letters, digits, and hyphens")
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
    command_name: str = Field(
        min_length=1,
        max_length=MAX_COMMAND_NAME_LENGTH,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="Generated backend console command",
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

    @field_validator("command_name", mode="before")
    @classmethod
    def normalize_persisted_command_name(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("command name must be a string")
        return normalize_command_name(value)

    @model_validator(mode="before")
    @classmethod
    def resolve_profile_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        resolved = dict(data)
        schema_version = int(resolved.get("schema_version", CURRENT_STATE_SCHEMA_VERSION))
        if resolved.get("command_name") is None:
            # Schema v1/v2 generated the fixed `app` console command. Keeping that
            # identity while loading lets update --check report the v3 rename.
            resolved["command_name"] = (
                "app" if schema_version < 3 else resolved.get("project_slug")
            )
        if resolved.get("sample") is not None:
            return resolved
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
        command_name: str | None = None,
        profile: Profile = Profile.FULLSTACK,
        auth: bool = False,
        evented: bool = False,
        sample: bool | None = None,
        default_locale: Locale = Locale.ZH_CN,
    ) -> Self:
        _reject_unsafe_project_name_characters(project_name)
        resolved_sample = sample if sample is not None else profile is not Profile.FRONTEND
        resolved_slug = slugify(project_slug or project_name)
        return cls(
            schema_version=CURRENT_STATE_SCHEMA_VERSION,
            template_version=__version__,
            template_digest=current_template_digest(),
            project_name=project_name.strip(),
            project_slug=resolved_slug,
            command_name=normalize_command_name(
                resolved_slug if command_name is None else command_name
            ),
            profile=profile,
            auth=auth,
            evented=evented,
            sample=resolved_sample,
            default_locale=default_locale,
        )

    def copier_data(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def with_current_template_identity(self, *, command_name: str | None = None) -> Self:
        """Return the state rendered by the installed template.

        Schema v1/v2 projects used the fixed `app` command. Any mutating
        Project Forge operation deliberately migrates them to the project slug.
        """

        target_command = command_name
        if target_command is None:
            target_command = self.project_slug if self.schema_version < 3 else self.command_name
        return type(self).model_validate(
            self.model_copy(
                update={
                    "schema_version": CURRENT_STATE_SCHEMA_VERSION,
                    "template_version": __version__,
                    "template_digest": current_template_digest(),
                    "command_name": normalize_command_name(target_command),
                }
            ).model_dump()
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
