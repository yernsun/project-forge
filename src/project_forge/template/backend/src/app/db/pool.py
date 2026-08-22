from __future__ import annotations

from typing import cast

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.db.types import DbPool


def create_pool(database_url: str) -> DbPool:
    return cast(
        DbPool,
        AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=10,
            open=False,
            kwargs={"row_factory": dict_row},
        ),
    )
