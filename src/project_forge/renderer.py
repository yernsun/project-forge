from __future__ import annotations

import gzip
import hashlib
import io
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from copier import run_copy
from copier.errors import CopierError

from project_forge.config import STATE_FILE, ProjectState, dump_state, load_state

METADATA_DIR = ".project-forge"
BASELINE_FILE = "baseline.tar.gz"
MAX_BASELINE_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_BASELINE_MEMBERS = 4096
MAX_BASELINE_MEMBER_BYTES = 16 * 1024 * 1024
MAX_BASELINE_UNCOMPRESSED_BYTES = 128 * 1024 * 1024


class ProjectForgeError(RuntimeError):
    """A user-actionable generator failure."""


def _baseline_members(bundle: tarfile.TarFile) -> list[tuple[tarfile.TarInfo, Path]]:
    members: list[tuple[tarfile.TarInfo, Path]] = []
    seen: set[Path] = set()
    total_size = 0
    for member in bundle:
        if len(members) >= MAX_BASELINE_MEMBERS:
            raise ValueError(
                f"baseline archive exceeds {MAX_BASELINE_MEMBERS} members"
            )
        posix_path = PurePosixPath(member.name)
        windows_path = PureWindowsPath(member.name)
        if (
            not posix_path.parts
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or ".." in posix_path.parts
            or ".." in windows_path.parts
        ):
            raise ValueError(f"unsafe baseline member path: {member.name!r}")
        if not member.isfile():
            raise ValueError(f"baseline member is not a regular file: {member.name!r}")
        if member.size < 0 or member.size > MAX_BASELINE_MEMBER_BYTES:
            raise ValueError(
                f"baseline member exceeds {MAX_BASELINE_MEMBER_BYTES} bytes: {member.name!r}"
            )
        total_size += member.size
        if total_size > MAX_BASELINE_UNCOMPRESSED_BYTES:
            raise ValueError(
                "baseline archive exceeds "
                f"{MAX_BASELINE_UNCOMPRESSED_BYTES} uncompressed bytes"
            )
        relative = Path(*posix_path.parts)
        if relative in seen:
            raise ValueError(f"duplicate baseline member path: {member.name!r}")
        if any(parent in seen for parent in relative.parents) or any(
            relative in existing.parents for existing in seen
        ):
            raise ValueError(f"conflicting baseline member path: {member.name!r}")
        seen.add(relative)
        members.append((member, relative))
    if not members:
        raise ValueError("baseline archive is empty")
    return members


@dataclass(frozen=True)
class _PlannedChange:
    relative: Path
    action: Literal["write", "delete"]
    content: bytes | None = None
    mode: int | None = None


@dataclass(frozen=True)
class _PlannedRejection:
    relative: Path
    content: bytes


@dataclass(frozen=True)
class _FileSnapshot:
    path: Path
    existed: bool
    content: bytes | None
    mode: int | None


@dataclass(frozen=True)
class BreakingChange:
    """Stable machine-readable description of a deliberate compatibility break."""

    code: str
    before: str
    after: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "from": self.before, "to": self.after}


UpdateStatus = Literal["up_to_date", "update_available", "updated", "conflicts"]


@dataclass(frozen=True)
class UpdateResult:
    """Shared read-only/apply result for controlled template updates."""

    status: UpdateStatus
    project: Path
    target_template_version: str
    target_template_digest: str | None
    identity_changed: bool
    changed_paths: tuple[Path, ...]
    conflict_paths: tuple[Path, ...]
    rejection_paths: tuple[Path, ...]
    breaking_changes: tuple[BreakingChange, ...]

    @property
    def update_available(self) -> bool:
        return self.status in {"update_available", "conflicts"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "project": str(self.project),
            "target_template_version": self.target_template_version,
            "target_template_digest": self.target_template_digest,
            "identity_changed": self.identity_changed,
            "changed_paths": [path.as_posix() for path in self.changed_paths],
            "conflict_paths": [path.as_posix() for path in self.conflict_paths],
            "rejection_paths": [path.as_posix() for path in self.rejection_paths],
            "breaking_changes": [change.as_dict() for change in self.breaking_changes],
        }


