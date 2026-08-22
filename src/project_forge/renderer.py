from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Iterable
from pathlib import Path

from copier import run_copy

from project_forge.config import STATE_FILE, ProjectState, dump_state

METADATA_DIR = ".project-forge"
BASELINE_FILE = "baseline.tar.gz"


class ProjectForgeError(RuntimeError):
    """A user-actionable generator failure."""


def template_path() -> Path:
    return Path(__file__).resolve().parent / "template"


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _prune(rendered: Path, state: ProjectState) -> None:
    _remove(rendered / METADATA_DIR)
    if not state.has_backend:
        _remove(rendered / "backend")
    if not state.has_frontend:
        _remove(rendered / "frontend")
    if state.has_backend and not state.auth:
        _remove(rendered / "backend/src/app/auth")
        _remove(rendered / "backend/tests/test_auth.py")
    if state.has_frontend and not state.auth:
        _remove(rendered / "frontend/src/features/auth")
    if state.has_backend and not state.evented:
        _remove(rendered / "backend/src/app/events")
        _remove(rendered / "backend/tests/test_evented.py")
    if not state.sample:
        for relative in (
            "backend/src/app/domain/items.py",
            "backend/src/app/repositories/items.py",
            "backend/src/app/services/items.py",
            "backend/src/app/api/items.py",
            "backend/src/app/db/migrations/items.py",
            "backend/tests/test_domain_models.py",
            "backend/tests/test_items_query.py",
            "frontend/src/features/items",
            "frontend/tests/items.spec.ts",
        ):
            _remove(rendered / relative)


def render_fresh(state: ProjectState, destination: Path) -> None:
    if destination.exists():
        raise ProjectForgeError(f"fresh render destination already exists: {destination}")
    run_copy(
        str(template_path()),
        str(destination),
        data=state.copier_data(),
        defaults=True,
        overwrite=False,
        quiet=True,
        unsafe=False,
    )
    _prune(destination, state)


def _managed_files(root: Path) -> list[Path]:
    ignored_roots = {".git", METADATA_DIR}
    result: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in ignored_roots:
            continue
        if relative.as_posix() == STATE_FILE or path.is_dir():
            continue
        result.append(relative)
    return sorted(result, key=lambda item: item.as_posix())


def _write_baseline(rendered: Path, project_dir: Path) -> None:
    metadata = project_dir / METADATA_DIR
    metadata.mkdir(parents=True, exist_ok=True)
    archive = metadata / BASELINE_FILE
    temporary = archive.with_suffix(".tmp")
    with tarfile.open(temporary, "w:gz") as bundle:
        for relative in _managed_files(rendered):
            bundle.add(rendered / relative, arcname=relative.as_posix(), recursive=False)
    temporary.replace(archive)


def _copy_render(rendered: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in rendered.iterdir():
        target = destination / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)


def initialize_project(
    state: ProjectState, destination: Path, *, initialize_git: bool = True
) -> None:
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ProjectForgeError(f"destination is not empty: {destination}")
    with tempfile.TemporaryDirectory(prefix="project-forge-render-") as temp_dir:
        rendered = Path(temp_dir) / "rendered"
        render_fresh(state, rendered)
        _copy_render(rendered, destination)
        (destination / STATE_FILE).write_text(dump_state(state), encoding="utf-8")
        _write_baseline(rendered, destination)
    if initialize_git and not (destination / ".git").exists():
        subprocess.run(
            ["git", "init", str(destination)], check=True, capture_output=True, text=True
        )


def _git(project_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project_dir), *args], check=False, capture_output=True, text=True
    )


