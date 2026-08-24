import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from project_forge.config import Locale, Profile, ProjectState, slugify

ROOT = Path(__file__).resolve().parents[1]


def test_noninteractive_defaults_are_fullstack_zh_cn_with_sample() -> None:
    state = ProjectState.create("My App")
    assert state.profile is Profile.FULLSTACK
    assert state.default_locale is Locale.ZH_CN
    assert state.sample is True
    assert state.auth is False
    assert state.evented is False
    assert state.project_slug == "my-app"


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (Profile.FRONTEND, False),
        (Profile.BACKEND, True),
        (Profile.FULLSTACK, True),
    ],
)
def test_sample_default_is_profile_aware(profile: Profile, expected: bool) -> None:
    assert ProjectState.create("Fixture", profile=profile).sample is expected


@pytest.mark.parametrize("sample", [False, True])
def test_explicit_sample_choice_overrides_profile_default(sample: bool) -> None:
    state = ProjectState.create("Frontend", profile=Profile.FRONTEND, sample=sample)
    assert state.sample is sample


def test_state_validation_resolves_missing_sample_for_frontend() -> None:
    state = ProjectState.model_validate(
        {
            "project_name": "Frontend",
            "project_slug": "frontend",
            "profile": "frontend",
        }
    )
    assert state.sample is False


def test_frontend_runtime_and_types_target_supported_node_22_range() -> None:
    frontend = ROOT / "src/project_forge/template/frontend"
    package = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        (frontend / "package-lock.json").read_text(encoding="utf-8")
    )
    locked_root = package_lock["packages"][""]
    locked_node_types = package_lock["packages"]["node_modules/@types/node"]

    assert package["engines"]["node"] == ">=22.12 <23"
    assert locked_root["engines"] == package["engines"]
    assert package["devDependencies"]["@types/node"] == "^22.12.0"
    assert locked_root["devDependencies"]["@types/node"] == "^22.12.0"
    assert locked_node_types["version"].startswith("22.")


@pytest.mark.parametrize("feature", ["auth", "evented"])
def test_backend_features_are_invalid_for_frontend_only(feature: str) -> None:
    values = {feature: True}
    with pytest.raises(ValidationError, match="requires a backend"):
        ProjectState.create("UI", profile=Profile.FRONTEND, **values)  # type: ignore[arg-type]


def test_slug_rejects_names_without_ascii_identity() -> None:
    with pytest.raises(ValueError):
        slugify("工程")


def test_explicit_slug_supports_non_ascii_display_name() -> None:
    state = ProjectState.create("订单服务", project_slug="order-service")
    assert state.project_name == "订单服务"
    assert state.project_slug == "order-service"


@pytest.mark.parametrize(
    "unsafe_character",
    ["\n", "\r", "\t", "\x00", "\x1f", "\x7f", "\u2028", "\u2029", "\u202e"],
    ids=[
        "lf",
        "cr",
        "tab",
        "nul",
        "unit-separator",
        "delete",
        "line-separator",
        "paragraph-separator",
        "bidi-override",
    ],
)
def test_project_name_rejects_control_and_line_separator_characters(
    unsafe_character: str,
) -> None:
    for value in (f"Unsafe{unsafe_character}Name", f"Unsafe{unsafe_character}"):
        with pytest.raises(ValueError, match="control or line-separator"):
            ProjectState.create(value, project_slug="unsafe-name")
        with pytest.raises(ValidationError, match="control or line-separator"):
            ProjectState.model_validate(
                {
                    "project_name": value,
                    "project_slug": "unsafe-name",
                }
            )
