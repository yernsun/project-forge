from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRICT = os.getenv("HARNESS_STRICT") == "1"


def run(command: list[str], cwd: Path = ROOT) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def require(tool: str) -> bool:
    found = shutil.which(tool) is not None
    if not found and STRICT:
        raise RuntimeError(f"required tool is missing: {tool}")
    if not found:
        print(f"skip: {tool} is not installed")
    return found


def main() -> int:
    run([sys.executable, "harness/check_sql.py"])
    run([sys.executable, "harness/check_i18n.py"])
    backend = ROOT / "backend"
    if backend.exists() and require("uv"):
        run(["uv", "sync", "--frozen", "--all-extras", "--all-groups"], backend)
        run(["uv", "run", "--frozen", "ruff", "check", "."], backend)
        run(["uv", "run", "--frozen", "mypy", "src/app"], backend)
        run(["uv", "run", "--frozen", "pytest"], backend)
    frontend = ROOT / "frontend"
    if frontend.exists() and require("npm"):
        install = ["npm", "ci"] if (frontend / "package-lock.json").exists() else ["npm", "install"]
        run(install, frontend)
        for script in ("lint", "typecheck", "test", "build"):
            run(["npm", "run", script], frontend)
    if os.getenv("HARNESS_DOCKER") == "1" and require("docker"):
        run(["docker", "compose", "-f", "docker-compose.dev.yml", "config"])
        run(["docker", "compose", "-f", "docker-compose.yml", "config"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
