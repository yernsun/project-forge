import tomllib
from importlib.metadata import version
from pathlib import Path

import yaml

from project_forge import __version__
from project_forge.config import ProjectState
from project_forge.identity import CURRENT_STATE_SCHEMA_VERSION, current_template_digest

ROOT = Path(__file__).resolve().parents[1]


def test_version_comes_from_distribution_metadata() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = project["project"]["version"]
    root_copier = yaml.safe_load((ROOT / "copier.yml").read_text(encoding="utf-8"))
    packaged_copier = yaml.safe_load(
        (ROOT / "src/project_forge/template/copier.yml").read_text(encoding="utf-8")
    )

    assert __version__ == version("project-forge") == declared
    assert ProjectState.create("Version Fixture").template_version == declared
    assert str(root_copier["template_version"]["default"]) == declared
    assert str(packaged_copier["template_version"]["default"]) == declared
    assert root_copier["schema_version"]["default"] == CURRENT_STATE_SCHEMA_VERSION
    assert packaged_copier["schema_version"]["default"] == CURRENT_STATE_SCHEMA_VERSION
    assert root_copier["template_digest"] == packaged_copier["template_digest"] == {
        "type": "str",
        "default": "",
        "when": False,
    }
    assert ProjectState.create("Digest Fixture").template_digest == current_template_digest()
