from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import typer

from app.db.migration_engine import MigrationRunner
from app.db.pool import create_pool
from app.db.registry import MIGRATIONS
from app.settings import get_settings

app = typer.Typer(no_args_is_help=True)
migrate = typer.Typer(help="Manage the immutable migration DAG")
app.add_typer(migrate, name="migrate")


@asynccontextmanager
async def _runner() -> AsyncIterator[MigrationRunner]:
    settings = get_settings()
    pool = create_pool(settings.database_url)
    await pool.open()
    try:
        async with pool.connection() as connection:
            yield MigrationRunner(connection, MIGRATIONS)
    finally:
        await pool.close()


@migrate.command("status")
def migration_status() -> None:
    async def run() -> None:
        async with _runner() as runner:
            for entry in await runner.status():
                typer.echo(f"{entry.state.value:8} {entry.migration_id} {entry.checksum[:12]}")

    asyncio.run(run())


@migrate.command("validate")
def migration_validate() -> None:
    async def run() -> None:
        async with _runner() as runner:
            await runner.validate()

    asyncio.run(run())
    typer.echo("migration history is valid")


@migrate.command("up")
def migration_up() -> None:
    async def run() -> tuple[str, ...]:
        async with _runner() as runner:
            return await runner.up()

    applied = asyncio.run(run())
    typer.echo("applied: " + (", ".join(applied) if applied else "none"))


def main() -> None:
    app()
