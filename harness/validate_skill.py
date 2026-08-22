from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def validate(skill: Path) -> None:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"missing YAML frontmatter: {skill}")
    _, frontmatter, _ = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    if set(metadata) != {"name", "description"}:
        raise ValueError(f"unexpected SKILL.md metadata: {metadata}")
    if metadata["name"] != "project-forge-init":
        raise ValueError("unexpected skill name")
    openai = yaml.safe_load((skill / "agents/openai.yaml").read_text(encoding="utf-8"))
    if "$project-forge-init" not in openai["interface"]["default_prompt"]:
        raise ValueError("default_prompt must mention the skill")


def main() -> None:
    repository_skill = ROOT / ".agents/skills/project-forge-init"
    bundled_skill = ROOT / "src/project_forge/bundled_skill"
    validate(repository_skill)
    validate(bundled_skill)
    for relative in ("SKILL.md", "agents/openai.yaml", "references/options.md"):
        if (repository_skill / relative).read_bytes() != (bundled_skill / relative).read_bytes():
            raise ValueError(f"bundled skill drift: {relative}")


if __name__ == "__main__":
    main()
