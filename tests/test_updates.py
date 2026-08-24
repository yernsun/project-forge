from __future__ import annotations

import io
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from project_forge import renderer
from project_forge.cli import app
from project_forge.config import Profile, ProjectState, load_state
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


def rewrite_baseline_file(
    project: Path,
    extracted: Path,
    relative: Path,
    content: bytes,
    mode: int,
) -> None:
    archive = project / ".project-forge/baseline.tar.gz"
    extracted.mkdir()
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(extracted, filter="data")
    target = extracted / relative
    target.write_bytes(content)
    target.chmod(mode)
    with tarfile.open(archive, "w:gz") as bundle:
        for path in sorted(extracted.rglob("*")):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(extracted).as_posix())


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


def test_frontend_to_backend_to_auth_evolution_updates_state_and_baseline(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    cli = CliRunner()
    initialized = cli.invoke(
        app,
        [
            "init",
            str(project),
            "--name",
            "Evolution App",
            "--profile",
            "frontend",
        ],
    )
    assert initialized.exit_code == 0, initialized.output
    user_file = project / "notes.md"
    user_file.write_text("user-owned\n", encoding="utf-8")
    commit_all(project, "frontend baseline")

    added = cli.invoke(app, ["add", "backend", "-C", str(project)])
    assert added.exit_code == 0, added.output
    assert (project / "backend/src/app/main.py").is_file()
    assert not (project / "backend/src/app/auth").exists()
    assert load_state(project).profile is Profile.FULLSTACK
    assert user_file.read_text(encoding="utf-8") == "user-owned\n"
    commit_all(project, "add backend")

    enabled = cli.invoke(app, ["enable", "auth", "-C", str(project)])
    assert enabled.exit_code == 0, enabled.output
    state = load_state(project)
    assert state.profile is Profile.FULLSTACK
    assert state.auth is True
    assert (project / "backend/src/app/auth/api.py").is_file()
    assert (project / "frontend/src/features/auth/AuthPanel.vue").is_file()
    assert user_file.read_text(encoding="utf-8") == "user-owned\n"

    with tarfile.open(project / ".project-forge/baseline.tar.gz", "r:gz") as bundle:
        managed = set(bundle.getnames())
    assert "backend/src/app/auth/api.py" in managed
    assert "frontend/src/features/auth/AuthPanel.vue" in managed
    assert "notes.md" not in managed


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
    result = CliRunner().invoke(app, ["update", str(project)])

    assert result.exit_code == 3
    assert "current files were preserved" in result.output
    assert project_readme.read_text(encoding="utf-8").startswith("# User title")
    assert "<<<<<<<" in (project / "README.md.rej").read_text(encoding="utf-8")


def test_conflict_preflight_does_not_apply_other_planned_changes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = ProjectState.create("Atomic App", profile=Profile.BACKEND, sample=False)
    initialize_project(state, project)
    commit_all(project, "initial")

    archive = project / ".project-forge/baseline.tar.gz"
    extracted = tmp_path / "baseline"
    extracted.mkdir()
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(extracted, filter="data")

    baseline_readme = extracted / "README.md"
    baseline_readme.write_text(
        baseline_readme.read_text(encoding="utf-8").replace("# Atomic App", "# Old title", 1),
        encoding="utf-8",
    )
    baseline_agents = extracted / "AGENTS.md"
    old_agents = baseline_agents.read_text(encoding="utf-8") + "\nold baseline marker\n"
    baseline_agents.write_text(old_agents, encoding="utf-8")
    with tarfile.open(archive, "w:gz") as bundle:
        for path in sorted(extracted.rglob("*")):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(extracted).as_posix())

    project_readme = project / "README.md"
    project_readme.write_text(
        project_readme.read_text(encoding="utf-8").replace("# Atomic App", "# User title", 1),
        encoding="utf-8",
    )
    project_agents = project / "AGENTS.md"
    project_agents.write_text(old_agents, encoding="utf-8")
    commit_all(project, "user changes")
    baseline_before = archive.read_bytes()
    state_file = project / ".project-forge.yml"
    state_before = state_file.read_bytes()

    conflicts = apply_controlled_update(project, state)

    assert conflicts == [project / "README.md.rej"]
    assert project_readme.read_text(encoding="utf-8").startswith("# User title")
    assert project_agents.read_text(encoding="utf-8") == old_agents
    assert archive.read_bytes() == baseline_before
    assert state_file.read_bytes() == state_before
    status = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout.strip() == ""
    assert (project / "README.md.rej").is_file()


