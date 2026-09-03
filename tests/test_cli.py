from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path
from typing import Any

import pytest
from copier.errors import CopierError
from typer.testing import CliRunner

from project_forge import __version__, renderer
from project_forge.cli import app
from project_forge.config import Profile, ProjectState, dump_state, load_state
from project_forge.identity import current_template_digest
from project_forge.renderer import initialize_project

runner = CliRunner()
ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
pytestmark = pytest.mark.compat


def commit_project(project: Path, message: str = "fixture") -> None:
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            message,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


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
    for command in (
        "init",
        "doctor",
        "features",
        "add",
        "enable",
        "configure",
        "update",
        "install-skill",
    ):
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
    # Rich may wrap an option name between characters when the Windows runner reports
    # a narrow terminal. Compare unstyled, whitespace-free help so display wrapping
    # cannot make the console entry point appear to have a different contract.
    console_contract = "".join(ANSI_ESCAPE.sub("", console_help.stdout).split())
    module_contract = "".join(ANSI_ESCAPE.sub("", module_help.stdout).split())
    for token in ("--version", "init", "doctor", "add", "enable", "update"):
        assert token in console_contract
        assert token in module_contract
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
    assert state.command_name == profile.value
    assert (destination / "backend").exists() is has_backend
    assert (destination / "frontend").exists() is has_frontend


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [([], "content-agent"), (["--command-name", "Content Agent CLI"], "content-agent-cli")],
    ids=("slug-default", "explicit-normalized"),
)
def test_init_generates_default_and_custom_console_commands(
    arguments: list[str], expected: str, tmp_path: Path
) -> None:
    destination = tmp_path / "content-agent"
    result = runner.invoke(
        app,
        [
            "init",
            str(destination),
            "--name",
            "Content Agent",
            "--profile",
            "backend",
            "--no-sample",
            "--no-git",
            *arguments,
        ],
    )

    assert result.exit_code == 0, result.output
    assert load_state(destination).command_name == expected
    backend_project = tomllib.loads(
        (destination / "backend/pyproject.toml").read_text(encoding="utf-8")
    )
    assert backend_project["project"]["scripts"] == {expected: "app.cli:main"}
    assert backend_project["tool"]["fastapi"]["entrypoint"] == "app.main:app"


@pytest.mark.parametrize("command_name", ["", "---", "工程", "a" * 101])
def test_init_rejects_invalid_command_names(command_name: str, tmp_path: Path) -> None:
    destination = tmp_path / "invalid"
    result = runner.invoke(
        app,
        ["init", str(destination), "--command-name", command_name, "--no-git"],
    )

    assert result.exit_code == 2
    assert "command" in result.output.lower() or "ASCII" in result.output
    assert not destination.exists()


def test_frontend_can_preconfigure_command_before_adding_backend(tmp_path: Path) -> None:
    project = tmp_path / "frontend"
    initialized = runner.invoke(
        app,
        ["init", str(project), "--profile", "frontend"],
    )
    assert initialized.exit_code == 0, initialized.output
    commit_project(project, "frontend")

    configured = runner.invoke(
        app, ["configure", "--command-name", "Content CLI", "-C", str(project)]
    )
    assert configured.exit_code == 0, configured.output
    assert load_state(project).command_name == "content-cli"
    assert not (project / "backend").exists()
    commit_project(project, "preconfigure command")
    added = runner.invoke(app, ["add", "backend", "-C", str(project)])

    assert added.exit_code == 0, added.output
    backend_project = tomllib.loads(
        (project / "backend/pyproject.toml").read_text(encoding="utf-8")
    )
    assert backend_project["project"]["scripts"] == {"content-cli": "app.cli:main"}