@dataclass(frozen=True)
class _UpdatePlan:
    changes: tuple[_PlannedChange, ...]
    rejections: tuple[_PlannedRejection, ...]
    new_root: Path


def template_path() -> Path:
    return Path(__file__).resolve().parent / "template"


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _prune(rendered: Path, state: ProjectState) -> None:
    _remove(rendered / METADATA_DIR)
    for cache in ("node_modules", "dist", "coverage"):
        _remove(rendered / "frontend" / cache)
    if not state.has_backend:
        _remove(rendered / "backend")
    if not state.has_frontend:
        _remove(rendered / "frontend")
    if state.has_backend and not state.auth:
        _remove(rendered / "backend/src/app/auth")
        _remove(rendered / "backend/tests/test_auth.py")
        _remove(rendered / "backend/tests/test_auth_postgres.py")
        for migration in ("auth.py", "auth_security.py", "auth_items.py"):
            _remove(rendered / "backend/src/app/db/migrations" / migration)
    if state.has_frontend and not state.auth:
        _remove(rendered / "frontend/src/features/auth")
        _remove(rendered / "frontend/tests/auth.spec.ts")
    if state.has_backend and state.auth and not state.sample:
        _remove(rendered / "backend/src/app/db/migrations/auth_items.py")
    if state.has_backend and not state.evented:
        _remove(rendered / "backend/src/app/events")
        for migration in ("events.py", "event_idempotency.py", "event_reliability.py"):
            _remove(rendered / "backend/src/app/db/migrations" / migration)
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
    try:
        run_copy(
            str(template_path()),
            str(destination),
            data=state.copier_data(),
            defaults=True,
            overwrite=False,
            quiet=True,
            unsafe=False,
        )
    except CopierError as error:
        raise ProjectForgeError(f"template rendering failed: {error}") from error
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


def _normalized_archive_mode(path: Path) -> int:
    return 0o755 if _file_mode(path) & 0o111 else 0o644


def _baseline_bytes(rendered: Path) -> bytes:
    managed = _managed_files(rendered)
    if len(managed) > MAX_BASELINE_MEMBERS:
        raise ProjectForgeError(
            f"rendered baseline exceeds {MAX_BASELINE_MEMBERS} members"
        )

    total_size = 0
    output = io.BytesIO()
    with (
        gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as bundle,
    ):
        for relative in managed:
            source = rendered / relative
            size = source.stat().st_size
            if size > MAX_BASELINE_MEMBER_BYTES:
                raise ProjectForgeError(
                    f"rendered baseline member exceeds {MAX_BASELINE_MEMBER_BYTES} bytes: "
                    f"{relative.as_posix()}"
                )
            total_size += size
            if total_size > MAX_BASELINE_UNCOMPRESSED_BYTES:
                raise ProjectForgeError(
                    "rendered baseline exceeds "
                    f"{MAX_BASELINE_UNCOMPRESSED_BYTES} uncompressed bytes"
                )
            member = tarfile.TarInfo(relative.as_posix())
            member.size = size
            member.mode = _normalized_archive_mode(source)
            member.mtime = 0
            member.uid = 0
            member.gid = 0
            member.uname = ""
            member.gname = ""
            with source.open("rb") as stream:
                bundle.addfile(member, stream)
    payload = output.getvalue()
    if len(payload) > MAX_BASELINE_COMPRESSED_BYTES:
        raise ProjectForgeError(
            f"rendered baseline exceeds {MAX_BASELINE_COMPRESSED_BYTES} compressed bytes"
        )
    return payload


def _write_baseline(rendered: Path, project_dir: Path) -> None:
    metadata = project_dir / METADATA_DIR
    metadata.mkdir(parents=True, exist_ok=True)
    archive = metadata / BASELINE_FILE
    _atomic_write_bytes(archive, _baseline_bytes(rendered), 0o644)


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
    state = state.with_current_template_identity()
    destination = _absolute_without_symlink_resolution(destination)
    if destination.is_symlink() or _is_junction(destination):
        raise ProjectForgeError(
            f"project destination must not be a symbolic link or junction: {destination}"
        )
    if destination.exists() and any(destination.iterdir()):
        raise ProjectForgeError(f"destination is not empty: {destination}")
    with tempfile.TemporaryDirectory(prefix="project-forge-render-") as temp_dir:
        rendered = Path(temp_dir) / "rendered"
        staged = Path(temp_dir) / "staged"
        render_fresh(state, rendered)
        _copy_render(rendered, staged)
        (staged / STATE_FILE).write_text(dump_state(state), encoding="utf-8")
        _write_baseline(rendered, staged)
        if initialize_git:
            try:
                subprocess.run(
                    ["git", "init", str(staged)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except (OSError, subprocess.SubprocessError) as error:
                detail = getattr(error, "stderr", None) or str(error)
                raise ProjectForgeError(f"Git initialization failed: {detail.strip()}") from error
        _copy_render(staged, destination)


def _git(project_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project_dir), *args], check=False, capture_output=True, text=True
    )


