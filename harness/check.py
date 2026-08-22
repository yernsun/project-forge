from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*command: str) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    run("uv", "run", "--frozen", "ruff", "check", ".")
    run("uv", "run", "--frozen", "mypy", "src/project_forge")
    run("uv", "run", "--frozen", "pytest")
    run("uv", "run", "--frozen", "python", "harness/validate_skill.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
