from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
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


def _run_checks() -> int:
    run([sys.executable, "harness/check_architecture.py"])
    run([sys.executable, "harness/check_sql.py"])
    run([sys.executable, "harness/check_i18n.py"])
    backend = ROOT / "backend"
    if backend.exists() and require("uv"):
        sync = ["uv", "sync", "--frozen", "--all-groups"]
        if (backend / "src/app/auth").exists():
            sync.extend(["--extra", "auth"])
        if (backend / "src/app/events").exists():
            sync.extend(["--extra", "evented"])
        run(sync, backend)
        run(["uv", "run", "--frozen", "--no-sync", "ruff", "check", "."], backend)
        run(["uv", "run", "--frozen", "--no-sync", "mypy", "src/app"], backend)
        pytest = ["uv", "run", "--frozen", "--no-sync", "pytest"]
        if STRICT:
            pytest.extend(
                [
                    "--cov=app",
                    "--cov-branch",
                    "--cov-report=term-missing",
                    "--cov-fail-under=65",
                ]
            )
        run(pytest, backend)
    frontend = ROOT / "frontend"
    if frontend.exists() and require("npm"):
        install = ["npm", "ci"] if (frontend / "package-lock.json").exists() else ["npm", "install"]
        run(install, frontend)
        test_script = "test:coverage" if STRICT else "test"
        for script in ("lint", "typecheck", test_script, "build"):
            run(["npm", "run", script], frontend)
    if backend.exists() and frontend.exists() and require("uv") and require("npm"):
        with tempfile.TemporaryDirectory(prefix="project-forge-openapi-") as temp_dir:
            contract = Path(temp_dir) / "openapi.json"
            run(
                [
                    "uv",
                    "run",
                    "--frozen",
                    "--no-sync",
                    "python",
                    "../harness/export_openapi.py",
                    str(contract),
                ],
                backend,
            )
            run(
                [
                    "node",
                    "scripts/generate-api.mjs",
                    "--check",
                    "--source",
                    str(contract),
                ],
                frontend,
            )
    if os.getenv("HARNESS_DOCKER") == "1" and require("docker"):
        run(["docker", "compose", "-f", "docker-compose.dev.yml", "config"])
        run(["docker", "compose", "-f", "docker-compose.yml", "config"])
    return 0


def main() -> int:
    try:
        return _run_checks()
    except subprocess.CalledProcessError as error:
        return error.returncode if error.returncode > 0 else 1
    except RuntimeError as error:
        print(f"harness error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
