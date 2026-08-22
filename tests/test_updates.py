from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path

from project_forge.config import Profile, ProjectState
from project_forge.renderer import apply_controlled_update, initialize_project


def git(project: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True, text=True)


def commit_all(project: Path, message: str) -> None:
    git(project, "add", ".")
    git(
        project,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        message,
    )


def test_monotonic_component_add_preserves_user_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initial = ProjectState.create("Backend App", profile=Profile.BACKEND, sample=False)
    initialize_project(initial, project)
    user_file = project / "notes.md"
    user_file.write_text("user-owned\n", encoding="utf-8")
    commit_all(project, "initial")

    expanded = initial.model_copy(update={"profile": Profile.FULLSTACK})
    conflicts = apply_controlled_update(project, expanded)

    assert conflicts == []
    assert (project / "frontend/package.json").is_file()
    assert user_file.read_text(encoding="utf-8") == "user-owned\n"


def test_double_modified_file_produces_rejection_without_overwrite(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = ProjectState.create("Conflict App", profile=Profile.BACKEND, sample=False)
    initialize_project(state, project)
    commit_all(project, "initial")

    metadata = project / ".project-forge"
    archive = metadata / "baseline.tar.gz"
    extracted = tmp_path / "baseline"
    extracted.mkdir()
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(extracted, filter="data")
    readme = extracted / "README.md"
    original = readme.read_text(encoding="utf-8")
    readme.write_text(original.replace("# Conflict App", "# Old title", 1), encoding="utf-8")
    with tarfile.open(archive, "w:gz") as bundle:
        for path in sorted(extracted.rglob("*")):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(extracted).as_posix())

    project_readme = project / "README.md"
    project_readme.write_text(
        project_readme.read_text(encoding="utf-8").replace("# Conflict App", "# User title", 1),
        encoding="utf-8",
    )
    commit_all(project, "user title")
    conflicts = apply_controlled_update(project, state)

    assert conflicts == [project / "README.md.rej"]
    assert project_readme.read_text(encoding="utf-8").startswith("# User title")
    assert "<<<<<<<" in (project / "README.md.rej").read_text(encoding="utf-8")