def git_worktree_status(project_dir: Path) -> tuple[bool, bool, str | None]:
    """Return repository, cleanliness, and error details without mutating Git state."""
    try:
        inside = _git(project_dir, "rev-parse", "--is-inside-work-tree")
    except OSError as error:
        return False, False, str(error)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return False, False, inside.stderr.strip() or "not a Git repository"
    status = _git(project_dir, "status", "--porcelain")
    if status.returncode != 0:
        return True, False, status.stderr.strip() or "unable to read Git status"
    if status.stdout.strip():
        return True, False, "working tree has uncommitted or untracked changes"
    return True, True, None


def require_clean_git(project_dir: Path) -> None:
    if project_dir.is_symlink() or _is_junction(project_dir):
        raise ProjectForgeError(
            f"project root must not be a symbolic link or junction: {project_dir}"
        )
    repository, clean, detail = git_worktree_status(project_dir)
    if not repository:
        raise ProjectForgeError("controlled updates require a Git repository")
    if not clean:
        raise ProjectForgeError(detail or "destination repository is dirty; commit or stash first")
    rejections: list[Path] = []
    for root, directories, files in os.walk(project_dir, followlinks=False):
        root_path = Path(root)
        directories[:] = [
            name
            for name in directories
            if not _is_junction(root_path / name) and not (root_path / name).is_symlink()
        ]
        rejections.extend(root_path / name for name in files if name.endswith(".rej"))
    if rejections:
        raise ProjectForgeError("resolve and remove existing .rej files before updating")


def validate_baseline(baseline: Path) -> tuple[bool, str]:
    project_dir = _absolute_without_symlink_resolution(baseline.parent.parent)
    baseline = _absolute_without_symlink_resolution(baseline)
    obstacle = _project_path_obstacle(
        project_dir, Path(METADATA_DIR) / BASELINE_FILE
    )
    if obstacle is not None:
        return False, f"baseline path must not contain symlinks or junctions: {obstacle}"
    if baseline.is_symlink() or _is_junction(baseline):
        return False, f"baseline path must not contain symlinks or junctions: {baseline}"
    if not baseline.is_file():
        return False, f"missing {baseline}"
    if baseline.stat().st_size > MAX_BASELINE_COMPRESSED_BYTES:
        return False, (
            f"baseline archive exceeds {MAX_BASELINE_COMPRESSED_BYTES} compressed bytes"
        )
    try:
        with tarfile.open(baseline, mode="r:gz") as archive:
            _baseline_members(archive)
    except ValueError as error:
        return False, str(error)
    except (tarfile.TarError, OSError, EOFError) as error:
        return False, f"baseline archive is invalid: {error}"
    return True, "baseline archive is valid"


def _extract_baseline(project_dir: Path, destination: Path) -> None:
    archive = project_dir / METADATA_DIR / BASELINE_FILE
    invalid_destination = destination.is_symlink() or _is_junction(destination) or (
        destination.exists()
        and (not destination.is_dir() or any(destination.iterdir()))
    )
    if invalid_destination:
        raise ProjectForgeError("baseline extraction destination must be an empty real directory")
    valid, detail = validate_baseline(archive)
    if not valid:
        raise ProjectForgeError(detail)
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = _baseline_members(bundle)
            destination.mkdir(parents=True, exist_ok=True)
            for member, relative in members:
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:  # pragma: no cover - guarded by member.isfile()
                    raise tarfile.ExtractError(f"cannot read baseline member: {member.name!r}")
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                os.chmod(target, member.mode & 0o777)
    except ValueError as error:
        raise ProjectForgeError(str(error)) from error
    except (tarfile.TarError, OSError, EOFError) as error:
        raise ProjectForgeError(f"baseline archive could not be extracted: {error}") from error


