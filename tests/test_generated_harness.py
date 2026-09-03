from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from project_forge.config import Profile, ProjectState
from project_forge.renderer import render_fresh

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ACTION_REFS = {
    "actions/checkout": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-node": "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020",
    "astral-sh/setup-uv": "astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d",
    "actions/attest-build-provenance": (
        "actions/attest-build-provenance@96278af6caaf10aea03fd8d33a09a777ca52d62f"
    ),
}

REPRESENTATIVE_STATES = (
    ProjectState.create("Frontend Minimal", profile=Profile.FRONTEND, sample=False),
    ProjectState.create("Frontend Sample", profile=Profile.FRONTEND, sample=True),
    ProjectState.create("Backend Minimal", profile=Profile.BACKEND, sample=False),
    ProjectState.create(
        "Backend Maximal",
        profile=Profile.BACKEND,
        auth=True,
        evented=True,
        sample=True,
    ),
    ProjectState.create(
        "Fullstack Auth Sample",
        profile=Profile.FULLSTACK,
        auth=True,
        sample=True,
    ),
    ProjectState.create(
        "Fullstack Auth Evented",
        profile=Profile.FULLSTACK,
        auth=True,
        evented=True,
        sample=False,
    ),
)


def assert_expected_action_refs(workflow: dict[str, object]) -> None:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    for job in jobs.values():
        assert isinstance(job, dict)
        for step in job.get("steps", []):
            uses = step.get("uses")
            if not isinstance(uses, str):
                continue
            action = uses.partition("@")[0]
            if action in EXPECTED_ACTION_REFS:
                assert uses == EXPECTED_ACTION_REFS[action]


