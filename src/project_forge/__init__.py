"""Project Forge public package."""

from importlib.metadata import PackageNotFoundError, version

__version__: str
try:
    __version__ = version("project-forge")
except PackageNotFoundError:  # pragma: no cover - only possible for an uninstalled source tree
    __version__ = "0+unknown"

from project_forge.config import ProjectState

__all__ = ["ProjectState", "__version__"]