def require_clean_git(project_dir: Path) -> None:
    inside = _git(project_dir, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        raise ProjectForgeError("controlled updates require a Git repository")
    status = _git(project_dir, "status", "--porcelain")
    if status.returncode != 0:
        raise ProjectForgeError(status.stderr.strip() or "unable to read Git status")
    if status.stdout.strip():
        raise ProjectForgeError("destination repository is dirty; commit or stash changes first")
    rejections = sorted(project_dir.rglob("*.rej"))
    if rejections:
        raise ProjectForgeError("resolve and remove existing .rej files before updating")


def _extract_baseline(project_dir: Path, destination: Path) -> None:
    archive = project_dir / METADATA_DIR / BASELINE_FILE
    if not archive.is_file():
        raise ProjectForgeError(f"missing update baseline: {archive}")
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(destination, filter="data")


def _same(left: Path, right: Path) -> bool:
    return left.is_file() and right.is_file() and left.read_bytes() == right.read_bytes()


def _is_text(path: Path) -> bool:
    try:
        path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    return True


def _write_rejection(path: Path, content: bytes) -> Path:
    rejection = path.with_name(path.name + ".rej")
    rejection.parent.mkdir(parents=True, exist_ok=True)
    rejection.write_bytes(content)
    return rejection


def _merge_text(current: Path, old: Path, new: Path) -> tuple[bool, str]:
    process = subprocess.run(
        ["git", "merge-file", "-p", str(current), str(old), str(new)],
        check=False,
        capture_output=True,
        text=True,
    )
    return process.returncode == 0, process.stdout


def _prune_empty_parents(path: Path, stop: Path) -> None:
    parent = path.parent
    while parent != stop and parent.is_dir():
        try:
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent


def _all_relative_files(roots: Iterable[Path]) -> list[Path]:
    paths: set[Path] = set()
    for root in roots:
        paths.update(_managed_files(root))
    return sorted(paths, key=lambda item: item.as_posix())


def apply_controlled_update(project_dir: Path, state: ProjectState) -> list[Path]:
    project_dir = project_dir.resolve()
    require_clean_git(project_dir)
    with tempfile.TemporaryDirectory(prefix="project-forge-update-") as temp_dir:
        work = Path(temp_dir)
        old_root = work / "old"
        new_root = work / "new"
        old_root.mkdir()
        _extract_baseline(project_dir, old_root)
        render_fresh(state, new_root)
        conflicts: list[Path] = []
        for relative in _all_relative_files((old_root, new_root, project_dir)):
            if relative.as_posix() == STATE_FILE or relative.parts[0] in {".git", METADATA_DIR}:
                continue
            old = old_root / relative
            new = new_root / relative
            current = project_dir / relative
            old_exists = old.is_file()
            new_exists = new.is_file()
            current_exists = current.is_file()

            if not old_exists and not new_exists:
                continue
            if old_exists and new_exists and _same(old, new):
                continue
            if current_exists and new_exists and _same(current, new):
                continue
            if old_exists and current_exists and _same(old, current):
                if new_exists:
                    current.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(new, current)
                else:
                    current.unlink()
                    _prune_empty_parents(current, project_dir)
                continue
            if not old_exists and new_exists and not current_exists:
                current.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(new, current)
                continue
            if old_exists and not new_exists and not current_exists:
                continue
            if old_exists and new_exists and current_exists and all(
                _is_text(path) for path in (old, new, current)
            ):
                merged, content = _merge_text(current, old, new)
                if merged:
                    current.write_text(content, encoding="utf-8")
                else:
                    conflicts.append(_write_rejection(current, content.encode("utf-8")))
                continue
            if new_exists:
                conflicts.append(_write_rejection(current, new.read_bytes()))
            else:
                message = f"Template removed {relative.as_posix()}, but the project changed it.\n"
                conflicts.append(_write_rejection(current, message.encode("utf-8")))

        if not conflicts:
            applied_state = state.model_copy(update={"template_version": state.template_version})
            (project_dir / STATE_FILE).write_text(dump_state(applied_state), encoding="utf-8")
            _write_baseline(new_root, project_dir)
        return conflicts


def tool_version(command: str) -> str | None:
    executable = shutil.which(command)
    if executable is None:
        return None
    process = subprocess.run([executable, "--version"], check=False, capture_output=True, text=True)
    output = process.stdout.strip() or process.stderr.strip()
    return output.splitlines()[0] if output else "installed"


def copy_skill(destination: Path, *, overwrite: bool = False) -> None:
    source = Path(__file__).resolve().parent / "bundled_skill"
    if destination.exists():
        if not overwrite:
            raise ProjectForgeError(f"skill already exists: {destination}")
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    for root, directories, files in os.walk(destination):
        for name in directories:
            os.chmod(Path(root) / name, 0o755)
        for name in files:
            os.chmod(Path(root) / name, 0o755 if name.endswith(".sh") else 0o644)
