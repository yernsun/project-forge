from __future__ import annotations

import logging
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

_DOMAIN_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_INSTANCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """Validated file-routing settings for one process domain and instance."""

    domain: str
    instance: str
    root: Path
    environment: str
    level_name: str
    level: int
    max_bytes: int
    backup_count: int
    sql_enabled: bool
    sql_slow_ms: float

    @property
    def directory(self) -> Path:
        return self.root / self.domain / self.instance


def build_logging_config(
    *,
    domain: str,
    instance: str,
    root: str | Path,
    environment: str,
    level: str,
    max_bytes: int,
    backup_count: int,
    sql_enabled: bool,
    sql_slow_ms: float,
) -> LoggingConfig:
    normalized_domain = domain.strip().lower()
    if len(normalized_domain) > 64 or _DOMAIN_PATTERN.fullmatch(normalized_domain) is None:
        raise ValueError("logging domain must be a lowercase hyphenated name")
    normalized_instance = instance.strip()
    if _INSTANCE_PATTERN.fullmatch(normalized_instance) is None:
        raise ValueError(
            "logging instance must contain only letters, digits, dot, underscore, or hyphen"
        )
    normalized_level = level.strip().upper()
    if normalized_level not in _LEVELS:
        raise ValueError(
            "unsupported log level; expected one of " + ", ".join(_LEVELS)
        )
    if max_bytes <= 0:
        raise ValueError("log max bytes must be positive")
    if backup_count < 1:
        raise ValueError("log backup count must be at least one")
    if sql_slow_ms < 0:
        raise ValueError("SQL slow threshold cannot be negative")
    normalized_environment = environment.strip() or "unknown"
    normalized_root = Path(root).expanduser()
    return LoggingConfig(
        domain=normalized_domain,
        instance=normalized_instance,
        root=normalized_root,
        environment=normalized_environment,
        level_name=normalized_level,
        level=_LEVELS[normalized_level],
        max_bytes=max_bytes,
        backup_count=backup_count,
        sql_enabled=sql_enabled,
        sql_slow_ms=float(sql_slow_ms),
    )


def prepare_log_directory(config: LoggingConfig) -> Path:
    """Create the isolated directory without following managed path links."""

    root = config.root.absolute()
    _reject_link_components(root)
    root.mkdir(parents=True, exist_ok=True)
    _reject_link_components(root)
    directory = root / config.domain / config.instance
    directory.mkdir(parents=True, exist_ok=True)
    _reject_link_components(directory)
    try:
        directory.relative_to(root)
    except ValueError as error:  # pragma: no cover - validated components make this defensive
        raise ValueError("logging directory escapes the configured root") from error
    for filename in ("business.log", "debug.log", "error.log", "sql.log"):
        target = directory / filename
        if os.path.lexists(target) and (
            _is_link_or_junction(target) or not target.is_file()
        ):
            raise ValueError(f"logging target must be a regular file: {target}")
    return directory


def _reject_link_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if os.path.lexists(current) and _is_link_or_junction(current):
            raise ValueError(f"logging paths must not contain symlinks or junctions: {current}")


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(reparse_flag and file_attributes & reparse_flag)