def test_configure_renames_command_and_second_run_is_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "service"
    initialized = runner.invoke(
        app,
        ["init", str(project), "--profile", "backend", "--no-sample"],
    )
    assert initialized.exit_code == 0, initialized.output
    commit_project(project, "initial")

    configured = runner.invoke(
        app, ["configure", "--command-name", "Service Operator", "-C", str(project)]
    )
    assert configured.exit_code == 0, configured.output
    assert load_state(project).command_name == "service-operator"
    scripts = tomllib.loads(
        (project / "backend/pyproject.toml").read_text(encoding="utf-8")
    )["project"]["scripts"]
    assert scripts == {"service-operator": "app.cli:main"}
    commit_project(project, "configure")
    baseline = (project / ".project-forge/baseline.tar.gz").read_bytes()

    repeated = runner.invoke(
        app, ["configure", "--command-name", "service-operator", "-C", str(project)]
    )
    assert repeated.exit_code == 0, repeated.output
    assert "up to date" in repeated.output
    assert (project / ".project-forge/baseline.tar.gz").read_bytes() == baseline
    status = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""


def test_configure_requires_clean_git(tmp_path: Path) -> None:
    project = tmp_path / "dirty"
    initialize_project(ProjectState.create("Dirty", profile=Profile.FRONTEND), project)
    commit_project(project)
    (project / "notes.md").write_text("dirty\n", encoding="utf-8")

    result = runner.invoke(
        app, ["configure", "--command-name", "new-command", "-C", str(project)]
    )

    assert result.exit_code == 2
    assert "uncommitted or untracked" in result.output


def test_configure_rejects_invalid_command_without_mutation(tmp_path: Path) -> None:
    project = tmp_path / "invalid-configure"
    initialize_project(ProjectState.create("Invalid Configure", profile=Profile.FRONTEND), project)
    commit_project(project)
    state_before = (project / ".project-forge.yml").read_bytes()
    baseline_before = (project / ".project-forge/baseline.tar.gz").read_bytes()

    result = runner.invoke(
        app, ["configure", "--command-name", "---", "-C", str(project)]
    )

    assert result.exit_code == 2
    assert (project / ".project-forge.yml").read_bytes() == state_before
    assert (project / ".project-forge/baseline.tar.gz").read_bytes() == baseline_before


def test_configure_conflict_writes_only_rejection(tmp_path: Path) -> None:
    project = tmp_path / "configure-conflict"
    state = ProjectState.create(
        "Configure Conflict", profile=Profile.BACKEND, sample=False
    )
    initialize_project(state, project)
    relative = Path("backend/pyproject.toml")
    extracted = tmp_path / "baseline"
    extracted.mkdir()
    renderer._extract_baseline(project, extracted)
    original = f'"{state.command_name}" = "app.cli:main"'
    (extracted / relative).write_text(
        (extracted / relative)
        .read_text(encoding="utf-8")
        .replace(original, '"baseline-command" = "app.cli:main"'),
        encoding="utf-8",
    )
    renderer._write_baseline(extracted, project)
    (project / relative).write_text(
        (project / relative)
        .read_text(encoding="utf-8")
        .replace(original, '"user-command" = "app.cli:main"'),
        encoding="utf-8",
    )
    commit_project(project)
    state_before = (project / ".project-forge.yml").read_bytes()
    baseline_before = (project / ".project-forge/baseline.tar.gz").read_bytes()

    result = runner.invoke(
        app, ["configure", "--command-name", "target-command", "-C", str(project)]
    )

    assert result.exit_code == 3
    assert (project / relative).read_text(encoding="utf-8").find("user-command") >= 0
    assert (project / ".project-forge.yml").read_bytes() == state_before
    assert (project / ".project-forge/baseline.tar.gz").read_bytes() == baseline_before
    rejections = list(project.rglob("*.rej"))
    assert len(rejections) == 1
    assert rejections[0] == project / "backend/pyproject.toml.rej"


