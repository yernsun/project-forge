from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*command: str) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def quality() -> None:
    run("uv", "run", "--frozen", "ruff", "check", ".")
    run("uv", "run", "--frozen", "mypy", "src/project_forge")
    run("uv", "run", "--frozen", "pytest", "-n", "auto")
    run("uv", "run", "--frozen", "python", "harness/validate_skill.py")


def contracts() -> None:
    run(
        "uv",
        "run",
        "--frozen",
        "python",
        "harness/manage_openapi_contracts.py",
        "--check",
    )


def compatibility() -> None:
    run(
        "uv",
        "run",
        "--frozen",
        "pytest",
        "-n",
        "auto",
        "--no-cov",
        "-m",
        "compat",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Project Forge validation gates.")
    parser.add_argument(
        "--mode",
        choices=("full", "quality", "contracts", "compatibility"),
        default="full",
        help="validation slice to run (default: full)",
    )
    return parser.parse_args()


def main() -> int:
    mode = parse_args().mode
    if mode in {"full", "quality"}:
        quality()
    if mode in {"full", "contracts"}:
        contracts()
    if mode == "compatibility":
        compatibility()
    return 0


if __name__ == "__main__":
    sys.exit(main())
