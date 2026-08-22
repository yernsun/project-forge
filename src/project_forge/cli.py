from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

import typer
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
    ProjectForgeError,
    apply_controlled_update,
    copy_skill,
    initialize_project,
    tool_version,
)

app = typer.Typer(
    name="project-forge",
    help="Initialize and evolve governed frontend/backend projects.",
    no_args_is_help=True,
)


class SkillScope(StrEnum):
    REPO = "repo"
    USER = "user"


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


@app.command("init")
def init_project(
    destination: Path = typer.Argument(..., help="New project directory"),
    name: str | None = typer.Option(None, "--name", help="Human-facing project name"),
    slug: str | None = typer.Option(None, "--slug", help="ASCII project slug"),
    profile: Profile = typer.Option(Profile.FULLSTACK, "--profile"),
    auth: bool = typer.Option(False, "--auth/--no-auth"),
    evented: bool = typer.Option(False, "--evented/--no-evented"),
    sample: bool = typer.Option(True, "--sample/--no-sample"),
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
def doctor(as_json: bool = typer.Option(False, "--json")) -> None:
    """Report generator and generated-project tool availability."""
    versions = {
        "project-forge": __version__,
        "python": tool_version("python3"),
        "uv": tool_version("uv"),
        "node": tool_version("node"),
        "npm": tool_version("npm"),
        "docker": tool_version("docker"),
        "git": tool_version("git"),
    }
    if as_json:
        typer.echo(json.dumps(versions, ensure_ascii=False, indent=2))
        return
    for name, version in versions.items():
        marker = "ok" if version is not None else "missing"
        typer.echo(f"{name:14} {marker:7} {version or ''}")


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
    check: bool = typer.Option(False, "--check", help="Only report whether an update is available"),
) -> None:
    """Apply the packaged template with clean-Git and .rej conflict safeguards."""
    try:
        root = project_dir.resolve()
        state = load_state(root)
        if check:
            available = state.template_version != __version__
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
        copy_skill(destination.resolve(), overwrite=overwrite)
    except (ProjectForgeError, OSError) as error:
        _fail(error)
    typer.secho(f"Installed skill at {destination.resolve()}", fg="green")


def main() -> None:
    app()
