from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from project_forge.config import Profile, ProjectState
from project_forge.renderer import render_fresh

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_FRONTEND = ROOT / "src/project_forge/template/frontend"
CONTRACTS = TEMPLATE_FRONTEND / "scripts/openapi/contracts"
GENERATED = TEMPLATE_FRONTEND / "scripts/openapi/generated"


@dataclass(frozen=True, slots=True)
class ContractVariant:
    filename: str
    auth: bool
    sample: bool


VARIANTS = (
    ContractVariant("core", auth=False, sample=False),
    ContractVariant("sample", auth=False, sample=True),
    ContractVariant("auth", auth=True, sample=False),
    ContractVariant("auth-sample", auth=True, sample=True),
)


def run(command: list[str], *, cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def require_tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"required tool is missing: {name}")
    return executable


def export_contracts(work: Path, uv: str) -> tuple[dict[str, Path], Path]:
    actual_directory = work / "contracts"
    actual_directory.mkdir()
    actual: dict[str, Path] = {}
    frontend: Path | None = None

    for variant in VARIANTS:
        rendered = work / f"render-{variant.filename}"
        state = ProjectState.create(
            "Auth Matrix",
            profile=Profile.FULLSTACK,
            auth=variant.auth,
            sample=variant.sample,
        )
        render_fresh(state, rendered)
        frontend = frontend or rendered / "frontend"
        backend = rendered / "backend"
        sync = [uv, "sync", "--frozen", "--no-dev"]
        if variant.auth:
            sync.extend(["--extra", "auth"])
        run(sync, cwd=backend)

        target = actual_directory / f"{variant.filename}.json"
        run(
            [
                str(backend / ".venv/bin/python"),
                str(rendered / "harness/export_openapi.py"),
                str(target),
            ],
            cwd=backend,
        )
        actual[variant.filename] = target

    if frontend is None:  # pragma: no cover - VARIANTS is intentionally non-empty
        raise AssertionError("no OpenAPI variants configured")
    return actual, frontend


def generate_types(
    work: Path,
    frontend: Path,
    contracts: dict[str, Path],
    npm: str,
    node: str,
) -> dict[str, Path]:
    run([npm, "ci", "--ignore-scripts"], cwd=frontend)
    cli = frontend / "node_modules/openapi-typescript/bin/cli.js"
    output_directory = work / "types"
    output_directory.mkdir()
    generated: dict[str, Path] = {}
    for variant in VARIANTS:
        target = output_directory / f"{variant.filename}.d.ts"
        run(
            [node, str(cli), str(contracts[variant.filename]), "--output", str(target)],
            cwd=frontend,
        )
        generated[variant.filename] = target
    return generated


def json_document(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def check_outputs(contracts: dict[str, Path], generated: dict[str, Path]) -> int:
    stale: list[str] = []
    for variant in VARIANTS:
        tracked_contract = CONTRACTS / f"{variant.filename}.json"
        tracked_types = GENERATED / f"{variant.filename}.d.ts"
        if not tracked_contract.is_file() or json_document(tracked_contract) != json_document(
            contracts[variant.filename]
        ):
            stale.append(str(tracked_contract.relative_to(ROOT)))
        if not tracked_types.is_file() or tracked_types.read_bytes() != generated[
            variant.filename
        ].read_bytes():
            stale.append(str(tracked_types.relative_to(ROOT)))
    if stale:
        print("managed OpenAPI artifacts are stale:", file=sys.stderr)
        for path in stale:
            print(f"  {path}", file=sys.stderr)
        print(
            "run `uv run python harness/manage_openapi_contracts.py --refresh`",
            file=sys.stderr,
        )
        return 1
    print("all four managed OpenAPI contracts and TypeScript artifacts are current")
    return 0


def replace_outputs(contracts: dict[str, Path], generated: dict[str, Path]) -> None:
    for directory in (CONTRACTS, GENERATED):
        directory.mkdir(parents=True, exist_ok=True)
    for variant in VARIANTS:
        shutil.copy2(contracts[variant.filename], CONTRACTS / f"{variant.filename}.json")
        shutil.copy2(generated[variant.filename], GENERATED / f"{variant.filename}.d.ts")
    print("refreshed all four managed OpenAPI contracts and TypeScript artifacts")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export and verify or refresh the four real FastAPI OpenAPI contracts."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="fail when a managed artifact drifts")
    action.add_argument("--refresh", action="store_true", help="replace managed artifacts")
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        uv = require_tool("uv")
        npm = require_tool("npm")
        node = require_tool("node")
        with tempfile.TemporaryDirectory(prefix="project-forge-contracts-") as temp_dir:
            work = Path(temp_dir)
            contracts, frontend = export_contracts(work, uv)
            generated = generate_types(work, frontend, contracts, npm, node)
            if arguments.refresh:
                replace_outputs(contracts, generated)
                return 0
            return check_outputs(contracts, generated)
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"contract management failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
