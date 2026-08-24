from __future__ import annotations

import json
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
)
from project_forge.renderer import (
    BASELINE_FILE,
    METADATA_DIR,
    ProjectForgeError,
    apply_controlled_update,
    copy_skill,
    git_worktree_status,
    initialize_project,
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


def _at_least_below(
    major: int, minor: int, upper_major: int
) -> Callable[[str], bool]:
    def compatible(output: str) -> bool:
        parts = _version_parts(output)
        return parts is not None and (major, minor, 0) <= parts < (upper_major, 0, 0)

    return compatible


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
            requirement=">=22.12,<27",
            compatible=_at_least_below(22, 12, 27),
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


def _apply(project_dir: Path, state: ProjectState) -> None:
    conflicts = apply_controlled_update(project_dir, state)
    if conflicts:
        typer.secho("Update stopped with conflicts; current files were preserved:", fg="yellow")
        for conflict in conflicts:
            typer.echo(f"  {conflict}")
        raise typer.Exit(code=3)
    typer.secho(f"Updated {project_dir} to template {state.template_version}", fg="green")


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
            profile=profile,
            auth=auth,
            evented=evented,
            sample=sample,
            default_locale=default_locale,
        )
        initialize_project(state, destination, initialize_git=initialize_git)
    except (ProjectForgeError, ValidationError, ValueError, OSError) as error:
        _fail(error)
    typer.secho(f"Created {state.profile.value} project at {destination.resolve()}", fg="green")
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
        root = project_dir.resolve()
        state = load_state(root)
        _template_versions(state)
        if (
            (component is Component.BACKEND
            and state.profile is Profile.FRONTEND)
            or (component is Component.FRONTEND
            and state.profile is Profile.BACKEND)
        ):
            state = state.model_copy(update={"profile": Profile.FULLSTACK})
        elif (component is Component.BACKEND and state.has_backend) or (
            component is Component.FRONTEND and state.has_frontend
        ):
            typer.echo(f"{component.value} is already enabled")
            return
        state = state.model_copy(update={"template_version": __version__})
        _apply(root, state)
    except (ProjectForgeError, ValidationError, ValueError, OSError) as error:
        _fail(error)


@app.command("enable")
def enable_feature(
    feature: Feature = typer.Argument(...),
    project_dir: Path = typer.Option(Path("."), "--project-dir", "-C"),
) -> None:
    """Monotonically enable auth, evented processing, or the sample slice."""
    try:
        root = project_dir.resolve()
        state = load_state(root)
        _template_versions(state)
        if getattr(state, feature.value):
            typer.echo(f"{feature.value} is already enabled")
            return
        state = state.model_copy(
            update={feature.value: True, "template_version": __version__}
        )
        state = ProjectState.model_validate(state.model_dump())
        _apply(root, state)
    except (ProjectForgeError, ValidationError, ValueError, OSError) as error:
        _fail(error)


@app.command("update")
def update_project(
    project_dir: Path = typer.Argument(Path(".")),
    check: bool = typer.Option(
        False,
        "--check",
        help=(
            "Only compare the project with this installed template version; "
            "do not check a remote repository"
        ),
    ),
) -> None:
    """Apply the packaged template with clean-Git and .rej conflict safeguards."""
    try:
        root = project_dir.resolve()
        state = load_state(root)
        project_version, installed_version = _template_versions(state)
        if check:
            available = installed_version > project_version
            typer.echo("update available" if available else "up to date")
            raise typer.Exit(code=1 if available else 0)
        state = state.model_copy(update={"template_version": __version__})
        _apply(root, state)
    except typer.Exit:
        raise
    except (ProjectForgeError, ValidationError, ValueError, OSError) as error:
        _fail(error)


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
