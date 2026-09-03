from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Literal, TypedDict

import typer
from packaging.version import InvalidVersion, Version
from pydantic import ValidationError

from project_forge import __version__
from project_forge.config import (
    Component,
    Feature,
    Locale,
    Profile,
    ProjectState,
    load_state,
    normalize_command_name,
)
from project_forge.identity import current_template_digest
from project_forge.renderer import (
    BASELINE_FILE,
    METADATA_DIR,
    ProjectForgeError,
    UpdateResult,
    apply_controlled_update,
    copy_skill,
    git_worktree_status,
    initialize_project,
    preview_controlled_update,
    tool_version,
    validate_baseline,
)

app = typer.Typer(
    name="project-forge",
    help="Initialize and evolve governed frontend/backend projects.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed Project Forge version and exit.",
    ),
) -> None:
    """Initialize and evolve governed frontend/backend projects."""


class SkillScope(StrEnum):
    REPO = "repo"
    USER = "user"


class DoctorCheck(TypedDict):
    name: str
    status: Literal["pass", "warn", "fail"]
    required: bool
    version: str | None
    message: str


def _version_parts(output: str) -> tuple[int, int, int] | None:
    match = re.search(r"(?<!\d)(\d+)(?:\.(\d+))?(?:\.(\d+))?", output)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor or 0), int(patch or 0)


def _at_least(major: int, minor: int = 0) -> Callable[[str], bool]:
    def compatible(output: str) -> bool:
        parts = _version_parts(output)
        return parts is not None and parts >= (major, minor, 0)

    return compatible


def _supported_node_lts(output: str) -> bool:
    """Accept only the Node LTS majors covered by the generated frontend."""

    parts = _version_parts(output)
    if parts is None:
        return False
    return (22, 13, 0) <= parts < (23, 0, 0) or (24, 0, 0) <= parts < (25, 0, 0)


def _tool_check(
    name: str,
    command: str,
    *,
    required: bool,
    requirement: str | None = None,
    compatible: Callable[[str], bool] | None = None,
) -> DoctorCheck:
    installed = tool_version(command)
    if installed is None:
        status: Literal["pass", "warn", "fail"] = "fail" if required else "warn"
        message = f"{name} is not installed"
    elif compatible is not None and not compatible(installed):
        status = "fail" if required else "warn"
        message = f"expected {requirement}"
    else:
        status = "pass"
        message = f"meets {requirement}" if requirement else "available"
    return {
        "name": name,
        "required": required,
        "status": status,
        "version": installed,
        "message": message,
    }


def _docker_checks(*, required: bool) -> list[DoctorCheck]:
    client = tool_version("docker")
    compose = tool_version("docker", "compose", "version") if client is not None else None
    server = tool_version("docker", "info", "--format", "{{.ServerVersion}}") if client else None
    failure_status: Literal["warn", "fail"] = "fail" if required else "warn"
    return [
        {
            "name": "docker-cli",
            "required": required,
            "status": "pass" if client is not None else failure_status,
            "version": client,
            "message": "Docker CLI is available" if client else "Docker CLI is not installed",
        },
        {
            "name": "docker-compose",
            "required": required,
            "status": "pass" if compose is not None else failure_status,
            "version": compose,
            "message": (
                "Docker Compose v2 is available"
                if compose
                else "Docker Compose v2 is unavailable"
            ),
        },
        {
            "name": "docker-daemon",
            "required": required,
            "status": "pass" if server is not None else failure_status,
            "version": server,
            "message": "Docker daemon is reachable" if server else "Docker daemon is not reachable",
        },
    ]