@pytest.mark.parametrize("state", REPRESENTATIVE_STATES, ids=lambda state: state.project_slug)
def test_static_generated_harnesses_pass(state: ProjectState, tmp_path: Path) -> None:
    destination = tmp_path / "project"
    render_fresh(state, destination)
    harness_source = (destination / "harness/check.py").read_text(encoding="utf-8")
    assert '"--cov-fail-under=90"' in harness_source
    assert '"--env-file"' in harness_source
    assert "harness-only-rate-limit-secret-at-least-32-bytes" in harness_source
    assert f'"{state.command_name}", "--help"' in harness_source
    for script in ("check_architecture.py", "check_sql.py", "check_i18n.py"):
        subprocess.run(
            [sys.executable, f"harness/{script}"],
            cwd=destination,
            check=True,
            capture_output=True,
            text=True,
        )

    if state.has_backend:
        subprocess.run(
            ["ruff", "check", "tests/test_runtime_coverage.py"],
            cwd=destination / "backend",
            check=True,
            capture_output=True,
            text=True,
        )

    workflow = yaml.safe_load(
        (destination / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    assert_expected_action_refs(workflow)
    validate = workflow["jobs"]["validate"]
    services = validate.get("services", {})
    if state.has_backend:
        assert services["postgres"]["image"] == "postgres:16-alpine"
    else:
        assert "postgres" not in services
    if state.evented:
        assert services["redis"]["image"] == "redis:7-alpine"
    else:
        assert "redis" not in services
    environment = validate.get("env", {})
    if state.auth:
        assert environment["PROJECT_FORGE_DESTRUCTIVE_PG_TESTS"] == "1"
        auth_tests = (destination / "backend/tests/test_auth.py").read_text(
            encoding="utf-8"
        )
        assert "unstyle(result.stdout)" in auth_tests
    else:
        assert "PROJECT_FORGE_DESTRUCTIVE_PG_TESTS" not in environment
    if state.profile is Profile.FRONTEND and state.sample:
        assert (
            environment["FRONTEND_API_UPSTREAM"]
            == "http://host.docker.internal:8000"
        )
    else:
        assert "FRONTEND_API_UPSTREAM" not in environment

    node_steps = [
        step
        for step in validate["steps"]
        if step.get("uses") == EXPECTED_ACTION_REFS["actions/setup-node"]
    ]
    python_steps = [
        step
        for step in validate["steps"]
        if step.get("uses") == EXPECTED_ACTION_REFS["astral-sh/setup-uv"]
    ]
    if state.has_backend:
        assert python_steps and all(
            step["with"]["python-version"] == "3.13" for step in python_steps
        )
    else:
        assert not python_steps
    if state.has_frontend:
        assert node_steps and all(step["with"]["node-version"] == "24" for step in node_steps)
    else:
        assert not node_steps

    emits_auth_e2e = state.profile is Profile.FULLSTACK and state.auth and state.sample
    assert ("auth-compose-e2e" in workflow["jobs"]) is emits_auth_e2e
    assert ("production-compose-smoke" in workflow["jobs"]) is emits_auth_e2e
    assert "security-audit" in workflow["jobs"]
    if emits_auth_e2e:
        auth_flow = (
            destination / "frontend/tests/e2e/auth-flow.e2e.ts"
        ).read_text(encoding="utf-8")
        assert "@example.com" in auth_flow
        assert "@example.test" not in auth_flow
        assert "expect((await signupResponse).status()).toBe(201)" in auth_flow
        e2e = workflow["jobs"]["auth-compose-e2e"]
        assert e2e["needs"] == "validate"
        assert "services" not in e2e
        commands = "\n".join(str(step.get("run", "")) for step in e2e["steps"])
        assert "docker compose -f docker-compose.dev.yml up -d --build" in commands
        assert "http://localhost:5173/health/ready" in commands
        assert "npm run e2e:install" in commands
        assert "npm run e2e" in commands
        assert "docker compose -f docker-compose.dev.yml logs" in commands
        assert "docker compose -f docker-compose.dev.yml down --volumes" in commands
        step_names = [step.get("name") for step in e2e["steps"]]
        assert step_names.index("Install browser test dependencies") < step_names.index(
            "Start development Compose stack"
        )
        cleanup = [step for step in e2e["steps"] if step.get("if") == "always()"]
        assert {step["name"] for step in cleanup} == {
            "Show Compose logs",
            "Stop Compose stack",
        }
        production = workflow["jobs"]["production-compose-smoke"]
        production_commands = "\n".join(
            str(step.get("run", "")) for step in production["steps"]
        )
        assert "APP_ALLOWED_ORIGINS=https://172.20.0.10:8443" in production_commands
        assert "docker compose --env-file .env.ci up -d --build" in production_commands
        assert "http://127.0.0.1:8080/health/ready" in production_commands


def test_top_level_harness_reports_python_311_syntax_cleanly(tmp_path: Path) -> None:
    destination = tmp_path / "project"
    render_fresh(
        ProjectState.create("Python Floor", profile=Profile.BACKEND, sample=False),
        destination,
    )
    incompatible = destination / "backend/src/app/domain/incompatible.py"
    incompatible.write_text("type NewAlias = dict[str, object]\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "harness/check.py"],
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "compatible with Python 3.11" in result.stderr
    assert "incompatible.py:1" in result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_root_ci_uses_supported_service_versions_and_frozen_commands() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    assert_expected_action_refs(workflow)
    quality = workflow["jobs"]["generator-quality"]
    assert "strategy" not in quality
    quality_python = [
        step
        for step in quality["steps"]
        if step.get("uses") == EXPECTED_ACTION_REFS["astral-sh/setup-uv"]
    ]
    assert quality_python[0]["with"]["python-version"] == "3.13"
    quality_commands = "\n".join(str(step.get("run", "")) for step in quality["steps"])
    assert "harness/check.py --mode quality" in quality_commands

    compatibility = workflow["jobs"]["generator-python-compatibility"]
    assert compatibility["strategy"]["matrix"]["python-version"] == [
        "3.11",
        "3.12",
        "3.14",
    ]
    compatibility_commands = "\n".join(
        str(step.get("run", "")) for step in compatibility["steps"]
    )
    assert "harness/check.py --mode compatibility" in compatibility_commands

    contracts = workflow["jobs"]["openapi-contracts"]
    contract_node_steps = [
        step
        for step in contracts["steps"]
        if step.get("uses") == EXPECTED_ACTION_REFS["actions/setup-node"]
    ]
    assert contract_node_steps[0]["with"]["node-version"] == "24"
    contract_commands = "\n".join(str(step.get("run", "")) for step in contracts["steps"])
    assert "harness/check.py --mode contracts" in contract_commands

    generated = workflow["jobs"]["generated-projects"]
    assert generated["services"]["postgres"]["image"] == "postgres:16-alpine"
    assert generated["env"]["PROJECT_FORGE_DESTRUCTIVE_PG_TESTS"] == "1"
    assert (
        generated["env"]["FRONTEND_API_UPSTREAM"]
        == "http://host.docker.internal:8000"
    )
    matrix = {entry["name"]: entry for entry in generated["strategy"]["matrix"]["include"]}
    assert matrix["frontend-sample"]["arguments"] == "--profile frontend --sample"
    generated_node_steps = [
        step
        for step in generated["steps"]
        if step.get("uses") == EXPECTED_ACTION_REFS["actions/setup-node"]
    ]
    assert generated_node_steps[0]["with"]["node-version"] == "24"
    steps = "\n".join(str(step.get("run", "")) for step in generated["steps"])
    assert "uv sync --frozen --all-groups" in steps
    assert "--command-name generated-app" in steps
    assert "uv run --frozen --no-sync generated-app migrate up" in steps
    e2e = workflow["jobs"]["fullstack-auth-compose-e2e"]
    e2e_node_steps = [
        step
        for step in e2e["steps"]
        if step.get("uses") == EXPECTED_ACTION_REFS["actions/setup-node"]
    ]
    assert e2e_node_steps[0]["with"]["node-version"] == "24"
    e2e_steps = "\n".join(str(step.get("run", "")) for step in e2e["steps"])
    assert "--profile fullstack --auth --sample --no-git" in e2e_steps
    assert "docker compose -f docker-compose.dev.yml up -d --build" in e2e_steps
    assert "npm run e2e" in e2e_steps
    e2e_step_names = [step.get("name") for step in e2e["steps"]]
    assert e2e_step_names.index("Install browser test dependencies") < e2e_step_names.index(
        "Start development Compose stack"
    )

    backend_compatibility = workflow["jobs"]["backend-runtime"]
    assert "strategy" not in backend_compatibility
    backend_commands = "\n".join(
        str(step.get("run", "")) for step in backend_compatibility["steps"]
    )
    assert "--profile backend --auth --evented --sample" in backend_commands
    assert "--command-name compat-backend --no-git" in backend_commands
    assert "compat-backend migrate up" in backend_commands
    assert "--extra auth --extra evented" in backend_commands

    frontend_compatibility = workflow["jobs"]["frontend-runtime-compatibility"]
    assert frontend_compatibility["strategy"]["matrix"]["node-version"] == ["22", "24"]
    assert frontend_compatibility["env"]["npm_config_engine_strict"] == "true"

    package = workflow["jobs"]["package-command"]
    assert package["strategy"]["matrix"]["python-version"] == ["3.11", "3.14"]
    package_commands = "\n".join(str(step.get("run", "")) for step in package["steps"])
    assert "content-agent --help" in package_commands
    assert "forge-service --help" in package_commands
    assert "python content-agent/harness/check.py" in package_commands

    platform = workflow["jobs"]["generator-platform-smoke"]
    assert platform["strategy"]["matrix"]["os"] == ["macos-latest", "windows-latest"]
    platform_commands = "\n".join(str(step.get("run", "")) for step in platform["steps"])
    assert "--no-cov" in platform_commands
    assert "test_real_windows_junction_is_rejected" in platform_commands

    security = workflow["jobs"]["security-audit"]
    security_commands = "\n".join(str(step.get("run", "")) for step in security["steps"])
    assert "pip-audit" in security_commands
    assert "npm audit --audit-level=high" in security_commands

    production = workflow["jobs"]["production-compose-smoke"]
    production_commands = "\n".join(
        str(step.get("run", "")) for step in production["steps"]
    )
    assert "APP_ALLOWED_ORIGINS=https://172.20.0.10:8443" in production_commands
    assert "http://127.0.0.1:8080/health/ready" in production_commands

    release = yaml.safe_load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    )
    assert_expected_action_refs(release)
    release_commands = "\n".join(
        str(step.get("run", "")) for step in release["jobs"]["wheel"]["steps"]
    )
    assert "cyclonedx-json" in release_commands
    assert "--no-emit-project" in release_commands
    assert "gh release create" in release_commands


def test_root_harness_exposes_full_quality_contract_and_compatibility_modes() -> None:
    source = (ROOT / "harness/check.py").read_text(encoding="utf-8")

    assert '("full", "quality", "contracts", "compatibility")' in source
    assert 'default="full"' in source
    assert '"pytest", "-n", "auto"' in source
    assert '"-m",\n        "compat"' in source
    assert '"harness/manage_openapi_contracts.py"' in source


def test_architecture_harness_rejects_boundary_bypasses(tmp_path: Path) -> None:
    destination = tmp_path / "project"
    render_fresh(
        ProjectState.create(
            "Architecture Guard",
            profile=Profile.BACKEND,
            auth=True,
            sample=True,
        ),
        destination,
    )
    app_source = destination / "backend/src/app"

    allowed = app_source / "api/allowed_factory.py"
    allowed.write_text(
        dedent(
            """
            from app.api.dependencies import UnitOfWorkFactoryDep
            from app.services.health import HealthService

            async def endpoint(factory: UnitOfWorkFactoryDep) -> bool:
                return await HealthService(factory).is_ready()
            """
        ),
        encoding="utf-8",
    )
    accepted = subprocess.run(
        [sys.executable, "harness/check_architecture.py"],
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stderr
    allowed.unlink()

    cases = (
        (
            "relative-service-repository",
            "services/forbidden_relative.py",
            """
            from ..repositories.items import ItemRepository

            repository_type = ItemRepository
            """,
            "service cannot import app.repositories.items",
        ),
        (
            "relative-domain-service",
            "domain/forbidden_relative.py",
            """
            from ..services.health import HealthService

            service_type = HealthService
            """,
            "domain cannot import app.services.health",
        ),
        (
            "relative-api-repository",
            "api/forbidden_relative.py",
            """
            from ..repositories.health import HealthRepository

            repository_type = HealthRepository
            """,
            "API cannot import infrastructure module app.repositories.health",
        ),
        (
            "sql-module-alias",
            "services/forbidden_sql_alias.py",
            """
            from psycopg import sql as pg_sql

            query = pg_sql.SQL("SELECT 1")
            """,
            "SQL composition belongs in a repository or db adapter",
        ),
        (
            "sql-constructor-alias",
            "services/forbidden_sql_constructor.py",
            """
            from psycopg.sql import Identifier as Column

            column = Column("item_id")
            """,
            "SQL composition belongs in a repository or db adapter",
        ),
        (
            "api-factory-call",
            "api/forbidden_factory.py",
            """
            from app.api.dependencies import UnitOfWorkFactoryDep as FactoryDep

            async def endpoint(factory: FactoryDep) -> object:
                return factory()
            """,
            "API cannot call UnitOfWorkFactoryDep directly",
        ),
        (
            "api-unit-of-work-entry",
            "api/forbidden_uow.py",
            """
            from app.api.dependencies import UnitOfWorkFactoryDep

            async def endpoint(factory: UnitOfWorkFactoryDep) -> object:
                async with factory() as unit_of_work:
                    return unit_of_work.items
            """,
            "API cannot enter a unit of work directly",
        ),
        (
            "api-repository-access",
            "api/forbidden_repository_access.py",
            """
            from app.api.dependencies import UnitOfWorkFactoryDep

            async def endpoint(factory: UnitOfWorkFactoryDep) -> object:
                async with factory() as unit_of_work:
                    return unit_of_work.items
            """,
            "API cannot access repositories through a unit of work",
        ),
        (
            "repository-raw-connection-import",
            "repositories/forbidden_raw_import.py",
            """
            from app.db.types import DbConnection
            from app.repositories.base import BaseRepository

            class PostgresRawRepository(BaseRepository):
                def __init__(self, connection: DbConnection) -> None:
                    self.raw = connection
            """,
            "repository cannot import raw connection dependency app.db.types",
        ),
        (
            "repository-cursor-access",
            "repositories/forbidden_cursor.py",
            """
            from app.repositories.base import BaseRepository

            class PostgresCursorRepository(BaseRepository):
                async def run(self) -> None:
                    async with self.connection.cursor() as cursor:
                        await cursor.execute("SELECT 1")
            """,
            "repository cannot acquire or operate a raw connection with cursor()",
        ),
        (
            "repository-missing-base",
            "repositories/forbidden_base.py",
            """
            from typing import Protocol

            class MissingBaseRepository(Protocol):
                async def get(self) -> None: ...
            """,
            "every repository must inherit BaseRepository",
        ),
        (
            "repository-outside-uow",
            "wiring.py",
            """
            from app.repositories.items import PostgresItemRepository

            def build(connection: object) -> PostgresItemRepository:
                return PostgresItemRepository(connection)
            """,
            "PostgresItemRepository may only be instantiated by UnitOfWork",
        ),
    )

    for name, relative, source, expected in cases:
        violation = app_source / relative
        violation.write_text(dedent(source), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "harness/check_architecture.py"],
            cwd=destination,
            check=False,
            capture_output=True,
            text=True,
        )
        violation.unlink()
        assert result.returncode == 1, f"{name} unexpectedly passed"
        assert expected in result.stderr, f"{name}: {result.stderr}"

    unit_of_work = app_source / "uow/unit.py"
    original_unit_of_work = unit_of_work.read_text(encoding="utf-8")
    uow_cases = (
        (
            """

            def forbidden_repository(self) -> PostgresItemRepository:
                return PostgresItemRepository(self._require_connection())
            """,
            "UnitOfWork repositories must be created inside @cached_property methods",
        ),
        (
            """

            @cached_property
            def forbidden_injection(self) -> PostgresItemRepository:
                return PostgresItemRepository(object())
            """,
            "must inject self._require_connection()",
        ),
    )
    for source, expected in uow_cases:
        unit_of_work.write_text(
            original_unit_of_work + dedent(source), encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, "harness/check_architecture.py"],
            cwd=destination,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert expected in result.stderr
    unit_of_work.write_text(original_unit_of_work, encoding="utf-8")


def test_sql_harness_rejects_dynamic_composition_bypasses(tmp_path: Path) -> None:
    destination = tmp_path / "project"
    render_fresh(
        ProjectState.create(
            "SQL Guard",
            profile=Profile.BACKEND,
            auth=True,
            sample=True,
        ),
        destination,
    )
    repository = destination / "backend/src/app/repositories/forbidden_sql.py"
    accepted = subprocess.run(
        [sys.executable, "harness/check_sql.py"],
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stderr

    cases = (
        (
            "direct-import",
            """
            from psycopg.sql import SQL

            def build(source: str):
                return SQL(source)
            """,
            "psycopg.sql.SQL arguments must be static literals",
        ),
        (
            "module-alias",
            """
            from psycopg import sql as pg_sql

            def build(column: str):
                return pg_sql.Identifier(column)
            """,
            "psycopg.sql.Identifier arguments must be static literals",
        ),
        (
            "imported-module-alias",
            """
            import psycopg.sql as pg_sql

            def build(value: object):
                return pg_sql.Literal(value)
            """,
            "psycopg.sql.Literal is forbidden",
        ),
        (
            "constructor-secondary-alias",
            """
            from psycopg.sql import Literal as Quoted

            First = Quoted
            Second = First

            def build(value: object):
                return Second(value)
            """,
            "psycopg.sql.Literal is forbidden",
        ),
        (
            "module-secondary-alias-concatenation",
            """
            from psycopg import sql as base_sql

            composed_sql = base_sql

            def build(suffix: str):
                return composed_sql.SQL("SELECT " + suffix)
            """,
            "psycopg.sql.SQL arguments must be static literals",
        ),
        (
            "placeholder-variable",
            """
            from psycopg.sql import Placeholder as Bind

            def build(name: str):
                return Bind(name)
            """,
            "psycopg.sql.Placeholder arguments must be static literals",
        ),
        (
            "anonymous-placeholder",
            """
            from psycopg import sql

            def build():
                return sql.Placeholder()
            """,
            "Psycopg Placeholder must have a name",
        ),
        (
            "meaningless-placeholder-name",
            """
            from psycopg import sql

            def build():
                return sql.Placeholder("p1")
            """,
            "SQL parameter 'p1' must have a descriptive name",
        ),
        (
            "direct-composed-construction",
            """
            from psycopg import sql

            def build():
                return sql.Composed([sql.SQL("SELECT 1")])
            """,
            "do not instantiate psycopg.sql.Composed directly",
        ),
        (
            "sql-f-string",
            """
            from psycopg import sql

            def build(table: str):
                return sql.SQL(f"SELECT * FROM {table}")
            """,
            "SQL f-string is forbidden",
        ),
        (
            "format-runtime-value",
            """
            from psycopg import sql

            async def run(cursor, item_id: object):
                query = sql.SQL("SELECT item_id FROM items WHERE item_id = {}").format(item_id)
                await cursor.execute(query, prepare=True)
            """,
            "SQL.format replacements must be safe Composable objects",
        ),
        (
            "join-raw-strings",
            """
            from psycopg import sql

            def build():
                return sql.SQL(", ").join(["item_id", "name"])
            """,
            "SQL.join items must be safe Composable objects",
        ),
        (
            "positional-binary-parameter",
            """
            from psycopg import sql

            QUERY = sql.SQL("SELECT item_id FROM items WHERE payload = %b")
            """,
            "positional %s/%b/%t",
        ),
        (
            "numbered-dollar-parameter",
            """
            from psycopg import sql

            QUERY = sql.SQL("SELECT item_id FROM items WHERE item_id = $1")
            """,
            "numbered dollar SQL parameters are forbidden",
        ),
        (
            "non-mapping-execute-parameters",
            """
            from psycopg import sql

            async def run(cursor, item_id: object):
                await cursor.execute(
                    sql.SQL("SELECT item_id FROM items WHERE item_id = %(item_id)s"),
                    (item_id,),
                    prepare=True,
                )
            """,
            "named Psycopg parameters require a mapping",
        ),
        (
            "executemany-positional-rows",
            """
            from psycopg import sql

            async def run(cursor, item_id: object):
                await cursor.executemany(
                    sql.SQL(
                        "INSERT INTO items (item_id) VALUES (%(item_id)s)"
                    ),
                    [(item_id,)],
                )
            """,
            "execute_many requires an iterable of named parameter mappings",
        ),
        (
            "execute-many-positional-rows",
            """
            from psycopg import sql

            async def run(connection, item_id: object):
                await connection.execute_many(
                    sql.SQL(
                        "INSERT INTO items (item_id) VALUES (%(item_id)s)"
                    ),
                    [(item_id,)],
                )
            """,
            "positional batch rows are forbidden",
        ),
        (
            "single-row-sql-loop",
            """
            from psycopg import sql

            async def run(connection, item_ids: list[object]):
                for item_id in item_ids:
                    await connection.execute(
                        sql.SQL(
                            "DELETE FROM items WHERE item_id = %(item_id)s"
                        ),
                        {"item_id": item_id},
                        prepare=True,
                    )
            """,
            "do not execute single-row SQL inside a loop",
        ),
        (
            "single-row-sql-comprehension",
            """
            from psycopg import sql

            async def run(connection, item_ids: list[object]):
                return [
                    await connection.fetch_one(
                        sql.SQL(
                            "SELECT item_id FROM items WHERE item_id = %(item_id)s"
                        ),
                        {"item_id": item_id},
                        prepare=True,
                    )
                    for item_id in item_ids
                ]
            """,
            "do not execute single-row SQL inside a loop",
        ),
        (
            "dynamic-copy-statement",
            """
            from collections.abc import Iterable, Sequence
            from psycopg import sql

            async def run(
                connection,
                fragment: sql.Composable,
                rows: Iterable[Sequence[object]],
            ):
                query = sql.SQL("COPY ") + fragment
                await connection.copy_rows(query, rows)
            """,
            "dynamic execute must contain a literal SELECT anchor",
        ),
        (
            "quoted-placeholder",
            """
            from psycopg import sql

            async def run(cursor, email: str):
                await cursor.execute(
                    sql.SQL("SELECT user_id FROM users WHERE email = '%(email)s'"),
                    {"email": email},
                    prepare=True,
                )
            """,
            "SQL parameter placeholders must not be quoted",
        ),
        (
            "invalid-placeholder-name",
            """
            from psycopg import sql

            QUERY = sql.SQL("SELECT item_id FROM items WHERE item_id = %(item-id)s")
            """,
            "SQL parameter 'item-id' must use lower_snake_case",
        ),
        (
            "unsupported-placeholder-format",
            """
            from psycopg import sql

            QUERY = sql.SQL("SELECT item_id FROM items WHERE item_id = %(item_id)d")
            """,
            "SQL parameter 'item_id' uses unsupported %d format",
        ),
        (
            "dynamic-non-select-execute",
            """
            from psycopg import sql

            async def run(cursor, fragment: sql.Composable):
                query = sql.SQL("UPDATE items SET ") + fragment
                await cursor.execute(query, prepare=False)
            """,
            "dynamic execute must contain a literal SELECT anchor",
        ),
    )

    for name, source, expected in cases:
        repository.write_text(dedent(source), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "harness/check_sql.py"],
            cwd=destination,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, f"{name} unexpectedly passed"
        assert expected in result.stderr, f"{name}: {result.stderr}"

    repository.write_text(
        dedent(
            """
            from psycopg import sql

            SORTS = {
                "name": sql.Identifier("name") + sql.SQL(" ASC"),
                "created": sql.Identifier("created_at") + sql.SQL(" DESC"),
            }

            async def run(cursor, item_id: object, updated_at: object):
                query = sql.SQL(
                    "SELECT item_id FROM items "
                    "WHERE item_id = {item_id} "
                    "AND updated_at <= %(updated_at)s "
                    "AND created_at <= %(updated_at)s "
                    "ORDER BY {ordering}, item_id ASC"
                ).format(
                    item_id=sql.Placeholder("item_id"),
                    ordering=SORTS["name"],
                )
                await cursor.execute(
                    query,
                    {"item_id": item_id, "updated_at": updated_at},
                    prepare=True,
                )
                await cursor.executemany(
                    sql.SQL(
                        "INSERT INTO items (item_id) VALUES (%(item_id)s)"
                    ),
                    [{"item_id": item_id}],
                )
                for _ in range(1):
                    await cursor.execute_many(
                        sql.SQL(
                            "INSERT INTO items (item_id) VALUES (%(item_id)s)"
                        ),
                        [{"item_id": item_id}],
                    )
                await cursor.copy_rows(
                    sql.SQL("COPY items (item_id) FROM STDIN"),
                    [],
                )
            """
        ),
        encoding="utf-8",
    )
    safe = subprocess.run(
        [sys.executable, "harness/check_sql.py"],
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )
    assert safe.returncode == 0, safe.stderr
    repository.unlink()

    migration = destination / "backend/src/app/db/migrations/forbidden.py"
    migration.write_text(
        dedent(
            """
            from app.db.migration_engine import Migration

            table_name = "items"
            FORBIDDEN = Migration(
                migration_id="9999_forbidden",
                dependencies=(),
                up_sql=f"CREATE TABLE {table_name} (item_id uuid PRIMARY KEY)",
            )
            """
        ),
        encoding="utf-8",
    )
    unsafe_migration = subprocess.run(
        [sys.executable, "harness/check_sql.py"],
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )
    assert unsafe_migration.returncode == 1
    assert "migration up_sql must be one static string literal" in unsafe_migration.stderr
    migration.unlink()

    migration.write_text(
        dedent(
            """
            from app.db.migration_engine import Migration

            FORBIDDEN = Migration(
                migration_id="9999_forbidden",
                dependencies=(),
                up_sql="INSERT INTO examples (name) VALUES (%s)",
            )
            """
        ),
        encoding="utf-8",
    )
    positional_migration = subprocess.run(
        [sys.executable, "harness/check_sql.py"],
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )
    assert positional_migration.returncode == 1
    assert "positional %s/%b/%t" in positional_migration.stderr
    migration.unlink()