def test_update_applies_template_mode_only_change(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = ProjectState.create("Mode App", profile=Profile.BACKEND, sample=False)
    initialize_project(state, project)
    target = project / "backend/src/app/cli.py"
    expected_mode = stat.S_IMODE(target.stat().st_mode)
    legacy_mode = expected_mode ^ stat.S_IXUSR

    archive = project / ".project-forge/baseline.tar.gz"
    extracted = tmp_path / "mode-baseline"
    extracted.mkdir()
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(extracted, filter="data")
    baseline_target = extracted / target.relative_to(project)
    baseline_target.chmod(legacy_mode)
    target.chmod(legacy_mode)
    with tarfile.open(archive, "w:gz") as bundle:
        for path in sorted(extracted.rglob("*")):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(extracted).as_posix())
    commit_all(project, "legacy executable mode")

    assert apply_controlled_update(project, state) == []
    assert stat.S_IMODE(target.stat().st_mode) == expected_mode


@pytest.mark.parametrize(
    ("old_mode", "current_mode", "new_mode", "expected_mode"),
    [
        (0o644, 0o644, 0o755, 0o755),
        (0o644, 0o755, 0o644, 0o755),
        (0o644, 0o755, 0o755, 0o755),
    ],
    ids=("template-only", "project-only", "same-change"),
)
def test_update_three_way_merges_content_and_compatible_modes(
    old_mode: int,
    current_mode: int,
    new_mode: int,
    expected_mode: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    state = ProjectState.create("Mode Merge", profile=Profile.BACKEND, sample=False)
    initialize_project(state, project)
    relative = Path("AGENTS.md")
    target = project / relative
    old_content = b"first\nshared\nlast\n"
    current_content = b"first\nproject addition\nshared\nlast\n"
    new_content = b"first\nshared\ntemplate addition\nlast\n"
    rewrite_baseline_file(
        project,
        tmp_path / "baseline-edit",
        relative,
        old_content,
        old_mode,
    )
    target.write_bytes(current_content)
    target.chmod(current_mode)
    commit_all(project, "project content and mode")

    original_render = renderer.render_fresh

    def render_changed(render_state: ProjectState, destination: Path) -> None:
        original_render(render_state, destination)
        rendered_target = destination / relative
        rendered_target.write_bytes(new_content)
        rendered_target.chmod(new_mode)

    monkeypatch.setattr(renderer, "render_fresh", render_changed)

    assert apply_controlled_update(project, state) == []
    merged = target.read_bytes()
    assert b"project addition" in merged
    assert b"template addition" in merged
    assert stat.S_IMODE(target.stat().st_mode) == expected_mode


def test_update_mode_conflict_writes_only_rejection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    state = ProjectState.create("Mode Conflict", profile=Profile.BACKEND, sample=False)
    initialize_project(state, project)
    relative = Path("AGENTS.md")
    target = project / relative
    old_content = b"first\nshared\nlast\n"
    current_content = b"first\nproject addition\nshared\nlast\n"
    new_content = b"first\nshared\ntemplate addition\nlast\n"
    rewrite_baseline_file(
        project,
        tmp_path / "baseline-edit",
        relative,
        old_content,
        0o644,
    )
    target.write_bytes(current_content)
    target.chmod(0o600)
    commit_all(project, "project mode")
    readme = project / "README.md"
    readme_before = readme.read_bytes()
    state_path = project / ".project-forge.yml"
    state_before = state_path.read_bytes()
    baseline_path = project / ".project-forge/baseline.tar.gz"
    baseline_before = baseline_path.read_bytes()

    original_render = renderer.render_fresh

    def render_changed(render_state: ProjectState, destination: Path) -> None:
        original_render(render_state, destination)
        rendered_target = destination / relative
        rendered_target.write_bytes(new_content)
        rendered_target.chmod(0o755)
        rendered_readme = destination / "README.md"
        rendered_readme.write_bytes(rendered_readme.read_bytes() + b"template update\n")

    monkeypatch.setattr(renderer, "render_fresh", render_changed)

    conflicts = apply_controlled_update(project, state)

    assert conflicts == [project / "AGENTS.md.rej"]
    assert "file mode changed differently" in conflicts[0].read_text(encoding="utf-8")
    assert target.read_bytes() == current_content
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert readme.read_bytes() == readme_before
    assert state_path.read_bytes() == state_before
    assert baseline_path.read_bytes() == baseline_before


def test_update_does_not_scan_user_owned_project_trees(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    state = ProjectState.create("Fast Update", profile=Profile.BACKEND, sample=False)
    initialize_project(state, project)
    ignored = project / "backend/.venv/deep/cache"
    ignored.mkdir(parents=True)
    (ignored / "large-user-file").write_text("user-owned", encoding="utf-8")
    commit_all(project, "initial with ignored environment")

    original = renderer._managed_files

    def reject_project_scan(root: Path) -> list[Path]:
        if root == project:
            raise AssertionError("the update engine scanned the user project")
        return original(root)

    monkeypatch.setattr(renderer, "_managed_files", reject_project_scan)
    assert apply_controlled_update(project, state) == []


def test_update_rejects_managed_file_symlink_without_touching_target(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = ProjectState.create("Symlink App", profile=Profile.BACKEND, sample=False)
    initialize_project(state, project)
    target = project / "README.md"
    external = tmp_path / "outside.md"
    external.write_text("outside must not change\n", encoding="utf-8")
    target.unlink()
    try:
        target.symlink_to(external)
    except OSError as error:  # pragma: no cover - platform-specific permission policy
        pytest.skip(f"symlinks are unavailable: {error}")
    commit_all(project, "managed file symlink")

    conflicts = apply_controlled_update(project, state)

    assert conflicts == [project / "README.md.rej"]
    assert target.is_symlink()
    assert external.read_text(encoding="utf-8") == "outside must not change\n"
    assert "managed paths must be regular files" in conflicts[0].read_text(encoding="utf-8")


def test_update_writes_parent_symlink_conflicts_inside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = ProjectState.create("Parent Link", profile=Profile.BACKEND, sample=False)
    initialize_project(state, project)
    services = project / "backend/src/app/services"
    external = tmp_path / "outside-services"
    services.rename(external)
    try:
        services.symlink_to(external, target_is_directory=True)
    except OSError as error:  # pragma: no cover - platform-specific permission policy
        pytest.skip(f"symlinks are unavailable: {error}")
    sentinel = external / "sentinel.txt"
    sentinel.write_text("outside must not change\n", encoding="utf-8")
    commit_all(project, "managed parent symlink")

    conflicts = apply_controlled_update(project, state)

    assert conflicts
    assert all(conflict.parent == project and conflict.suffix == ".rej" for conflict in conflicts)
    assert sentinel.read_text(encoding="utf-8") == "outside must not change\n"


@pytest.mark.parametrize("case", ["corrupt", "empty", "unsafe"])
def test_update_reports_invalid_baseline_as_runtime_error(case: str, tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = ProjectState.create("Bad Baseline", profile=Profile.BACKEND, sample=False)
    initialize_project(state, project)
    archive = project / ".project-forge/baseline.tar.gz"
    if case == "corrupt":
        archive.write_bytes(b"not a gzip archive")
    elif case == "empty":
        with tarfile.open(archive, "w:gz"):
            pass
    else:
        payload = b"must not escape"
        member = tarfile.TarInfo("../outside.txt")
        member.size = len(payload)
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.addfile(member, io.BytesIO(payload))
    commit_all(project, f"{case} baseline")

    result = CliRunner().invoke(app, ["update", str(project)])

    assert result.exit_code == 2
    assert "baseline" in result.output.lower()
    assert not (tmp_path / "outside.txt").exists()


def test_update_staging_failure_leaves_project_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    initial = ProjectState.create("Staging Failure", profile=Profile.BACKEND, sample=False)
    initialize_project(initial, project)
    commit_all(project, "initial")
    state_path = project / ".project-forge.yml"
    baseline_path = project / ".project-forge/baseline.tar.gz"
    state_before = state_path.read_bytes()
    baseline_before = baseline_path.read_bytes()

    def fail_baseline(_rendered: Path, _project_dir: Path) -> None:
        raise OSError("injected baseline staging failure")

    monkeypatch.setattr(renderer, "_write_baseline", fail_baseline)
    expanded = initial.model_copy(update={"profile": Profile.FULLSTACK})

    with pytest.raises(OSError, match="injected baseline"):
        apply_controlled_update(project, expanded)
    assert not (project / "frontend").exists()
    assert state_path.read_bytes() == state_before
    assert baseline_path.read_bytes() == baseline_before


@pytest.mark.parametrize("failure_point", ["second-write", "baseline-replace"])
def test_update_io_failure_rolls_back_files_state_and_baseline(
    failure_point: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    initial = ProjectState.create("Rollback App", profile=Profile.BACKEND, sample=False)
    initialize_project(initial, project)
    commit_all(project, "initial")
    state_path = project / ".project-forge.yml"
    baseline_path = project / ".project-forge/baseline.tar.gz"
    state_before = state_path.read_bytes()
    baseline_before = baseline_path.read_bytes()
    original_write = renderer._atomic_write_bytes
    calls = 0
    failed = False

    def fail_once(path: Path, content: bytes, mode: int) -> None:
        nonlocal calls, failed
        calls += 1
        should_fail = (
            failure_point == "second-write" and calls == 2
        ) or (
            failure_point == "baseline-replace" and path == baseline_path
        )
        if should_fail and not failed:
            failed = True
            raise OSError(f"injected {failure_point}")
        original_write(path, content, mode)

    monkeypatch.setattr(renderer, "_atomic_write_bytes", fail_once)
    expanded = initial.model_copy(update={"profile": Profile.FULLSTACK})

    with pytest.raises(OSError, match=failure_point):
        apply_controlled_update(project, expanded)
    assert failed
    assert not (project / "frontend").exists()
    assert state_path.read_bytes() == state_before
    assert baseline_path.read_bytes() == baseline_before
    status = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout.strip() == ""