def _same(left: Path, right: Path) -> bool:
    return (
        left.is_file()
        and right.is_file()
        and left.read_bytes() == right.read_bytes()
        and _file_mode(left) == _file_mode(right)
    )


def _file_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _atomic_write_bytes(
    path: Path,
    content: bytes,
    mode: int,
    *,
    project_dir: Path | None = None,
) -> None:
    if project_dir is not None:
        _assert_safe_project_file(project_dir, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if project_dir is not None:
        _assert_safe_project_file(project_dir, path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.project-forge-", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        if project_dir is not None:
            _assert_safe_project_file(project_dir, path)
        temporary.replace(path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def _snapshot_file(path: Path, project_dir: Path | None = None) -> _FileSnapshot:
    if project_dir is not None:
        _assert_safe_project_file(project_dir, path)
    elif path.is_symlink() or _is_junction(path):
        raise ProjectForgeError(
            f"managed metadata must not be a symlink or junction: {path}"
        )
    if not path.exists():
        return _FileSnapshot(path=path, existed=False, content=None, mode=None)
    if not path.is_file():
        raise ProjectForgeError(f"managed path must be a regular file: {path}")
    return _FileSnapshot(
        path=path,
        existed=True,
        content=path.read_bytes(),
        mode=_file_mode(path),
    )


def _restore_snapshot(snapshot: _FileSnapshot, project_dir: Path) -> None:
    if snapshot.existed:
        if snapshot.content is None or snapshot.mode is None:  # pragma: no cover - invariant
            raise AssertionError("existing snapshot is missing content or mode")
        _atomic_write_bytes(
            snapshot.path,
            snapshot.content,
            snapshot.mode,
            project_dir=project_dir,
        )
        return
    _assert_safe_project_file(project_dir, snapshot.path)
    if snapshot.path.is_file():
        snapshot.path.unlink()
        _prune_empty_parents(snapshot.path, project_dir)
    elif snapshot.path.exists():
        raise ProjectForgeError(f"cannot roll back non-file path: {snapshot.path}")


def _is_text(path: Path) -> bool:
    try:
        path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    return True


def _project_parent_obstacle(project_dir: Path, relative: Path) -> Path | None:
    if project_dir.is_symlink() or _is_junction(project_dir):
        return project_dir
    if project_dir.exists() and not project_dir.is_dir():
        return project_dir
    candidate = project_dir
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink() or _is_junction(candidate):
            return candidate
        if candidate.exists() and not candidate.is_dir():
            return candidate
    return None


def _project_path_obstacle(project_dir: Path, relative: Path) -> Path | None:
    parent_obstacle = _project_parent_obstacle(project_dir, relative.parent)
    if parent_obstacle is not None:
        return parent_obstacle
    candidate = project_dir / relative
    if (
        candidate.is_symlink()
        or _is_junction(candidate)
        or (candidate.exists() and not candidate.is_file())
    ):
        return candidate
    return None


def _assert_safe_project_file(project_dir: Path, path: Path) -> Path:
    project_dir = _absolute_without_symlink_resolution(project_dir)
    path = _absolute_without_symlink_resolution(path)
    try:
        relative = path.relative_to(project_dir)
    except ValueError as error:
        raise ProjectForgeError(f"managed path escapes the project root: {path}") from error
    if relative == Path("."):
        raise ProjectForgeError(f"managed path must be below the project root: {path}")
    obstacle = _project_path_obstacle(project_dir, relative)
    if obstacle is not None:
        raise ProjectForgeError(
            "managed paths must be regular files under real directories; "
            f"found {obstacle}"
        )
    return relative


def _write_project_rejection(
    project_dir: Path, rejection: _PlannedRejection
) -> Path:
    target = project_dir / rejection.relative
    desired = target.with_name(target.name + ".rej")
    desired_relative = rejection.relative.with_name(rejection.relative.name + ".rej")
    if not desired.exists() and _project_path_obstacle(project_dir, desired_relative) is None:
        _atomic_write_bytes(desired, rejection.content, 0o644, project_dir=project_dir)
        return desired
    digest = hashlib.sha256(rejection.relative.as_posix().encode()).hexdigest()[:12]
    safe_name = f"project-forge-{rejection.relative.name}-{digest}.rej"
    safe_rejection = project_dir / safe_name
    if safe_rejection.exists() or safe_rejection.is_symlink() or _is_junction(safe_rejection):
        raise ProjectForgeError(
            f"refusing to overwrite existing rejection diagnostic: {safe_rejection}"
        )
    _atomic_write_bytes(
        safe_rejection,
        rejection.content,
        0o644,
        project_dir=project_dir,
    )
    return safe_rejection


def _merge_text(current: Path, old: Path, new: Path) -> tuple[bool, str]:
    process = subprocess.run(
        ["git", "merge-file", "-p", str(current), str(old), str(new)],
        check=False,
        capture_output=True,
        text=True,
    )
    return process.returncode == 0, process.stdout


def _merge_mode(old: int, current: int, new: int) -> int | None:
    """Three-way merge a file mode, treating it as one scalar template attribute."""
    if current == new:
        return current
    if current == old:
        return new
    if new == old:
        return current
    return None


def _mode_conflict(relative: Path, old: int, current: int, new: int) -> bytes:
    return (
        f"Cannot update {relative.as_posix()}: file mode changed differently in the project "
        "and template.\n"
        f"baseline mode: {old:#06o}\n"
        f"project mode:  {current:#06o}\n"
        f"template mode: {new:#06o}\n"
    ).encode()


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


def _plan_controlled_update(
    project_dir: Path,
    state: ProjectState,
    work: Path,
) -> _UpdatePlan:
    old_root = work / "old"
    new_root = work / "new"
    old_root.mkdir()
    _extract_baseline(project_dir, old_root)
    render_fresh(state, new_root)
    changes: list[_PlannedChange] = []
    rejections: list[_PlannedRejection] = []
    for relative in _all_relative_files((old_root, new_root)):
        if relative.as_posix() == STATE_FILE or relative.parts[0] in {".git", METADATA_DIR}:
            continue
        old = old_root / relative
        new = new_root / relative
        current = project_dir / relative
        obstacle = _project_path_obstacle(project_dir, relative)
        if obstacle is not None:
            message = (
                f"Cannot update {relative.as_posix()}: managed paths must be regular files "
                f"under real directories; found {obstacle.relative_to(project_dir)}.\n"
            )
            rejections.append(_PlannedRejection(relative, message.encode("utf-8")))
            continue
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
                changes.append(
                    _PlannedChange(relative, "write", new.read_bytes(), _file_mode(new))
                )
            else:
                changes.append(_PlannedChange(relative, "delete"))
            continue
        if not old_exists and new_exists and not current_exists:
            changes.append(
                _PlannedChange(relative, "write", new.read_bytes(), _file_mode(new))
            )
            continue
        if old_exists and not new_exists and not current_exists:
            continue
        if old_exists and new_exists and current_exists:
            old_mode = _file_mode(old)
            current_mode = _file_mode(current)
            new_mode = _file_mode(new)
            merged_mode = _merge_mode(old_mode, current_mode, new_mode)
            if merged_mode is None:
                rejections.append(
                    _PlannedRejection(
                        relative,
                        _mode_conflict(relative, old_mode, current_mode, new_mode),
                    )
                )
                continue

            old_content = old.read_bytes()
            current_content = current.read_bytes()
            new_content = new.read_bytes()
            if current_content == new_content:
                merged_content = current_content
            elif current_content == old_content:
                merged_content = new_content
            elif new_content == old_content:
                merged_content = current_content
            elif all(_is_text(path) for path in (old, new, current)):
                merged, content = _merge_text(current, old, new)
                if not merged:
                    rejections.append(_PlannedRejection(relative, content.encode("utf-8")))
                    continue
                merged_content = content.encode("utf-8")
            else:
                rejections.append(_PlannedRejection(relative, new_content))
                continue

            if merged_content != current_content or merged_mode != current_mode:
                changes.append(_PlannedChange(relative, "write", merged_content, merged_mode))
            continue
        if new_exists:
            rejections.append(_PlannedRejection(relative, new.read_bytes()))
        else:
            message = f"Template removed {relative.as_posix()}, but the project changed it.\n"
            rejections.append(_PlannedRejection(relative, message.encode("utf-8")))

    return _UpdatePlan(tuple(changes), tuple(rejections), new_root)


def _identity_changed(current_state: ProjectState, target_state: ProjectState) -> bool:
    return (
        current_state.schema_version != target_state.schema_version
        or current_state.template_version != target_state.template_version
        or current_state.template_digest != target_state.template_digest
    )


def _breaking_changes(
    current_state: ProjectState, target_state: ProjectState
) -> tuple[BreakingChange, ...]:
    if (
        current_state.has_backend
        and current_state.command_name != target_state.command_name
    ):
        return (
            BreakingChange(
                code="generated_command_renamed",
                before=current_state.command_name,
                after=target_state.command_name,
            ),
        )
    return ()


def _sorted_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    return tuple(sorted(set(paths), key=lambda path: path.as_posix()))


def _planned_result(
    project_dir: Path,
    current_state: ProjectState,
    target_state: ProjectState,
    plan: _UpdatePlan,
) -> tuple[UpdateResult, bytes, bool, bool]:
    baseline_payload = _baseline_bytes(plan.new_root)
    state_payload = dump_state(target_state).encode("utf-8")
    state_path = project_dir / STATE_FILE
    baseline_path = project_dir / METADATA_DIR / BASELINE_FILE
    state_snapshot = _snapshot_file(state_path, project_dir)
    baseline_snapshot = _snapshot_file(baseline_path, project_dir)
    state_changed = state_snapshot.content != state_payload
    baseline_changed = baseline_snapshot.content != baseline_payload
    changed_paths = [change.relative for change in plan.changes]
    if state_changed:
        changed_paths.append(Path(STATE_FILE))
    if baseline_changed:
        changed_paths.append(Path(METADATA_DIR) / BASELINE_FILE)
    conflicts = _sorted_paths(rejection.relative for rejection in plan.rejections)
    changed = _sorted_paths(changed_paths)
    if conflicts:
        status: UpdateStatus = "conflicts"
    elif changed or _identity_changed(current_state, target_state):
        status = "update_available"
    else:
        status = "up_to_date"
    result = UpdateResult(
        status=status,
        project=project_dir,
        target_template_version=target_state.template_version,
        target_template_digest=target_state.template_digest,
        identity_changed=_identity_changed(current_state, target_state),
        changed_paths=changed,
        conflict_paths=conflicts,
        rejection_paths=(),
        breaking_changes=_breaking_changes(current_state, target_state),
    )
    return result, baseline_payload, state_changed, baseline_changed


def preview_controlled_update(
    project_dir: Path,
    current_state: ProjectState,
    target_state: ProjectState,
) -> UpdateResult:
    """Compare with the installed template without changing any project path."""

    project_dir = _absolute_without_symlink_resolution(project_dir)
    require_clean_git(project_dir)
    with tempfile.TemporaryDirectory(prefix="project-forge-check-") as temp_dir:
        plan = _plan_controlled_update(project_dir, target_state, Path(temp_dir))
        result, _, _, _ = _planned_result(
            project_dir, current_state, target_state, plan
        )
        return result


def apply_controlled_update(
    project_dir: Path,
    target_state: ProjectState,
    current_state: ProjectState | None = None,
) -> UpdateResult:
    project_dir = _absolute_without_symlink_resolution(project_dir)
    require_clean_git(project_dir)
    if current_state is None:
        _assert_safe_project_file(project_dir, project_dir / STATE_FILE)
        current_state = load_state(project_dir)
    with tempfile.TemporaryDirectory(prefix="project-forge-update-") as temp_dir:
        work = Path(temp_dir)
        plan = _plan_controlled_update(project_dir, target_state, work)
        preview, baseline_payload, state_changed, baseline_changed = _planned_result(
            project_dir, current_state, target_state, plan
        )
        if plan.rejections:
            rejection_paths = _sorted_paths(
                _write_project_rejection(project_dir, rejection).relative_to(project_dir)
                for rejection in plan.rejections
            )
            return UpdateResult(
                status="conflicts",
                project=preview.project,
                target_template_version=preview.target_template_version,
                target_template_digest=preview.target_template_digest,
                identity_changed=preview.identity_changed,
                changed_paths=preview.changed_paths,
                conflict_paths=preview.conflict_paths,
                rejection_paths=rejection_paths,
                breaking_changes=preview.breaking_changes,
            )
        if preview.status == "up_to_date":
            return preview

        state_path = project_dir / STATE_FILE
        baseline_path = project_dir / METADATA_DIR / BASELINE_FILE
        snapshots = [
            *(
                _snapshot_file(project_dir / change.relative, project_dir)
                for change in plan.changes
            ),
        ]
        if state_changed:
            snapshots.append(_snapshot_file(state_path, project_dir))
        if baseline_changed:
            snapshots.append(_snapshot_file(baseline_path, project_dir))
        try:
            for change in plan.changes:
                current = project_dir / change.relative
                _assert_safe_project_file(project_dir, current)
                if change.action == "write":
                    if change.content is None or change.mode is None:  # pragma: no cover
                        raise AssertionError("write change is missing content or mode")
                    _atomic_write_bytes(
                        current,
                        change.content,
                        change.mode,
                        project_dir=project_dir,
                    )
                elif current.is_file():
                    current.unlink()
                    _prune_empty_parents(current, project_dir)

            if state_changed:
                state_mode = _file_mode(state_path) if state_path.is_file() else 0o644
                _atomic_write_bytes(
                    state_path,
                    dump_state(target_state).encode("utf-8"),
                    state_mode,
                    project_dir=project_dir,
                )
            if baseline_changed:
                _atomic_write_bytes(
                    baseline_path,
                    baseline_payload,
                    0o644,
                    project_dir=project_dir,
                )
        except BaseException as error:
            rollback_errors: list[Exception] = []
            for snapshot in reversed(snapshots):
                try:
                    _restore_snapshot(snapshot, project_dir)
                except Exception as rollback_error:  # pragma: no cover - catastrophic filesystem
                    rollback_errors.append(rollback_error)
            if rollback_errors:
                details = "; ".join(str(item) for item in rollback_errors)
                raise ProjectForgeError(
                    f"update failed and rollback was incomplete: {details}"
                ) from error
            raise
        return UpdateResult(
            status="updated",
            project=preview.project,
            target_template_version=preview.target_template_version,
            target_template_digest=preview.target_template_digest,
            identity_changed=preview.identity_changed,
            changed_paths=preview.changed_paths,
            conflict_paths=(),
            rejection_paths=(),
            breaking_changes=preview.breaking_changes,
        )


def tool_version(command: str, *arguments: str) -> str | None:
    executable = shutil.which(command)
    if executable is None:
        return None
    try:
        process = subprocess.run(
            [executable, *(arguments or ("--version",))],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if process.returncode != 0:
        return None
    output = process.stdout.strip() or process.stderr.strip()
    return output.splitlines()[0] if output else "installed"


def _absolute_without_symlink_resolution(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _symlink_component(path: Path) -> Path | None:
    for candidate in reversed((path, *path.parents)):
        if candidate.is_symlink() or _is_junction(candidate):
            return candidate
    return None


def _is_junction(path: Path) -> bool:
    junction_check = getattr(path, "is_junction", None)
    if junction_check is not None:
        return bool(junction_check())
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_point and attributes & reparse_point)


def copy_skill(destination: Path, *, overwrite: bool = False) -> Path:
    destination = _absolute_without_symlink_resolution(destination)
    linked = _symlink_component(destination)
    if linked is not None:
        raise ProjectForgeError(
            f"skill destination must not contain symbolic links or junctions: {linked}"
        )
    source = Path(__file__).resolve().parent / "bundled_skill"
    if destination.exists():
        if not overwrite:
            raise ProjectForgeError(f"skill already exists: {destination}")
        if not destination.is_dir():
            raise ProjectForgeError(f"skill destination is not a directory: {destination}")
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    for root, directories, files in os.walk(destination):
        for name in directories:
            os.chmod(Path(root) / name, 0o755)
        for name in files:
            os.chmod(Path(root) / name, 0o755 if name.endswith(".sh") else 0o644)
    return destination