def _doctor_checks(profile: Profile, *, require_docker: bool) -> list[DoctorCheck]:
    has_frontend = profile in {Profile.FRONTEND, Profile.FULLSTACK}
    checks: list[DoctorCheck] = [
        {
            "name": "project-forge",
            "required": True,
            "status": "pass",
            "version": __version__,
            "message": "installed metadata is readable",
        },
        _tool_check(
            "python",
            sys.executable,
            required=True,
            requirement=">=3.11",
            compatible=_at_least(3, 11),
        ),
        _tool_check("git", "git", required=True),
        _tool_check("uv", "uv", required=True),
        _tool_check(
            "node",
            "node",
            required=has_frontend,
            requirement=">=22.13,<23 || >=24,<25 (LTS only)",
            compatible=_supported_node_lts,
        ),
        _tool_check("npm", "npm", required=has_frontend),
    ]
    checks.extend(_docker_checks(required=require_docker))
    return checks


def _project_checks(project_dir: Path) -> tuple[ProjectState | None, list[DoctorCheck]]:
    checks: list[DoctorCheck] = []
    try:
        loaded_state = load_state(project_dir)
    except (ValidationError, ValueError, OSError) as error:
        state = None
        checks.append(
            {
                "name": "project-state",
                "status": "fail",
                "required": True,
                "version": None,
                "message": str(error),
            }
        )
    else:
        state = loaded_state
        checks.append(
            {
                "name": "project-state",
                "status": "pass",
                "required": True,
                "version": loaded_state.template_version,
                "message": ".project-forge.yml is valid",
            }
        )

    baseline = project_dir / METADATA_DIR / BASELINE_FILE
    baseline_valid, baseline_message = validate_baseline(baseline)
    checks.append(
        {
            "name": "update-baseline",
            "status": "pass" if baseline_valid else "fail",
            "required": True,
            "version": None,
            "message": baseline_message,
        }
    )
    repository, clean, detail = git_worktree_status(project_dir)
    checks.extend(
        [
            {
                "name": "git-repository",
                "status": "pass" if repository else "fail",
                "required": True,
                "version": None,
                "message": (
                    "Git repository detected"
                    if repository
                    else (detail or "not a Git repository")
                ),
            },
            {
                "name": "git-clean",
                "status": "pass" if clean else "fail",
                "required": True,
                "version": None,
                "message": (
                    "working tree is clean" if clean else (detail or "Git status unavailable")
                ),
            },
        ]
    )
    return state, checks


