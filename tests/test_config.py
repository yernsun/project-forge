import json
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from project_forge.config import (
    Locale,
    Profile,
    ProjectState,
    normalize_command_name,
    slugify,
)
from project_forge.identity import CURRENT_STATE_SCHEMA_VERSION, current_template_digest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.compat


def test_noninteractive_defaults_are_fullstack_zh_cn_with_sample() -> None:
    state = ProjectState.create("My App")
    assert state.profile is Profile.FULLSTACK
    assert state.default_locale is Locale.ZH_CN
    assert state.sample is True
    assert state.auth is False
    assert state.evented is False
    assert state.schema_version == CURRENT_STATE_SCHEMA_VERSION == 3
    assert state.template_digest == current_template_digest()
    assert state.project_slug == "my-app"
    assert state.command_name == "my-app"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Content Agent", "content-agent"), ("  API__Worker  ", "api-worker")],
)
def test_command_name_is_normalized(value: str, expected: str) -> None:
    assert normalize_command_name(value) == expected
    assert ProjectState.create("Fixture", command_name=value).command_name == expected


@pytest.mark.parametrize("value", ["", "---", "工程", "a" * 101])
def test_invalid_command_name_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        ProjectState.create("Fixture", command_name=value)


@pytest.mark.parametrize("schema_version", [1, 2])
def test_legacy_state_defaults_to_historical_app_command(schema_version: int) -> None:
    state = ProjectState.model_validate(
        {
            "schema_version": schema_version,
            "template_version": "0.2.0",
            "project_name": "Content Agent",
            "project_slug": "content-agent",
        }
    )
    assert state.command_name == "app"
    assert state.with_current_template_identity().command_name == "content-agent"


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


def test_python_runtime_contracts_target_311_and_locks_match() -> None:
    root_project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    backend_root = ROOT / "src/project_forge/template/backend"
    backend_project = tomllib.loads(
        (backend_root / "pyproject.toml.jinja")
        .read_text(encoding="utf-8")
        .replace("{{ command_name }}", "fixture-command")
    )
    root_lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    backend_lock = tomllib.loads((backend_root / "uv.lock").read_text(encoding="utf-8"))

    for project in (root_project, backend_project):
        assert project["project"]["requires-python"] == ">=3.11"
        assert project["tool"]["ruff"]["target-version"] == "py311"
        assert project["tool"]["mypy"]["python_version"] == "3.11"
    assert root_lock["requires-python"] == ">=3.11"
    assert backend_lock["requires-python"] == ">=3.11"
    assert any(
        dependency.startswith("pip-audit")
        for dependency in root_project["dependency-groups"]["dev"]
    )
    assert any(
        dependency.startswith("pip-audit")
        for dependency in backend_project["dependency-groups"]["dev"]
    )
    assert any(
        dependency.startswith("pytest-cov")
        for dependency in backend_project["dependency-groups"]["dev"]
    )
    assert "pytest>=9.0.3,<10" in root_project["dependency-groups"]["dev"]
    assert "pytest-xdist>=3.8,<4" in root_project["dependency-groups"]["dev"]
    assert "pytest>=9.0.3,<10" in backend_project["dependency-groups"]["dev"]
    assert "pytest-asyncio>=1.3,<2" in backend_project["dependency-groups"]["dev"]
    assert "httpx2>=2.12,<3" in backend_project["dependency-groups"]["dev"]
    root_pytest_options = root_project["tool"]["pytest"]["ini_options"]["addopts"]
    for option in (
        "--cov=project_forge",
        "--cov-branch",
        "--cov-report=term-missing",
        "--cov-fail-under=85",
    ):
        assert option in root_pytest_options
    backend_dockerfile = (backend_root / "Dockerfile.jinja").read_text(encoding="utf-8")
    assert backend_dockerfile.startswith(
        "FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim"
    )
    assert "FROM python:3.13-slim-bookworm AS runtime" in backend_dockerfile
    assert next(
        package["version"] for package in root_lock["package"] if package["name"] == "pytest"
    ).startswith("9.")
    assert next(
        package["version"]
        for package in backend_lock["package"]
        if package["name"] == "pytest-asyncio"
    ).startswith("1.")


def test_frontend_runtime_range_uses_node_22_type_floor_and_node_24_image() -> None:
    frontend = ROOT / "src/project_forge/template/frontend"
    package = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        (frontend / "package-lock.json").read_text(encoding="utf-8")
    )
    locked_root = package_lock["packages"][""]
    locked_node_types = package_lock["packages"]["node_modules/@types/node"]

    assert package["engines"]["node"] == ">=22.13 <23 || >=24 <25"
    assert locked_root["engines"] == package["engines"]
    assert package["devDependencies"]["@types/node"] == "^22.12.0"
    assert locked_root["devDependencies"]["@types/node"] == "^22.12.0"
    assert locked_node_types["version"].startswith("22.")
    assert package["devDependencies"]["eslint"].startswith("^10.")
    assert locked_root["devDependencies"]["eslint"].startswith("^10.")
    assert package["scripts"]["test:coverage"] == "vitest run --coverage"
    assert (frontend / "Dockerfile").read_text(encoding="utf-8").startswith(
        "FROM node:24-bookworm-slim"
    )


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


def test_root_and_packaged_faqs_are_bilingual_and_synchronized() -> None:
    template = ROOT / "src/project_forge/template"
    pairs = (
        (ROOT / "FAQ.md", template / "FAQ.md.jinja"),
        (ROOT / "FAQ.zh-CN.md", template / "FAQ.zh-CN.md.jinja"),
    )

    for root_path, template_path in pairs:
        root_content = root_path.read_text(encoding="utf-8")
        template_content = (
            template_path.read_text(encoding="utf-8")
            .replace("{{ command_name }}", "content-agent")
            .replace("{{ project_slug }}", "PROJECT")
        )
        assert root_content == template_content
        assert root_content.count("```") % 2 == 0
        for marker in (
            "origin_not_allowed",
            "request_validation_failed",
            "APP_ALLOWED_ORIGINS",
            "APP_SESSION_COOKIE_SECURE",
            "FORWARDED_ALLOW_IPS",
            "172.20.0.10",
            "https://172.20.0.10:8443",
            "X-Request-ID",
            "content-agent config check --json",
        ):
            assert marker in root_content
        assert "192.168." not in root_content

    assert "[简体中文](FAQ.zh-CN.md)" in pairs[0][0].read_text(encoding="utf-8")
    assert "[English](FAQ.md)" in pairs[1][0].read_text(encoding="utf-8")

    production_environment = (
        ROOT / "src/project_forge/template/.env.example.jinja"
    ).read_text(encoding="utf-8")
    assert "APP_ALLOWED_ORIGINS=https://172.20.0.10:8443" in production_environment
    assert "APP_ALLOWED_ORIGINS=https://app.example.com" not in production_environment
