from pathlib import Path

import pytest
import yaml

from project_forge.config import Profile, ProjectState
from project_forge.renderer import render_fresh, template_path

ROOT = Path(__file__).resolve().parents[1]


def test_bundled_skill_metadata_is_valid_and_identical() -> None:
    repository = ROOT / ".agents/skills/project-forge-init"
    bundled = ROOT / "src/project_forge/bundled_skill"
    for relative in ("SKILL.md", "agents/openai.yaml", "references/options.md"):
        assert (repository / relative).read_bytes() == (bundled / relative).read_bytes()
    metadata = yaml.safe_load((bundled / "agents/openai.yaml").read_text(encoding="utf-8"))
    assert "$project-forge-init" in metadata["interface"]["default_prompt"]


@pytest.mark.parametrize("profile", Profile)
def test_primevue_skill_and_all_references_render_without_local_installation(
    profile: Profile, tmp_path: Path
) -> None:
    destination = tmp_path / "project"
    render_fresh(ProjectState.create("Bundled UI Skill", profile=profile), destination)
    relative = Path(".agents/skills/primevue-skilld")
    bundled = template_path() / relative
    rendered = destination / relative
    assets = {path.relative_to(bundled) for path in bundled.rglob("*") if path.is_file()}
    assert Path("SKILL.md") in assets
    for reference in (
        "docs/_INDEX.md",
        "docs/datatable.md",
        "issues/_INDEX.md",
        "releases/_INDEX.md",
        "releases/CHANGELOG.md",
    ):
        assert Path("references") / reference in assets
    assert {path.relative_to(rendered) for path in rendered.rglob("*") if path.is_file()} == assets
    for asset in assets:
        assert (rendered / asset).read_bytes() == (bundled / asset).read_bytes()
        assert not (rendered / asset).is_symlink()
    metadata = yaml.safe_load((rendered / "SKILL.md").read_text().split("---", 2)[1])
    assert metadata["name"] == "primevue-skilld"
