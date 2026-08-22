from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_bundled_skill_metadata_is_valid_and_identical() -> None:
    repository = ROOT / ".agents/skills/project-forge-init"
    bundled = ROOT / "src/project_forge/bundled_skill"
    for relative in ("SKILL.md", "agents/openai.yaml", "references/options.md"):
        assert (repository / relative).read_bytes() == (bundled / relative).read_bytes()
    metadata = yaml.safe_load((bundled / "agents/openai.yaml").read_text(encoding="utf-8"))
    assert "$project-forge-init" in metadata["interface"]["default_prompt"]
