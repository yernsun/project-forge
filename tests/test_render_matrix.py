from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from project_forge.config import Locale, Profile, ProjectState
from project_forge.renderer import render_fresh


def valid_states() -> Iterator[ProjectState]:
    for profile in Profile:
        auth_values = (False,) if profile is Profile.FRONTEND else (False, True)
        event_values = (False,) if profile is Profile.FRONTEND else (False, True)
        for auth in auth_values:
            for evented in event_values:
                for sample in (False, True):
                    for locale in Locale:
                        yield ProjectState.create(
                            f"Fixture {profile.value} {auth} {evented} {sample} {locale.value}",
                            profile=profile,
                            auth=auth,
                            evented=evented,
                            sample=sample,
                            default_locale=locale,
                        )


STATES = tuple(valid_states())


@pytest.mark.parametrize("state", STATES, ids=lambda state: state.project_slug)
def test_every_valid_combination_renders(state: ProjectState, tmp_path: Path) -> None:
    destination = tmp_path / "project"
    render_fresh(state, destination)
    assert (destination / "backend").exists() is state.has_backend
    assert (destination / "frontend").exists() is state.has_frontend
    assert (destination / "backend/src/app/auth").exists() is (state.has_backend and state.auth)
    assert (destination / "backend/src/app/events").exists() is (
        state.has_backend and state.evented
    )
    assert (destination / "backend/src/app/domain/items.py").exists() is (
        state.has_backend and state.sample
    )
    assert (destination / "frontend/src/features/items").exists() is (
        state.has_frontend and state.sample
    )
    assert not (destination / ".project-forge").exists()

    for compose_file in ("docker-compose.dev.yml", "docker-compose.yml"):
        document = yaml.safe_load((destination / compose_file).read_text(encoding="utf-8"))
        assert document["services"]
    workflow = yaml.safe_load(
        (destination / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    assert workflow["jobs"]["validate"]["steps"]

    if state.has_backend:
        for path in (destination / "backend/src").rglob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    if state.has_frontend:
        for locale_name in ("zh-CN.json", "en-US.json"):
            json.loads(
                (destination / "frontend/src/shared/i18n/locales" / locale_name).read_text(
                    encoding="utf-8"
                )
            )


def test_generated_projects_have_no_source_specific_residue(tmp_path: Path) -> None:
    destination = tmp_path / "project"
    render_fresh(
        ProjectState.create("Clean Fixture", auth=True, evented=True),
        destination,
    )
    forbidden = ("TradeComposer", "async" + "pg", "Statement")
    for path in destination.rglob("*"):
        if path.is_dir():
            assert path.name not in {".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        assert not any(token in text for token in forbidden), path