def _fail(error: Exception) -> None:
    typer.secho(f"Error: {error}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2)


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _show_breaking_changes(result: UpdateResult) -> None:
    for change in result.breaking_changes:
        typer.secho(
            f"Breaking change: generated command {change.before} → {change.after}; "
            "user-owned scripts are not rewritten.",
            fg="yellow",
        )


def _apply(
    project_dir: Path,
    current_state: ProjectState,
    target_state: ProjectState | None = None,
) -> UpdateResult:
    target_state = target_state or current_state.with_current_template_identity()
    result = apply_controlled_update(project_dir, target_state, current_state)
    _show_breaking_changes(result)
    if result.status == "conflicts":
        typer.secho("Update stopped with conflicts; current files were preserved:", fg="yellow")
        for rejection in result.rejection_paths:
            typer.echo(f"  {project_dir / rejection}")
        raise typer.Exit(code=3)
    if result.status == "up_to_date":
        typer.echo("up to date")
    else:
        typer.secho(
            f"Updated {project_dir} to template {target_state.template_version}", fg="green"
        )
    return result


def _template_versions(state: ProjectState) -> tuple[Version, Version]:
    try:
        project_version = Version(state.template_version)
        installed_version = Version(__version__)
    except InvalidVersion as error:
        raise ProjectForgeError(f"invalid template version: {error}") from error
    if project_version > installed_version:
        raise ProjectForgeError(
            f"project template {project_version} is newer than installed Project Forge "
            f"{installed_version}; run `uv tool upgrade project-forge`"
        )
    return project_version, installed_version


@app.command("init")
def init_project(
    destination: Path = typer.Argument(..., help="New project directory"),
    name: str | None = typer.Option(None, "--name", help="Human-facing project name"),
    slug: str | None = typer.Option(None, "--slug", help="ASCII project slug"),
    command_name: str | None = typer.Option(
        None,
        "--command-name",
        help="Generated backend console command (default: project slug)",
    ),
    profile: Profile = typer.Option(Profile.FULLSTACK, "--profile"),
    auth: bool = typer.Option(False, "--auth/--no-auth"),
    evented: bool = typer.Option(False, "--evented/--no-evented"),
    sample: bool | None = typer.Option(
        None,
        "--sample/--no-sample",
        help="Generate the sample slice (default: backend/fullstack on, frontend off)",
    ),
    default_locale: Locale = typer.Option(Locale.ZH_CN, "--default-locale"),
    initialize_git: bool = typer.Option(True, "--git/--no-git"),
) -> None:
    """Create a frontend, backend, or full-stack project."""
    try:
        project_name = name or destination.name
        state = ProjectState.create(
            project_name,
            project_slug=slug,
            command_name=command_name,
            profile=profile,
            auth=auth,
            evented=evented,
            sample=sample,
            default_locale=default_locale,
        )
        initialize_project(state, destination, initialize_git=initialize_git)
    except (ProjectForgeError, ValidationError, ValueError, OSError) as error:
        _fail(error)
    typer.secho(f"Created {state.profile.value} project at {_absolute(destination)}", fg="green")
    if initialize_git:
        typer.echo("Commit the generated baseline before running add, enable, or update.")


@app.command("doctor")
def doctor(
    project_dir: Path | None = typer.Argument(
        None, help="Generated project to inspect; defaults to full-stack requirements"
    ),
    as_json: bool = typer.Option(False, "--json"),
    require_docker: bool = typer.Option(
        False,
        "--require-docker",
        help="Fail unless Docker CLI, Compose v2, and the daemon are available",
    ),
) -> None:
    """Validate profile-aware generator and generated-project prerequisites."""
    state: ProjectState | None = None
    root_path: str | None = None
    project_checks: list[DoctorCheck] = []
    if project_dir is not None:
        root = project_dir.resolve()
        root_path = str(root)
        state, project_checks = _project_checks(root)
    profile = state.profile if state is not None else Profile.FULLSTACK
    checks = [*_doctor_checks(profile, require_docker=require_docker), *project_checks]
    ok = all(check["status"] != "fail" for check in checks)
    report = {
        "ok": ok,
        "project": root_path,
        "checks": checks,
    }
    if as_json:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        scope = root_path or "new fullstack project"
        typer.echo(f"scope: {scope} ({profile.value})")
        for check in checks:
            role = "required" if check["required"] else "optional"
            version = check["version"] or ""
            typer.echo(
                f"{check['name']:16} {check['status']:5} {role:8} "
                f"{version} - {check['message']}"
            )
    if not ok:
        raise typer.Exit(code=1)


@app.command("features")
def features(project_dir: Path = typer.Argument(Path("."))) -> None:
    """Show persisted profile and capability flags."""
    try:
        state = load_state(project_dir.resolve())
    except (ValidationError, ValueError, OSError) as error:
        _fail(error)
    typer.echo(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command("add")
def add_component(
    component: Component = typer.Argument(...),
    project_dir: Path = typer.Option(Path("."), "--project-dir", "-C"),
) -> None:
    """Monotonically add frontend or backend to an existing project."""
    try:
        root = _absolute(project_dir)
        state = load_state(root)
        _template_versions(state)
        if (
            (component is Component.BACKEND
            and state.profile is Profile.FRONTEND)
            or (component is Component.FRONTEND
            and state.profile is Profile.BACKEND)
        ):
            state = state.model_copy(update={"profile": Profile.FULLSTACK})
        _apply(root, state, state.with_current_template_identity())
    except (ProjectForgeError, ValidationError, ValueError, OSError) as error:
        _fail(error)


@app.command("enable")
def enable_feature(
    feature: Feature = typer.Argument(...),
    project_dir: Path = typer.Option(Path("."), "--project-dir", "-C"),
) -> None:
    """Monotonically enable auth, evented processing, or the sample slice."""
    try:
        root = _absolute(project_dir)
        state = load_state(root)
        _template_versions(state)
        if not getattr(state, feature.value):
            state = state.model_copy(update={feature.value: True})
        state = ProjectState.model_validate(state.model_dump())
        _apply(root, state, state.with_current_template_identity())
    except (ProjectForgeError, ValidationError, ValueError, OSError) as error:
        _fail(error)


@app.command("configure")
def configure_project(
    command_name: str = typer.Option(
        ...,
        "--command-name",
        help="Generated backend console command; normalized to lowercase hyphen form",
    ),
    project_dir: Path = typer.Option(Path("."), "--project-dir", "-C"),
) -> None:
    """Change persisted generator configuration through a controlled update."""

    try:
        root = _absolute(project_dir)
        state = load_state(root)
        _template_versions(state)
        normalized = normalize_command_name(command_name)
        target_state = state.with_current_template_identity(command_name=normalized)
        _apply(root, state, target_state)
    except (ProjectForgeError, ValidationError, ValueError, OSError) as error:
        _fail(error)


@app.command("update")
def update_project(
    project_dir: Path = typer.Argument(Path(".")),
    check: bool = typer.Option(
        False,
        "--check",
        help=(
            "Render and compare with this installed template without changing the project; "
            "do not check a remote repository"
        ),
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit a stable machine-readable result"),
) -> None:
    """Apply the packaged template with clean-Git and .rej conflict safeguards."""
    try:
        root = _absolute(project_dir)
        state = load_state(root)
        _template_versions(state)
        target_state = state.with_current_template_identity()
        if check:
            result = preview_controlled_update(root, state, target_state)
            if as_json:
                typer.echo(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
            else:
                _show_breaking_changes(result)
            if result.status == "conflicts":
                if as_json:
                    raise typer.Exit(code=3)
                typer.echo(
                    f"update conflicts ({len(result.conflict_paths)} managed paths); "
                    "run update to write .rej diagnostics"
                )
                raise typer.Exit(code=3)
            if result.status == "update_available":
                if not as_json:
                    typer.echo(f"update available ({len(result.changed_paths)} paths)")
                raise typer.Exit(code=1)
            if not as_json:
                typer.echo("up to date")
            return
        if as_json:
            result = apply_controlled_update(root, target_state, state)
            typer.echo(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
            if result.status == "conflicts":
                raise typer.Exit(code=3)
        else:
            _apply(root, state, target_state)
    except typer.Exit:
        raise
    except (ProjectForgeError, ValidationError, ValueError, OSError) as error:
        if not as_json:
            _fail(error)
        report = {
            "status": "error",
            "project": str(_absolute(project_dir)),
            "target_template_version": __version__,
            "target_template_digest": current_template_digest(),
            "identity_changed": False,
            "changed_paths": [],
            "conflict_paths": [],
            "rejection_paths": [],
            "breaking_changes": [],
            "message": str(error),
        }
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
        raise typer.Exit(code=2) from error


@app.command("install-skill")
def install_skill(
    scope: SkillScope = typer.Option(SkillScope.REPO, "--scope"),
    destination: Path | None = typer.Option(None, "--destination"),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Install the bundled project-forge-init Codex skill."""
    if destination is None:
        base = Path.home() if scope is SkillScope.USER else Path.cwd()
        destination = base / ".agents/skills/project-forge-init"
    try:
        installed = copy_skill(destination, overwrite=overwrite)
    except (ProjectForgeError, OSError) as error:
        _fail(error)
    typer.secho(f"Installed skill at {installed}", fg="green")


def main() -> None:
    app()