@pytest.mark.parametrize(
    ("arguments", "expected_command"),
    [
        (["add", "frontend"], "legacy-operation"),
        (["enable", "sample"], "legacy-operation"),
        (["configure", "--command-name", "Operator CLI"], "operator-cli"),
    ],
    ids=("add", "enable", "configure"),
)
def test_each_mutating_operation_migrates_legacy_command_state(
    arguments: list[str], expected_command: str, tmp_path: Path
) -> None:
    project = tmp_path / "legacy-operation"
    initialize_project(
        ProjectState.create("Legacy Operation", profile=Profile.BACKEND, sample=False),
        project,
    )
    state_path = project / ".project-forge.yml"
    lines = [
        "schema_version: 2" if line.startswith("schema_version:") else line
        for line in state_path.read_text(encoding="utf-8").splitlines()
        if not line.startswith("command_name:")
    ]
    state_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    commit_project(project)

    result = runner.invoke(app, [*arguments, "-C", str(project)])

    assert result.exit_code == 0, result.output
    migrated = load_state(project)
    assert migrated.schema_version == 3
    assert migrated.command_name == expected_command


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
        ("v22.12.99", 1, "fail"),
        ("v22.13.0", 0, "pass"),
        ("v22.99.0", 0, "pass"),
        ("v23.11.1", 1, "fail"),
        ("v24.19.0", 0, "pass"),
        ("v25.9.0", 1, "fail"),
        ("v26.7.0", 1, "fail"),
        ("v27.0.0", 1, "fail"),
    ],
)
def test_doctor_enforces_supported_node_lts_runtime_ranges(
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
    assert ">=22.13,<23 || >=24,<25 (LTS only)" in node_check["message"]


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
    state = ProjectState.create("Check")
    initialize_project(state, project)
    state = load_state(project).model_copy(update={"template_version": template_version})
    (project / ".project-forge.yml").write_text(dump_state(state), encoding="utf-8")
    commit_project(project)

    result = runner.invoke(app, ["update", str(project), "--check"])

    assert result.exit_code == expected_code
    assert expected_output in result.stdout


def test_update_json_has_stable_sorted_shape_for_check_and_apply(tmp_path: Path) -> None:
    project = tmp_path / "json-result"
    initialize_project(ProjectState.create("JSON Result"), project)
    commit_project(project)
    expected_keys = {
        "status",
        "project",
        "target_template_version",
        "target_template_digest",
        "identity_changed",
        "changed_paths",
        "conflict_paths",
        "rejection_paths",
        "breaking_changes",
    }

    checked = runner.invoke(app, ["update", str(project), "--check", "--json"])
    assert checked.exit_code == 0, checked.output
    check_report = json.loads(checked.stdout)
    assert set(check_report) == expected_keys
    assert check_report["status"] == "up_to_date"
    assert check_report["project"] == str(project)
    assert check_report["changed_paths"] == []

    state_path = project / ".project-forge.yml"
    state = load_state(project).model_copy(update={"template_digest": f"sha256:{'0' * 64}"})
    state_path.write_text(dump_state(state), encoding="utf-8")
    commit_project(project, "old identity")
    applied = runner.invoke(app, ["update", str(project), "--json"])

    assert applied.exit_code == 0, applied.output
    apply_report = json.loads(applied.stdout)
    assert set(apply_report) == expected_keys
    assert apply_report["status"] == "updated"
    assert apply_report["identity_changed"] is True
    assert apply_report["changed_paths"] == sorted(apply_report["changed_paths"])
    assert ".project-forge.yml" in apply_report["changed_paths"]


def test_update_json_runtime_error_keeps_machine_readable_shape(tmp_path: Path) -> None:
    project = tmp_path / "json-error"
    initialize_project(ProjectState.create("JSON Error"), project)
    commit_project(project)
    (project / "notes.md").write_text("dirty\n", encoding="utf-8")

    result = runner.invoke(app, ["update", str(project), "--json"])

    assert result.exit_code == 2
    report = json.loads(result.stdout)
    assert report["status"] == "error"
    assert report["project"] == str(project)
    assert report["changed_paths"] == []
    assert report["conflict_paths"] == []
    assert report["rejection_paths"] == []
    assert report["breaking_changes"] == []
    assert "uncommitted or untracked" in report["message"]


def test_update_check_detects_same_version_template_digest_without_mutation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "digest-check"
    initialize_project(ProjectState.create("Digest Check"), project)
    state_path = project / ".project-forge.yml"
    state = load_state(project).model_copy(update={"template_digest": f"sha256:{'0' * 64}"})
    state_path.write_text(dump_state(state), encoding="utf-8")
    commit_project(project)
    baseline_before = (project / ".project-forge/baseline.tar.gz").read_bytes()

    result = runner.invoke(app, ["update", str(project), "--check"])

    assert result.exit_code == 1
    assert "update available" in result.stdout
    assert load_state(project).template_digest == f"sha256:{'0' * 64}"
    assert (project / ".project-forge/baseline.tar.gz").read_bytes() == baseline_before
    assert not list(project.rglob("*.rej"))

    applied = runner.invoke(app, ["update", str(project)])
    assert applied.exit_code == 0, applied.output
    assert load_state(project).template_digest == current_template_digest()


@pytest.mark.parametrize("schema_version", [1, 2])
def test_update_migrates_legacy_state_and_hard_switches_app_command(
    schema_version: int,
    tmp_path: Path,
) -> None:
    project = tmp_path / "legacy-state"
    initialize_project(ProjectState.create("Legacy State"), project)
    state_path = project / ".project-forge.yml"
    legacy_lines = [
        f"schema_version: {schema_version}" if line.startswith("schema_version:") else line
        for line in state_path.read_text(encoding="utf-8").splitlines()
        if not line.startswith(("template_digest:", "command_name:"))
    ]
    legacy_lines = [
        "template_version: 0.2.0" if line.startswith("template_version:") else line
        for line in legacy_lines
    ]
    state_path.write_text("\n".join(legacy_lines) + "\n", encoding="utf-8")
    extracted = tmp_path / f"legacy-baseline-{schema_version}"
    extracted.mkdir()
    renderer._extract_baseline(project, extracted)
    relative = Path("backend/pyproject.toml")
    for root in (project, extracted):
        path = root / relative
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                '"legacy-state" = "app.cli:main"',
                'app = "app.cli:main"',
            ),
            encoding="utf-8",
        )
    renderer._write_baseline(extracted, project)
    user_script = project / "deploy.sh"
    user_script.write_text("uv run app migrate up\n", encoding="utf-8")
    commit_project(project)

    legacy = load_state(project)
    assert legacy.schema_version == schema_version
    assert legacy.template_version == "0.2.0"
    assert legacy.template_digest is None
    assert legacy.command_name == "app"

    preview = runner.invoke(app, ["update", str(project), "--check", "--json"])
    assert preview.exit_code == 1
    report = json.loads(preview.stdout)
    assert report["status"] == "update_available"
    assert report["breaking_changes"] == [
        {"code": "generated_command_renamed", "from": "app", "to": "legacy-state"}
    ]
    assert report["changed_paths"] == sorted(report["changed_paths"])
    assert load_state(project).schema_version == schema_version
    assert load_state(project).template_digest is None

    applied = runner.invoke(app, ["update", str(project)])
    assert applied.exit_code == 0, applied.output
    upgraded = load_state(project)
    assert upgraded.schema_version == 3
    assert upgraded.template_version == "0.3.0"
    assert upgraded.template_digest == current_template_digest()
    assert upgraded.command_name == "legacy-state"
    backend_project = (project / relative).read_text(encoding="utf-8")
    assert '"legacy-state" = "app.cli:main"' in backend_project
    assert '\napp = "app.cli:main"' not in backend_project
    assert user_script.read_text(encoding="utf-8") == "uv run app migrate up\n"


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
