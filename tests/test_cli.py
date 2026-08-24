from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest
from copier.errors import CopierError
from typer.testing import CliRunner

from project_forge import __version__
from project_forge.cli import app
from project_forge.config import Profile, ProjectState, dump_state, load_state

runner = CliRunner()


def write_baseline(
    path: Path,
    *,
    member_name: str = "README.md",
    member_type: bytes = tarfile.REGTYPE,
) -> None:
    payload = b"fixture" if member_type == tarfile.REGTYPE else b""
    member = tarfile.TarInfo(member_name)
    member.type = member_type
    member.size = len(payload)
    with tarfile.open(path, mode="w:gz") as archive:
        archive.addfile(member, io.BytesIO(payload))


def test_global_version_options() -> None:
    for option in ("--version", "-V"):
        result = runner.invoke(app, [option])
        assert result.exit_code == 0
        assert result.stdout.strip() == __version__


def test_global_help_lists_only_explicit_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("init", "doctor", "features", "add", "enable", "update", "install-skill"):
        assert command in result.stdout


def test_update_check_help_is_explicitly_local() -> None:
    result = runner.invoke(app, ["update", "--help"])

    assert result.exit_code == 0
    assert "installed template" in result.stdout
    assert "remote repository" in result.stdout


def test_python_module_and_console_app_have_equivalent_global_contract() -> None:
    console_help = runner.invoke(app, ["--help"])
    module_help = subprocess.run(
        [sys.executable, "-m", "project_forge", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    module_version = subprocess.run(
        [sys.executable, "-m", "project_forge", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert console_help.exit_code == module_help.returncode == module_version.returncode == 0
    for token in ("--version", "init", "doctor", "add", "enable", "update"):
        assert (token in console_help.stdout) is (token in module_help.stdout)
    assert module_version.stdout.strip() == __version__


def test_init_sample_default_is_profile_aware(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    states: list[ProjectState] = []

    def capture_state(
        state: ProjectState, destination: Path, *, initialize_git: bool = True
    ) -> None:
        del destination, initialize_git
        states.append(state)

    monkeypatch.setattr("project_forge.cli.initialize_project", capture_state)

    frontend_result = runner.invoke(
        app, ["init", str(tmp_path / "frontend"), "--profile", "frontend"]
    )
    backend_result = runner.invoke(app, ["init", str(tmp_path / "backend"), "--profile", "backend"])

    assert frontend_result.exit_code == 0
    assert backend_result.exit_code == 0
    assert [state.sample for state in states] == [False, True]


def test_init_explicit_sample_flags_override_profile_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    states: list[ProjectState] = []

    def capture_state(
        state: ProjectState, destination: Path, *, initialize_git: bool = True
    ) -> None:
        del destination, initialize_git
        states.append(state)

    monkeypatch.setattr("project_forge.cli.initialize_project", capture_state)
    with_sample = runner.invoke(
        app,
        ["init", str(tmp_path / "frontend"), "--profile", "frontend", "--sample"],
    )
    without_sample = runner.invoke(
        app,
        ["init", str(tmp_path / "backend"), "--profile", "backend", "--no-sample"],
    )

    assert with_sample.exit_code == 0
    assert without_sample.exit_code == 0
    assert [state.sample for state in states] == [True, False]


@pytest.mark.parametrize(
    ("profile", "has_backend", "has_frontend", "sample"),
    [
        (Profile.FRONTEND, False, True, False),
        (Profile.BACKEND, True, False, True),
        (Profile.FULLSTACK, True, True, True),
    ],
)
def test_init_really_renders_each_profile(
    profile: Profile,
    has_backend: bool,
    has_frontend: bool,
    sample: bool,
    tmp_path: Path,
) -> None:
    destination = tmp_path / profile.value

    result = runner.invoke(
        app,
        ["init", str(destination), "--profile", profile.value, "--no-git"],
    )

    assert result.exit_code == 0, result.output
    state = load_state(destination)
    assert state.profile is profile
    assert state.sample is sample
    assert (destination / "backend").exists() is has_backend
    assert (destination / "frontend").exists() is has_frontend


def test_init_wraps_copier_error_as_exit_two_without_partial_destination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "copier-failure"

    def fail_copy(*_args: object, **_kwargs: object) -> None:
        raise CopierError("injected Copier failure")

    monkeypatch.setattr("project_forge.renderer.run_copy", fail_copy)
    result = runner.invoke(
        app,
        ["init", str(destination), "--profile", "backend", "--no-sample", "--no-git"],
    )

    assert result.exit_code == 2
    assert "template rendering failed" in result.output
    assert "Traceback" not in result.output
    assert not destination.exists()


def test_init_wraps_git_failure_as_exit_two_without_partial_destination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "git-failure"
    real_run = subprocess.run

    def fail_git_init(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["git", "init"]:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=command,
                stderr="injected Git failure",
            )
        return real_run(command, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr("project_forge.renderer.subprocess.run", fail_git_init)
    result = runner.invoke(
        app,
        ["init", str(destination), "--profile", "backend", "--no-sample"],
    )

    assert result.exit_code == 2
    assert "Git initialization failed" in result.output
    assert "Traceback" not in result.output
    assert not destination.exists()


def test_install_skill_overwrites_normal_directory(tmp_path: Path) -> None:
    destination = tmp_path / "skill"
    destination.mkdir()
    stale = destination / "stale.txt"
    stale.write_text("old", encoding="utf-8")

    result = runner.invoke(
        app,
        ["install-skill", "--destination", str(destination), "--overwrite"],
    )

    assert result.exit_code == 0, result.output
    assert not stale.exists()
    assert (destination / "SKILL.md").is_file()


def test_install_skill_rejects_explicit_symlink_without_deleting_target(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    destination = tmp_path / "skill-link"
    try:
        destination.symlink_to(outside, target_is_directory=True)
    except OSError as error:  # pragma: no cover - platform-specific permission policy
        pytest.skip(f"symlinks are unavailable: {error}")

    result = runner.invoke(
        app,
        ["install-skill", "--destination", str(destination), "--overwrite"],
    )

    assert result.exit_code == 2
    assert "symbolic links or junctions" in result.output
    assert destination.is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert not (outside / "SKILL.md").exists()


def test_install_skill_rejects_explicit_symlink_parent(tmp_path: Path) -> None:
    outside = tmp_path / "outside-parent"
    outside.mkdir()
    linked_parent = tmp_path / "linked-parent"
    try:
        linked_parent.symlink_to(outside, target_is_directory=True)
    except OSError as error:  # pragma: no cover - platform-specific permission policy
        pytest.skip(f"symlinks are unavailable: {error}")
    destination = linked_parent / "skill"

    result = runner.invoke(
        app,
        ["install-skill", "--destination", str(destination), "--overwrite"],
    )

    assert result.exit_code == 2
    assert "symbolic links or junctions" in result.output
    assert linked_parent.is_symlink()
    assert not (outside / "skill").exists()


def test_install_skill_default_repo_scope_rejects_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    skills = repository / ".agents/skills"
    skills.mkdir(parents=True)
    outside = tmp_path / "outside-default"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    destination = skills / "project-forge-init"
    try:
        destination.symlink_to(outside, target_is_directory=True)
    except OSError as error:  # pragma: no cover - platform-specific permission policy
        pytest.skip(f"symlinks are unavailable: {error}")
    monkeypatch.chdir(repository)

    result = runner.invoke(app, ["install-skill", "--overwrite"])

    assert result.exit_code == 2
    assert "symbolic links or junctions" in result.output
    assert destination.is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert not (outside / "SKILL.md").exists()


def check_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assert set(report) == {"ok", "project", "checks"}
    checks = report["checks"]
    assert isinstance(checks, list)
    assert all(
        set(check) == {"name", "status", "required", "version", "message"}
        for check in checks
    )
    assert all(check["status"] in {"pass", "warn", "fail"} for check in checks)
    return {check["name"]: check for check in checks}


def test_doctor_is_profile_aware_and_emits_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "backend"
    project.mkdir()
    state = ProjectState.create("Backend", profile=Profile.BACKEND)
    (project / ".project-forge.yml").write_text(dump_state(state), encoding="utf-8")
    metadata = project / ".project-forge"
    metadata.mkdir()
    write_baseline(metadata / "baseline.tar.gz")
    monkeypatch.setattr("project_forge.cli.git_worktree_status", lambda _: (True, True, None))

    def fake_version(command: str, *arguments: str) -> str | None:
        del arguments
        versions = {
            Path(sys.executable).name: "Python 3.13.1",
            "git": "git version 2.49.0",
            "uv": "uv 0.8.0",
        }
        name = Path(command).name
        return versions.get(name)

    monkeypatch.setattr("project_forge.cli.tool_version", fake_version)
    result = runner.invoke(app, ["doctor", str(project), "--json"])

    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["ok"] is True
    checks = check_map(report)
    assert checks["uv"]["required"] is True
    assert checks["node"]["required"] is False
    assert checks["node"]["status"] == "warn"
    assert checks["docker-cli"]["required"] is False
    assert checks["docker-cli"]["status"] == "warn"
    assert checks["docker-compose"]["status"] == "warn"
    assert checks["docker-daemon"]["status"] == "warn"
    assert checks["project-state"]["status"] == "pass"
    assert checks["update-baseline"]["status"] == "pass"
    assert checks["git-repository"]["status"] == "pass"
    assert checks["git-clean"]["status"] == "pass"


@pytest.mark.parametrize(
    ("python_version", "expected_exit_code", "expected_status"),
    [
        ("Python 3.10.99", 1, "fail"),
        ("Python 3.11.0", 0, "pass"),
        ("Python 3.14.7", 0, "pass"),
    ],
)
def test_doctor_enforces_python_311_floor(
    python_version: str,
    expected_exit_code: int,
    expected_status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_version(command: str, *arguments: str) -> str | None:
        del arguments
        versions = {
            Path(sys.executable).name: python_version,
            "git": "git version 2.49.0",
            "uv": "uv 0.8.0",
            "node": "v24.11.1",
            "npm": "11.6.2",
        }
        return versions.get(Path(command).name)

    monkeypatch.setattr("project_forge.cli.tool_version", fake_version)
    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == expected_exit_code
    python_check = check_map(json.loads(result.stdout))["python"]
    assert python_check["status"] == expected_status
    assert ">=3.11" in python_check["message"]


@pytest.mark.parametrize(
    ("node_version", "expected_exit_code", "expected_status"),
    [
        ("v22.11.99", 1, "fail"),
        ("v22.12.0", 0, "pass"),
        ("v22.99.0", 0, "pass"),
        ("v23.11.1", 0, "pass"),
        ("v24.19.0", 0, "pass"),
        ("v25.9.0", 0, "pass"),
        ("v26.7.0", 0, "pass"),
        ("v27.0.0", 1, "fail"),
    ],
)
def test_doctor_enforces_node_22_12_through_26_runtime_range(
    node_version: str,
    expected_exit_code: int,
    expected_status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_version(command: str, *arguments: str) -> str | None:
        del arguments
        if command == sys.executable:
            return "Python 3.13.1"
        versions = {
            "git": "git version 2.49.0",
            "uv": "uv 0.8.0",
            "node": node_version,
            "npm": "10.9.0",
        }
        return versions.get(Path(command).name)

    monkeypatch.setattr("project_forge.cli.tool_version", fake_version)
    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == expected_exit_code
    node_check = check_map(json.loads(result.stdout))["node"]
    assert node_check["status"] == expected_status
    assert ">=22.12,<27" in node_check["message"]


@pytest.mark.parametrize(
    ("case", "expected_message"),
    [
        ("corrupt", "invalid"),
        ("empty", "empty"),
        ("absolute", "unsafe"),
        ("traversal", "unsafe"),
        ("directory", "not a regular file"),
        ("symlink", "not a regular file"),
        ("hardlink", "not a regular file"),
        ("duplicate", "duplicate"),
        ("conflict", "conflicting"),
    ],
)
def test_doctor_rejects_invalid_update_baseline(
    case: str,
    expected_message: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = tmp_path / "backend"
    project.mkdir()
    state = ProjectState.create("Backend", profile=Profile.BACKEND)
    (project / ".project-forge.yml").write_text(dump_state(state), encoding="utf-8")
    metadata = project / ".project-forge"
    metadata.mkdir()
    baseline = metadata / "baseline.tar.gz"
    if case == "corrupt":
        baseline.write_bytes(b"not a gzip archive")
    elif case == "empty":
        with tarfile.open(baseline, mode="w:gz"):
            pass
    elif case == "absolute":
        write_baseline(baseline, member_name="/outside.txt")
    elif case == "traversal":
        write_baseline(baseline, member_name="../outside.txt")
    elif case == "directory":
        write_baseline(baseline, member_name="directory", member_type=tarfile.DIRTYPE)
    elif case == "symlink":
        write_baseline(baseline, member_name="linked", member_type=tarfile.SYMTYPE)
    elif case == "hardlink":
        write_baseline(baseline, member_name="linked", member_type=tarfile.LNKTYPE)
    else:
        names = ("same.txt", "same.txt") if case == "duplicate" else ("parent", "parent/file")
        with tarfile.open(baseline, mode="w:gz") as archive:
            for name in names:
                payload = b"fixture"
                member = tarfile.TarInfo(name)
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))

    monkeypatch.setattr("project_forge.cli.git_worktree_status", lambda _: (True, True, None))
    result = runner.invoke(app, ["doctor", str(project), "--json"])

    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["ok"] is False
    baseline_check = check_map(report)["update-baseline"]
    assert baseline_check["status"] == "fail"
    assert expected_message in baseline_check["message"]


def test_doctor_returns_one_when_required_tool_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_version(command: str, *arguments: str) -> str | None:
        del arguments
        name = Path(command).name
        if command == sys.executable:
            return "Python 3.13.1"
        if name == "git":
            return "git version 2.49.0"
        return None

    monkeypatch.setattr("project_forge.cli.tool_version", fake_version)
    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["ok"] is False
    checks = check_map(report)
    assert checks["uv"]["status"] == "fail"
    assert checks["node"]["required"] is True


def test_doctor_require_docker_checks_compose_and_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_version(command: str, *arguments: str) -> str | None:
        name = Path(command).name
        if command == sys.executable:
            return "Python 3.13.1"
        if name == "git":
            return "git version 2.49.0"
        if name == "uv":
            return "uv 0.8.0"
        if name == "node":
            return "v22.18.0"
        if name == "npm":
            return "10.9.0"
        if name == "docker" and not arguments:
            return "Docker version 28.0.0"
        if name == "docker" and arguments[:2] == ("compose", "version"):
            return "Docker Compose version v2.39.0"
        return None

    monkeypatch.setattr("project_forge.cli.tool_version", fake_version)
    result = runner.invoke(app, ["doctor", "--json", "--require-docker"])

    assert result.exit_code == 1
    report = json.loads(result.stdout)
    checks = check_map(report)
    assert checks["docker-cli"]["required"] is True
    assert checks["docker-cli"]["status"] == "pass"
    assert checks["docker-compose"]["status"] == "pass"
    assert checks["docker-daemon"]["status"] == "fail"


def test_doctor_invalid_project_reports_failed_checks(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", str(tmp_path), "--json"])
    assert result.exit_code == 1
    checks = check_map(json.loads(result.stdout))
    assert checks["project-state"]["status"] == "fail"
    assert checks["update-baseline"]["status"] == "fail"
    assert checks["git-repository"]["status"] == "fail"
    assert checks["git-clean"]["status"] == "fail"


@pytest.mark.parametrize(
    ("template_version", "expected_code", "expected_output"),
    [
        (__version__, 0, "up to date"),
        ("0.0.0", 1, "update available"),
    ],
)
def test_update_check_compares_with_installed_template_only(
    template_version: str,
    expected_code: int,
    expected_output: str,
    tmp_path: Path,
) -> None:
    project = tmp_path / "check"
    project.mkdir()
    state = ProjectState.create("Check").model_copy(
        update={"template_version": template_version}
    )
    (project / ".project-forge.yml").write_text(dump_state(state), encoding="utf-8")

    result = runner.invoke(app, ["update", str(project), "--check"])

    assert result.exit_code == expected_code
    assert result.stdout.strip() == expected_output


@pytest.mark.parametrize("check", [False, True])
def test_update_refuses_to_downgrade_a_newer_project(check: bool, tmp_path: Path) -> None:
    project = tmp_path / "newer"
    project.mkdir()
    state = ProjectState.create("Newer").model_copy(update={"template_version": "99.0.0"})
    (project / ".project-forge.yml").write_text(dump_state(state), encoding="utf-8")
    arguments = ["update", str(project)]
    if check:
        arguments.append("--check")

    result = runner.invoke(app, arguments)

    assert result.exit_code == 2
    assert "newer than installed" in result.output
    assert "uv tool upgrade project-forge" in result.output


@pytest.mark.parametrize(
    ("profile", "arguments"),
    [
        (Profile.FRONTEND, ["add", "backend"]),
        (Profile.BACKEND, ["enable", "auth"]),
    ],
)
def test_capability_changes_refuse_to_downgrade_a_newer_project(
    profile: Profile, arguments: list[str], tmp_path: Path
) -> None:
    project = tmp_path / "newer"
    project.mkdir()
    state = ProjectState.create("Newer", profile=profile).model_copy(
        update={"template_version": "99.0.0"}
    )
    (project / ".project-forge.yml").write_text(dump_state(state), encoding="utf-8")

    result = runner.invoke(app, [*arguments, "-C", str(project)])

    assert result.exit_code == 2
    assert "newer than installed" in result.output
